"""Application factory and router wiring."""
from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.native import router as native_router
from app.api.openai import router as openai_router
from app.api.ui import router as ui_router
from app.lifecycle import lifespan


def create_app() -> FastAPI:
    application = FastAPI(lifespan=lifespan)
    application.include_router(admin_router)
    application.include_router(native_router)
    application.include_router(openai_router)
    application.include_router(ui_router)
    return application


app = create_app()

__all__ = ["app", "create_app"]
