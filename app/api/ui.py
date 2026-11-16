"""FastAPI routes for the browser UI."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.ui import HTML_INDEX

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def ui_index():
    return HTML_INDEX


__all__ = ["router"]
