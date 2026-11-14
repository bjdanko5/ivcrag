import re
from typing import List

import state
import config


def _normalize_query_for_search(question: str) -> str:
    words = question.split()
    result = []
    for w in words:
        if w and w[0].isupper() and len(w) > 4:
            if w.endswith(('ко', 'КО', 'Ко')) and len(w) > 5:
                w = w[:-1]
            elif w.endswith(('а', 'я', 'у', 'ю', 'ой', 'ей', 'ым', 'им', 'ом', 'ем')):
                w = w[:-1]
        result.append(w)
    return " ".join(result)


def _filter_hits_by_entity(hits, question: str):
    entity_words = [
        config._normalize_text(w) for w in re.findall(r'[А-ЯЁA-Z][а-яёa-z]{3,}', question)
        if config._normalize_text(w) not in {"что", "как", "где", "когда", "почему", "зачем", "какой", "какая", "какие", "телефон", "директора"}
    ]
    if not entity_words:
        return hits

    stems = []
    for w in entity_words:
        if w.endswith('ко') and len(w) > 5:
            stems.append(w[:-1])
        elif len(w) >= 5:
            stems.append(w[:5])
        elif len(w) >= 4:
            stems.append(w[:4])

    matched = [h for h in hits if any(s in config._normalize_text(h.payload.get('text', '')) for s in stems)]
    return matched if matched else hits


def _collect_all_entity_rows(source_name: str, question: str, limit: int = 200) -> list:
    entities = re.findall(r'[А-ЯЁA-Z][а-яёa-z]{3,}', question or "")
    IGNORE = {"что", "как", "где", "когда", "почему", "зачем", "какой", "какая",
              "какие", "телефон", "директора", "комната", "отдел"}
    entities = [e for e in entities if config._normalize_text(e) not in IGNORE]
    if not entities:
        return []

    def _stems_for(e):
        n = config._normalize_text(e)
        out = []
        if n.endswith('ко') and len(n) > 5:
            out.append(n[:-1])
        if len(n) >= 5:
            out.append(n[:5])
        if len(n) >= 4:
            out.append(n[:4])
        return out

    all_stems = []
    for e in entities:
        all_stems.extend(_stems_for(e))
    if not all_stems:
        return []

    try:
        scroll_filter = state.models.Filter(must=[
            state.models.FieldCondition(key="source", match=state.models.MatchValue(value=source_name))
        ])
        points, _ = state.qdrant_client.scroll(
            collection_name=config.COLLECTION_NAME,
            scroll_filter=scroll_filter,
            limit=limit,
            with_payload=True,
        )
    except Exception as e:
        state.log.warning(f"[_collect_all_entity_rows] scroll failed: {e}")
        return []

    rows = []
    for pt in points:
        text = pt.payload.get("text", "") if pt.payload else ""
        ntext = config._normalize_text(text)
        if any(st in ntext for st in all_stems):
            rows.append(text)
    return rows


