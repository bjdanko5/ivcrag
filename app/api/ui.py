"""Browser UI endpoint."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def ui_index():
    # HTML is kept in the legacy UI module during the file-only move.
    from main import HTML_INDEX
    return HTML_INDEX


__all__ = ["router"]
