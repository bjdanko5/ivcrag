"""RAG subsystem package."""
try:
    from app import rag as _legacy
except ImportError:  # pragma: no cover
    import rag as _legacy

for _name in getattr(_legacy, "__all__", ()):
    globals()[_name] = getattr(_legacy, _name)

__all__ = list(getattr(_legacy, "__all__", ()))
