"""OpenAI-compatible endpoints."""
import json
import time
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from app.state import state
from app import tracing
from app.rag.answers import _rag_answer
from app.schemas import _ChatCompletionRequest

router = APIRouter()


def _last_user_question(messages):
    for message in reversed(messages):
        if message.role == "user" and message.text.strip():
            return message.text.strip()
    return ""


@router.post("/v1/chat/completions")
async def openai_chat_completions(req: _ChatCompletionRequest):
    question = _last_user_question(req.messages)
    if not question:
        raise HTTPException(status_code=400, detail="No user message found")
    tracing.begin(
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

 #       tracing.stage("shortcut", {
 #           "no_llm": bool(result.get("no_llm")),
 #           "hits": result.get("hits"),
 #           "sources": result.get("sources"),
 #           "answer_chars": len(result.get("answer") or ""),
 #       })

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
                yield f"data: {json.dumps(first, ensure_ascii=False)}\n\n"
                for i in range(0, len(answer), 40):
                    chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": req.model,
                        "choices": [{"index": 0, "delta": {"content": answer[i:i + 40]}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                last = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": req.model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(last, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

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

@router.get("/v1/models")
async def openai_models():
    return {
        "object": "list",
        "data": [{
            "id": "rag",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "local-rag",
        }],
    }


__all__ = ["router", "_last_user_question"]
