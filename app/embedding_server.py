from main import app

if __name__ == "__main__":
    import uvicorn
    import config
    uvicorn.run(app, host=config.HOST, port=config.PORT, timeout_graceful_shutdown=5)
