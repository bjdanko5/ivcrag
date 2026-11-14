"""Document scan and persistent hash entry points."""
from . import _legacy

_load_hashes = _legacy._load_hashes
_save_hashes = _legacy._save_hashes
scan_docs_dir = _legacy.scan_docs_dir
periodic_scan = _legacy.periodic_scan

__all__ = ["_load_hashes", "_save_hashes", "scan_docs_dir", "periodic_scan"]
