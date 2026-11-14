"""Chunking, file indexing, and Qdrant write entry points."""
from . import _legacy

chunk_text = _legacy.chunk_text
get_file_hash = _legacy.get_file_hash
delete_file_from_index = _legacy.delete_file_from_index
index_file = _legacy.index_file

__all__ = ["chunk_text", "get_file_hash", "delete_file_from_index", "index_file"]
