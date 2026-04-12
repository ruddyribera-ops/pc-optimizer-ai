from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PORT = int(os.getenv("PORT", 8000))

app = FastAPI(title="PC Optimizer Cloud API - Minimal Test")


@app.get("/")
async def root():
    return {"message": "Hello World", "port": PORT}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/test")
async def test():
    return {"status": "test ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
