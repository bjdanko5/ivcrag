"""Admin endpoints: runtime tracing toggle."""
from fastapi import APIRouter, Request

from app import tracing

router = APIRouter()


@router.get("/admin/trace")
async def trace_status():
    """Текущее состояние трассировки."""
    return tracing.status()


@router.post("/admin/trace")
async def trace_set(request: Request):
    """Query: ?on=1 | ?on=0 | ?toggle=1. Без параметров — no-op со статусом."""
    qp = request.query_params
    if "on" in qp:
        tracing.set_enabled(qp["on"].lower() in ("1", "true", "yes", "on"))
        return {"ok": True, **tracing.status()}
    if "toggle" in qp:
        tracing.set_enabled(not tracing.enabled())
        return {"ok": True, **tracing.status()}
    return {"ok": True, "noop": True, **tracing.status()}