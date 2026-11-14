"""Application factory and router wiring."""
from fastapi import FastAPI

from api.native import router as native_router
from api.openai import router as openai_router
from api.ui import router as ui_router
from lifecycle import lifespan

app = FastAPI(lifespan=lifespan)
app.include_router(native_router)
app.include_router(openai_router)
app.include_router(ui_router)

__all__ = ["app"]
