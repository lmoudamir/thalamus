import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("thalamus-py")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.anthropic_messages import router as anthropic_router
from routes.token_routes import router as token_router

app = FastAPI(title="thalamus-py", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(anthropic_router)
app.include_router(token_router)

@app.get("/")
async def root():
    return {"service": "thalamus-py", "status": "running"}

@app.get("/health")
async def health():
    from core.token_manager import has_cursor_access_token
    return {
        "status": "ok",
        "has_token": has_cursor_access_token(),
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "3013"))
    logger.info(f"Starting thalamus-py on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
