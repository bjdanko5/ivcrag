"""Backward-compatible application entry point.

Legacy scripts import ``app.main`` for the FastAPI app and HTML payload.
The runtime wiring now lives in ``app.bootstrap`` and the browser HTML in
``app.ui``.
"""
from app.bootstrap import app
from app.ui import HTML_INDEX

__all__ = ["app", "HTML_INDEX"]