def _format_department_answer(dept_query: str, all_sources_texts: list) -> str:
    def _split_rows(t):
        return [r for r in t.split('\n---\n') if r.strip()]

    pool = []
    for t in all_sources_texts:
        pool.extend(_split_rows(t))

    dq = config._normalize_text(dept_query).strip()
    if not dq or len(dq) < 2:
        return ""

    matched_rows = []
    for row in pool:
        if ':' not in row:
            continue
        fields = {}
        clean = re.sub(r'^\[[^\]]*\]\s*', '', row)
        for part in clean.split('|'):
            if ':' in part:
                k, v = part.split(':', 1)
                k = k.strip().lower()
                v = v.strip()
                if v:
                    fields[k] = v
        if not fields:
            continue
        dept_vals = []
        for k in ('отдел', 'отдел в тел.'):
            if k in fields:
                dept_vals.append(config._normalize_text(fields[k]))
        if not dept_vals:
            continue
        dq_words = dq.split()
        dq_stems = []
        for w in dq_words:
            if len(w) >= 5:
                dq_stems.append(w[:5])
            elif len(w) >= 4:
                dq_stems.append(w[:4])
            else:
                dq_stems.append(w)
        if not dq_stems:
            continue

        matched = False
        for dv in dept_vals:
            if all(st in dv for st in dq_stems):
                matched = True
                break
        if matched:
            matched_rows.append(fields)

    if not matched_rows:
        return ""

    by_fio = {}
    for f in matched_rows:
        fio = f.get('ф.и.о.') or f.get('фио') or ''
        if fio:
            by_fio[fio] = f
        else:
            by_fio[tuple(sorted(f.items()))] = f

    records = list(by_fio.values())
    if not records:
        return ""

    CANON = {
        '№': '№', 'ф.и.о.': 'Ф.И.О.', 'фио': 'Ф.И.О.',
        'отдел': 'Отдел', 'область': 'Область',
        'внут.': 'Внутренний', 'внутренний': 'Внутренний',
        'городской': 'Городской', 'мобильный': 'Мобильный',
    }
    ORDER = ['№', 'Ф.И.О.', 'Отдел', 'Область', 'Внутренний', 'Городской', 'Мобильный']

    canon_records = []
    for f in records:
        c = {}
        for k, v in f.items():
            ck = CANON.get(k)
            if ck:
                c[ck] = v
        if c.get('Ф.И.О.'):
            canon_records.append(c)

    if not canon_records:
        return ""

    present = set()
    for r in canon_records:
        present.update(r.keys())
    headers = [h for h in ORDER if h in present]

    body_lines = []
    for r in canon_records:
        vals = [r.get(h, '') for h in headers]
        body_lines.append("| " + " | ".join(vals) + " |")

    header_line = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join("---" for _ in headers) + "|"
    result = "\n".join([header_line, sep] + body_lines)
    result += f"\n\n_Сотрудников в отделе: {len(canon_records)}._"
    return result


