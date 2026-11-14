"""FastAPI routes for the browser UI."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def ui_index():
    from app.main import HTML_INDEX
    return HTML_INDEX


__all__ = ["router"]
