#!/usr/bin/env python3
"""Вставляет per-request трассировку в ivcrag (v2, с гарантией импорта).

  python3 patch_tracing.py --check     # показать план
  python3 patch_tracing.py             # применить
  python3 patch_tracing.py --revert    # откатить по *.bak.tracing
"""
import argparse
import pathlib
import shutil
import sys
import textwrap

OPENAI = pathlib.Path("app/api/openai.py")
ANSWERS = pathlib.Path("app/rag/answers.py")
IMPORT_LINE = "from app import tracing\n"


# ─────────────────────────── утилиты ───────────────────────────

def backup(p: pathlib.Path) -> pathlib.Path:
    b = p.with_suffix(p.suffix + ".bak.tracing")
    if not b.exists():
        shutil.copy2(p, b)
    return b


def write_if_changed(p: pathlib.Path, new_src: str, check: bool) -> bool:
    old = p.read_text(encoding="utf-8")
    if old == new_src:
        print(f"= {p}: без изменений")
        return False
    if check:
        print(f"~ {p}: будет изменён")
        return True
    backup(p)
    p.write_text(new_src, encoding="utf-8")
    print(f"✓ {p}: пропатчен (бэкап {p.name}.bak.tracing)")
    return True


def ensure_tracing_import(p: pathlib.Path, check: bool) -> bool:
    """Вставляет 'from app import tracing' после блока импортов, если его нет.

    Идемпотентно. Возвращает True, если файл был бы изменён.
    """
    src = p.read_text(encoding="utf-8")
    if IMPORT_LINE.strip() in src:
        print(f"= {p}: import tracing уже есть")
        return False

    lines = src.splitlines(keepends=True)
    out, inserted = [], False
    for line in lines:
        out.append(line)
        if not inserted and line.startswith("from app") and "import" in line:
            out.append(IMPORT_LINE)
            inserted = True
    if not inserted:
        # fallback: после последней строки import/from в шапке
        for i, line in enumerate(out):
            stripped = line.strip()
            if stripped and not stripped.startswith(("import ", "from ", "#", '"""', "'''")):
                out.insert(i, IMPORT_LINE)
                inserted = True
                break
    if not inserted:
        # совсем fallback: в начало файла
        out.insert(0, IMPORT_LINE)
        inserted = True

    if check:
        print(f"~ {p}: будет добавлен import tracing")
        return True
    backup(p)
    p.write_text("".join(out), encoding="utf-8")
    print(f"✓ {p}: добавлен import tracing")
    return True


def insert_after(src: str, anchor: str, insert: str, indent: str = "") -> str:
    """Вставляет insert сразу после первого вхождения anchor.
    indent добавляется к каждой непустой строке insert."""
    idx = src.find(anchor)
    if idx < 0:
        raise ValueError(f"anchor not found: {anchor[:60]!r}")
    end = idx + len(anchor)
    block = textwrap.indent(insert.rstrip("\n"), indent,
                            predicate=lambda line: line.strip() != "")
    return src[:end] + "\n" + block + src[end:]


# ─────────────────── 1. app/api/openai.py ───────────────────

OPENAI_HEAD = '''@router.post("/v1/chat/completions")
async def openai_chat_completions(req: _ChatCompletionRequest):
    question = _last_user_question(req.messages)
    if not question:
        raise HTTPException(status_code=400, detail="No user message found")
'''

OPENAI_WRAPPED = OPENAI_HEAD + '''    tracing.begin(
        query=question,
        params={
            "mode": getattr(state, "llm_mode", None),
            "top_k": getattr(state, "top_k", None),
            "stream": bool(getattr(req, "stream", False)),
            "max_tokens": getattr(req, "max_tokens", None),
        },
        client_ip="",
    )
    _tracing_status = "ok"
    try:
        try:
            result = _rag_answer(question, req.max_tokens)
        except Exception as exc:  # pragma: no cover
            state.log.error(f"[openai] RAG error: {exc}")
            import traceback
            state.log.error(traceback.format_exc())
            raise HTTPException(status_code=500, detail=f"RAG error: {exc}")

        tracing.stage("shortcut", {
            "no_llm": bool(result.get("no_llm")),
            "hits": result.get("hits"),
            "sources": result.get("sources"),
            "answer_chars": len(result.get("answer") or ""),
        })

        answer = result["answer"]
        tracing.stage("llm_response", {
            "answer": answer,
            "answer_chars": len(answer),
            "sources": result.get("sources"),
            "hits": result.get("hits"),
            "no_llm": bool(result.get("no_llm")),
        })

        created = int(time.time())
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

        if req.stream:
            async def event_gen():
                first = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": req.model,
                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
                }
                yield f"data: {json.dumps(first, ensure_ascii=False)}\\n\\n"
                for i in range(0, len(answer), 40):
                    chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": req.model,
                        "choices": [{"index": 0, "delta": {"content": answer[i:i + 40]}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\\n\\n"
                last = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": req.model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(last, ensure_ascii=False)}\\n\\n"
                yield "data: [DONE]\\n\\n"

            return StreamingResponse(event_gen(), media_type="text/event-stream")

        prompt_tokens = len(question) // 4
        completion_tokens = len(answer) // 4
        return JSONResponse({
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": req.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "x_rag_sources": result["sources"],
            "x_rag_hits": result["hits"],
        })
    except Exception as _exc:
        _tracing_status = "error"
        tracing.stage("error", {"type": type(_exc).__name__, "msg": str(_exc)})
        raise
    finally:
        tracing.end(status=_tracing_status)
'''


