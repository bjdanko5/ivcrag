"""Compatibility wrapper for the legacy single-file app layout."""
from app.bootstrap import app

HTML_INDEX = """<html><body><h1>ivcrag</h1></body></html>"""

__all__ = ["app", "HTML_INDEX"]
