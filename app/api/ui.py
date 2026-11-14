"""Browser UI endpoint."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def ui_index():
    try:
        from app.main import HTML_INDEX
        return HTML_INDEX
    except ImportError:  # pragma: no cover
        return """<html><body><h1>ivcrag</h1></body></html>"""


__all__ = ["router"]