def patch_openai(check: bool) -> int:
    ensure_tracing_import(OPENAI, check)

    src = OPENAI.read_text(encoding="utf-8")
    if "tracing.begin(" in src and "finally:\n        tracing.end(" in src:
        print(f"= {OPENAI}: тело уже пропатчено")
        return 0
    if OPENAI_HEAD not in src:
        print(f"✗ {OPENAI}: не найден заголовок openai_chat_completions — не трогаю")
        return 2

    start = src.index(OPENAI_HEAD)
    nxt = src.find("\n@router", start + len(OPENAI_HEAD))
    if nxt < 0:
        print(f"✗ {OPENAI}: не найден следующий @router после эндпоинта")
        return 2

    new = src[:start] + OPENAI_WRAPPED + src[nxt:]
    write_if_changed(OPENAI, new, check)
    return 0


# ─────────────────── 2. app/rag/answers.py ───────────────────

def patch_answers(check: bool) -> int:
    ensure_tracing_import(ANSWERS, check)

    src = ANSWERS.read_text(encoding="utf-8")
    changed = False
    IND = "    "

    if 'tracing.stage("normalize"' not in src:
        src = insert_after(
            src,
            "search_question = _normalize_query_for_search(question)",
            'tracing.stage("normalize", {\n'
            '    "raw": question,\n'
            '    "normalized": search_question,\n'
            '})',
            indent=IND,
        )
        changed = True

    if 'tracing.stage("retrieval"' not in src:
        src = insert_after(
            src,
            "hits = _filter_hits_by_entity(hits, question)",
            'tracing.stage("retrieval", {\n'
            '    "n_hits": len(hits),\n'
            '    "hits": [\n'
            '        {\n'
            '            "id": str(getattr(h, "id", "")),\n'
            '            "source": (h.payload or {}).get("source"),\n'
            '            "chunk_index": (h.payload or {}).get("chunk_index"),\n'
            '            "text": (h.payload or {}).get("text"),\n'
            '            "score": getattr(h, "score", None),\n'
            '            "rank": i,\n'
            '        }\n'
            '        for i, h in enumerate(hits)\n'
            '    ],\n'
            '})',
            indent=IND,
        )
        changed = True

    if 'tracing.stage("context"' not in src:
        src = insert_after(
            src,
            "context = _build_context_adaptive(ranked, question, _ctx_relevance)",
            'tracing.stage("context", {\n'
            '    "chars": len(context),\n'
            '    "sources": sorted({hit.payload.get("source", "?") for hit in hits}),\n'
            '    "text": context,\n'
            '})',
            indent=IND,
        )
        changed = True

    if 'tracing.stage("llm_request"' not in src:
        anchor = "    try:\n        response = _post_llm(config.LLM_URL, config.LLM_MODEL)"
        if anchor not in src:
            print(f"✗ {ANSWERS}: не найден якорь llm_request")
            return 2
        insert = (
            '    tracing.stage("llm_request", {\n'
            '        "endpoint": config.LLM_URL,\n'
            '        "model": config.LLM_MODEL,\n'
            '        "fallback_enabled": bool(getattr(config, "LLM_FALLBACK_TO_LOCAL", False)),\n'
            '        "max_tokens": max_tokens or config.MAX_ANSWER_TOKENS,\n'
            '        "prompt_chars": len(user_prompt),\n'
            '        "prompt": user_prompt,\n'
            '    })\n'
        )
        src = src.replace(anchor, insert + anchor, 1)
        changed = True

    if 'tracing.stage("llm_response"' not in src:
        anchor = '    answer = data["choices"][0]["message"].get("content", "").strip() or "(пустой ответ)"\n'
        if anchor not in src:
            print(f"✗ {ANSWERS}: не найден якорь llm_response")
            return 2
        insert = (
            '    tracing.stage("llm_response", {\n'
            '        "answer": answer,\n'
            '        "answer_chars": len(answer),\n'
            '        "usage": data.get("usage"),\n'
            '        "finish_reason": (data.get("choices") or [{}])[0].get("finish_reason"),\n'
            '    })\n'
        )
        src = src.replace(anchor, anchor + insert, 1)   # ПОСЛЕ answer = ...
        changed = True

    if not changed:
        print(f"= {ANSWERS}: тело уже пропатчено")
        return 0
    write_if_changed(ANSWERS, src, check)
    return 0


# ─────────────────── sanity / revert / main ───────────────────

def sanity() -> int:
    import compileall
    ok = compileall.compile_dir("app", quiet=1)
    if not ok:
        print("✗ compileall app — FAILED")
        return 1
    print("✓ compileall app OK")
    return 0


def revert() -> int:
    n = 0
    for p in (OPENAI, ANSWERS):
        b = p.with_suffix(p.suffix + ".bak.tracing")
        if b.exists():
            shutil.move(str(b), str(p))
            print(f"✓ восстановлен {p}")
            n += 1
    if not n:
        print("✗ бэкапов не найдено")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    if a.revert:
        return revert()
    if not OPENAI.exists() or not ANSWERS.exists():
        print("✗ ожидаются app/api/openai.py и app/rag/answers.py в CWD")
        return 1
    rc = 0
    rc |= patch_openai(a.check)
    rc |= patch_answers(a.check)
    if rc == 0 and not a.check:
        rc |= sanity()
    return rc


if __name__ == "__main__":
    sys.exit(main())