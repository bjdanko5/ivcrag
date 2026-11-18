"""Compatibility entry point used by systemd and existing shell scripts."""
import sys
from pathlib import Path

# Ensure `python app/embedding_server.py` and package imports resolve from repo root.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.bootstrap import app
from app.config import HOST, PORT

if __name__ == "__main__":
    import uvicorn
    # Reduced graceful shutdown timeout from 5 to 2 seconds for faster service restarts
    uvicorn.run(app, host=HOST, port=PORT, timeout_graceful_shutdown=2)
