"""Ingestion package exposing the original implementation through focused modules."""
import importlib.util
import sys
from pathlib import Path

from app.state import config, state

_legacy_path = Path(__file__).resolve().parents[1] / "ingestion.py"
_spec = importlib.util.spec_from_file_location("_ivcrag_ingestion_legacy", _legacy_path)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Cannot load ingestion implementation from {_legacy_path}")
_legacy = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _legacy
_spec.loader.exec_module(_legacy)

for _symbol in _legacy.__all__:
    globals()[_symbol] = getattr(_legacy, _symbol)

__all__ = list(_legacy.__all__)
