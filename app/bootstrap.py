"""Application factory and router wiring."""
from fastapi import FastAPI

try:
    from app.api.native import router as native_router
    from app.api.openai import router as openai_router
    from app.api.ui import router as ui_router
    from app.lifecycle import lifespan
except ImportError:  # pragma: no cover
    from api.native import router as native_router
    from api.openai import router as openai_router
    from api.ui import router as ui_router
    from lifecycle import lifespan


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.include_router(native_router)
    app.include_router(openai_router)
    app.include_router(ui_router)
    return app


app = create_app()

__all__ = ["app", "create_app"]
