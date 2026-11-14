"""Application compatibility entry point.

The application factory and router wiring live in :mod:`app.bootstrap`.
"""
from app.bootstrap import app

__all__ = ["app"]