def _format_phone_answer_from_hit(hit_text: str, question: str, all_hits_texts=None) -> str:
    def _split_rows(t):
        return [r for r in t.split('\n---\n') if r.strip()]

    pool = _split_rows(hit_text)
    if all_hits_texts:
        for t in all_hits_texts:
            if t != hit_text:
                pool.extend(_split_rows(t))

    seen = set()
    uniq_pool = []
    for r in pool:
        key = r.strip()
        if key and key not in seen:
            seen.add(key)
            uniq_pool.append(r)

    entities = re.findall(r'[А-ЯЁA-Z][а-яёa-z]{3,}', question or "")
    IGNORE = {"что", "как", "где", "когда", "почему", "зачем", "какой", "какая",
              "какие", "телефон", "директора", "комната", "отдел"}
    entities = [e for e in entities if config._normalize_text(e) not in IGNORE]

    def _stems_for(e):
        n = config._normalize_text(e)
        out = []
        if n.endswith('ко') and len(n) > 5:
            out.append(n[:-1])
        if len(n) >= 5:
            out.append(n[:5])
        if len(n) >= 4:
            out.append(n[:4])
        return out

    matches = []
    for row in uniq_pool:
        nrow = config._normalize_text(row)
        for e in entities:
            if any(st in nrow for st in _stems_for(e)):
                matches.append(row)
                break

    if not matches:
        return ""

    def _extract_fields(row: str):
        clean = re.sub(r'^\[[^\]]*\]\s*', '', row)
        clean = re.sub(r'\s*---.*$', '', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        fields = {}
        if ':' in clean:
            for part in clean.split('|'):
                if ':' in part:
                    k, v = part.split(':', 1)
                    k = k.strip().lower()
                    v = v.strip()
                    if v:
                        fields[k] = v
        return fields

    CANON = {
        'фио': 'Ф.И.О.', 'ф.и.о.': 'Ф.И.О.', 'фамилия': 'Ф.И.О.', 'имя': 'Ф.И.О.',
        'комната': 'Комната', 'каб.': 'Комната', 'кабинет': 'Комната',
        'внут.': 'Внутренний', 'внутренний': 'Внутренний', 'телефон внутренний': 'Внутренний',
        'городской': 'Городской', 'телефон городской': 'Городской',
        'мобильный': 'Мобильный', 'телефон мобильный': 'Мобильный',
        'отдел': 'Отдел', 'должность': 'Должность', 'область': 'Область', '№': '№',
    }
    ORDER = ['№', 'Ф.И.О.', 'Должность', 'Комната', 'Отдел', 'Область',
             'Внутренний', 'Городской', 'Мобильный']

    records = []
    for m in matches:
        f = _extract_fields(m)
        canon = {}
        for k, v in f.items():
            ck = CANON.get(k)
            if ck:
                canon[ck] = v
        if canon:
            records.append(canon)

    if not records:
        return ""

    by_key = {}
    for r in records:
        key = r.get('Ф.И.О.') or tuple(sorted(r.items()))
        if key not in by_key:
            by_key[key] = r
        else:
            if len([v for v in r.values() if v]) > len([v for v in by_key[key].values() if v]):
                by_key[key] = r
    uniq_records = list(by_key.values())

    present = set()
    for r in uniq_records:
        present.update(r.keys())
    headers = [h for h in ORDER if h in present]
    extra = [h for h in present if h not in headers]
    headers.extend(sorted(extra))
    if not headers:
        return ""

    body_lines = []
    for r in uniq_records:
        vals = [r.get(h, '') for h in headers]
        body_lines.append("| " + " | ".join(vals) + " |")

    header_line = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join("---" for _ in headers) + "|"
    result = "\n".join([header_line, sep] + body_lines)

    if len(uniq_records) > 1:
        result += "\n\n_Найдено несколько совпадений (" + str(len(uniq_records)) + "). Уточните ФИО, отдел или комнату._"
    return result


def _build_md_table(headers: List[str], values: List[str]) -> str:
    header_line = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join("---" for _ in headers) + "|"
    val_line = "| " + " | ".join(values) + " |"
    return f"{header_line}\n{sep}\n{val_line}"


def _rag_answer(question: str, max_tokens: int = None) -> dict:
    search_question = _normalize_query_for_search(question)
    query_vector = list(state._dense_model.query_embed(f"query: {search_question}"))[0].tolist()

    query_filter = None
    file_match = re.search(r'[\w.-]+\.(?:md|txt|pdf|docx|xlsx|xls|py|sh|json|ya?ml)', question, re.IGNORECASE)
    if file_match:
        query_filter = state.models.Filter(
            must=[state.models.FieldCondition(
                key="source", match=state.models.MatchValue(value=file_match.group(0))
            )]
        )

    hits = state.qdrant_client.query_points(
        collection_name=config.COLLECTION_NAME,
        prefetch=[
            state.Prefetch(query=query_vector, using="dense", limit=25),
            state.Prefetch(query=state.Document(text=search_question, model="Qdrant/bm25"), using="sparse", limit=25)
        ],
        query=state.models.FusionQuery(fusion=state.models.Fusion.RRF),
        query_filter=query_filter,
        limit=config.TOP_K,
        with_payload=True,
    ).points

    hits = _filter_hits_by_entity(hits, question)

    context_parts, total = [], 0
    for hit in hits:
        src_name = hit.payload.get("source", "?")
        idx = hit.payload.get("chunk_index", "?")
        text = hit.payload.get("text", "")
        block = f"[{src_name} | chunk {idx}]\n{text}\n"
        if total + len(block) > config.MAX_CONTEXT_CHARS:
            break
        context_parts.append(block)
        total += len(block)

    context = "\n---\n".join(context_parts) if context_parts else "(контекст не найден)"
    sources = sorted({h.payload.get("source", "?") for h in hits})

    has_name = bool(re.search(r'[А-ЯЁA-Z][а-яёa-z]{3,}', question))
    job_titles = r'директор|секретарь|бухгалтер|начальник|зам|специалист|электроник|инженер|менеджер|руководитель|главный|юрист|экономист|кадровик|делопроизводитель'
    has_job = bool(re.search(job_titles, question, re.IGNORECASE))

    if re.search(r'какие\s+отделы|список\s+отделов|все\s+отделы', question, re.IGNORECASE):
        try:
            all_depts = set()
            offset_d = None
            while True:
                pts_d, offset_d = state.qdrant_client.scroll(
                    collection_name=config.COLLECTION_NAME, limit=200, offset=offset_d, with_payload=True
                )
                for pt_d in pts_d:
                    if pt_d.payload and pt_d.payload.get("text"):
                        for row in pt_d.payload["text"].split('\n---\n'):
                            m = re.search(r'Отдел:\s*([^|]+)', row)
                            if m:
                                d = m.group(1).strip()
                                if d:
                                    all_depts.add(d)
                if offset_d is None:
                    break
            all_depts = {d for d in all_depts if config._normalize_text(d) not in {'отдел', 'отдел в тел.', ''}}
            if all_depts:
                result = "В справочнике есть отделы:\n" + "\n".join(f"- {config._department_with_alias(d)}" for d in sorted(all_depts))
                state.log.info(f"[rag] Прямой ответ (список отделов): {len(all_depts)} отделов")
                return {"answer": result, "sources": sources, "hits": len(hits), "no_llm": True}
        except Exception as e:
            state.log.warning(f"[rag] list departments failed: {e}")

    if re.search(r'телефон|мобильн|внутренн|городск|тел[.\s]|позвонить|контакт|кто\s+работает|кто\s+сотрудник|список\s+сотрудник|сотрудник|люди|людей|человек|сколько|количество|кол-во|как\s+много|кто\s+в\s+отдел', question, re.IGNORECASE):
        dept_query = re.sub(
            r'\b(тел|телефон|мобильн\w*|внутренн\w*|городск\w*|позвонить|контакт\w*|отдел\w*|кто|работает|сотрудник\w*|список|люди|людей|человек|в|на|по|сколько|количество|кол-во|как|много)\b',
            ' ', question, flags=re.IGNORECASE
        ).strip()
        dept_query = re.sub(r'\s+', ' ', dept_query).strip(' .,!?-')
        if dept_query and len(dept_query) >= 2:
            try:
                all_src_texts = []
                offset = None
                while True:
                    pts, offset = state.qdrant_client.scroll(
                        collection_name=config.COLLECTION_NAME,
                        limit=200, offset=offset, with_payload=True,
                    )
                    for pt in pts:
                        if pt.payload and pt.payload.get("text"):
                            all_src_texts.append(pt.payload["text"])
                    if offset is None:
                        break
                dept_table = _format_department_answer(config._expand_department(dept_query), all_src_texts)
                if dept_table:
                    state.log.info(f"[rag] Прямой ответ по отделу «{dept_query}»:\n{dept_table[:200]}")
                    return {"answer": dept_table, "sources": sources, "hits": len(hits), "no_llm": True}
            except Exception as e:
                state.log.warning(f"[rag] dept answer failed: {e}")

    if re.search(r'отдел|комнат|кабинет|где\s+сидит|где\s+работает', question, re.IGNORECASE):
        ent_words = re.findall(r'[А-ЯЁA-Z][а-яёa-z]{3,}', question)
        IGNORE_ATTR = {'каком', 'какой', 'какая', 'какие', 'отдел', 'отделе',
                       'комната', 'комнате', 'кабинет', 'кабинете', 'где', 'сидит',
                       'работает', 'телефон'}
        ent_words = [w for w in ent_words if config._normalize_text(w) not in IGNORE_ATTR]
        if ent_words:
            try:
                all_src_texts = []
                offset = None
                while True:
                    pts, offset = state.qdrant_client.scroll(
                        collection_name=config.COLLECTION_NAME,
                        limit=200, offset=offset, with_payload=True,
                    )
                    for pt in pts:
                        if pt.payload and pt.payload.get("text"):
                            all_src_texts.append(pt.payload["text"])
                    if offset is None:
                        break
                found_rows = []
                for t in all_src_texts:
                    for row in t.split('\n---\n'):
                        if ':' not in row:
                            continue
                        norm_row = config._normalize_text(row)
                        for e in ent_words:
                            n = config._normalize_text(e)
                            stems = []
                            if n.endswith('ко') and len(n) > 5:
                                stems.append(n[:-1])
                            if len(n) >= 5:
                                stems.append(n[:5])
                            if len(n) >= 4:
                                stems.append(n[:4])
                            if any(st in norm_row for st in stems):
                                found_rows.append(row)
                                break
                seen = set()
                uniq = []
                for r in found_rows:
                    k = r.strip()
                    if k and k not in seen:
                        seen.add(k)
                        uniq.append(r)
                if uniq:
                    formatted = _format_phone_answer_from_hit(uniq[0], question, all_hits_texts=uniq)
                    if formatted:
                        state.log.info(f"[rag] Прямой ответ атрибута:\n{formatted}")
                        return {"answer": formatted, "sources": sources, "hits": len(hits), "no_llm": True}
            except Exception as e:
                state.log.warning(f"[rag] attr answer failed: {e}")

    if (has_name or has_job) and re.search(r'телефон|мобильн|внутренн|городск|тел[.\s]|позвонить|контакт', question, re.IGNORECASE):
        all_texts = [h.payload.get('text', '') for h in hits]
        sources_in_hits = sorted({h.payload.get('source', '') for h in hits if h.payload.get('source')})
        extra_rows = []
        for sn in sources_in_hits:
            extra_rows.extend(_collect_all_entity_rows(sn, question))
        try:
            all_sources = set()
            offset = None
            while True:
                pts, offset = state.qdrant_client.scroll(collection_name=config.COLLECTION_NAME, limit=200, offset=offset, with_payload=True)
                for pt in pts:
                    if pt.payload and pt.payload.get("source"):
                        all_sources.add(pt.payload["source"])
                if offset is None:
                    break
            for sn in sorted(all_sources):
                if sn not in sources_in_hits:
                    extra_rows.extend(_collect_all_entity_rows(sn, question))
        except Exception as e:
            state.log.warning(f"[rag] scroll all sources failed: {e}")
        combined_texts = list(dict.fromkeys(all_texts + extra_rows))
        for t in combined_texts:
            formatted = _format_phone_answer_from_hit(t, question, all_hits_texts=combined_texts)
            if formatted:
                state.log.info(f"[rag] Прямой ответ без LLM:\n{formatted}")
                return {"answer": formatted, "sources": sources, "hits": len(hits), "no_llm": True}

    dept_query_for_llm = re.sub(
        r'\b(тел|телефон|мобильн\w*|внутренн\w*|городск\w*|позвонить|контакт\w*|отдел\w*|кто|работает|сотрудник\w*|список|люди|в|на|по)\b',
        ' ', question, flags=re.IGNORECASE
    ).strip()
    if dept_query_for_llm and len(dept_query_for_llm) >= 2:
        all_texts_for_llm = []
        offset_llm = None
        while True:
            pts_llm, offset_llm = state.qdrant_client.scroll(
                collection_name=config.COLLECTION_NAME, limit=200, offset=offset_llm, with_payload=True
            )
            for pt_llm in pts_llm:
                if pt_llm.payload and pt_llm.payload.get("text"):
                    all_texts_for_llm.append(pt_llm.payload["text"])
            if offset_llm is None:
                break
        dept_table_for_llm = _format_department_answer(dept_query_for_llm, all_texts_for_llm)
        if dept_table_for_llm:
            extra_llm = "\n---\nТаблица сотрудников отдела:\n" + dept_table_for_llm + "\n"
            if len(context) + len(extra_llm) <= config.MAX_CONTEXT_CHARS + 1000:
                context += extra_llm
                state.log.info(f"[RAG] Добавлена таблица отдела {dept_query_for_llm} в контекст для LLM")

    _tag_re = r'\b(токен|токен[а-я]*|ключ|пароль|api[_ ]?key|hf_|secret)\b'
    if re.search(_tag_re, question, re.IGNORECASE) or re.search(r'\b\w+_\w+\b', question):
        prompt_to_use = config.FEW_SHOT_PROMPT
    else:
        prompt_to_use = config.SYSTEM_PROMPT
    user_prompt = prompt_to_use.format(context=context, question=question)

    resp = state.requests.post(
        config.LLAMA_SERVER_URL,
        json={
            "model": config.OLLAMA_MODEL,
            "messages": [{"role": "user", "content": user_prompt}],
            "max_tokens": max_tokens or config.MAX_ANSWER_TOKENS,
            "temperature": 0.3,
            "top_p": 0.9,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=config.LLM_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    answer = data["choices"][0]["message"].get("content", "").strip() or "(пустой ответ)"
    return {"answer": answer, "sources": sources, "hits": len(hits)}


__all__ = [
    "_normalize_query_for_search",
    "_filter_hits_by_entity",
    "_collect_all_entity_rows",
    "_format_department_answer",
    "_format_phone_answer_from_hit",
    "_build_md_table",
    "_rag_answer",
]
