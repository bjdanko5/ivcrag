"""Launch entrypoint retained for systemd and existing scripts."""
try:
    from app.bootstrap import app
except ImportError:  # pragma: no cover
    from bootstrap import app

if __name__ == "__main__":
    import uvicorn
    try:
        import app.config as config
    except ImportError:  # pragma: no cover
        import config
    uvicorn.run(app, host=config.HOST, port=config.PORT, timeout_graceful_shutdown=5)
