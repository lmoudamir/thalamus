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
from routes.openai_chat import router as openai_router
from routes.model_routes import router as model_router
from routes.token_routes import router as token_router
from routes.login_routes import router as login_router

app = FastAPI(title="thalamus-py", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(anthropic_router)
app.include_router(openai_router)
app.include_router(model_router)
app.include_router(token_router)
app.include_router(login_router)

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

@app.get("/api/hello")
async def api_hello():
    """CC SDK calls BASE_API_URL/api/hello as a connectivity check during startup."""
    return {"status": "ok"}

@app.get("/v1/oauth/hello")
async def oauth_hello():
    """CC SDK calls TOKEN_URL/v1/oauth/hello during auth health check."""
    return {"status": "ok"}

@app.post("/v1/messages/count_tokens")
async def count_tokens():
    """CC SDK may call this for token counting; return a dummy response."""
    return {"input_tokens": 0}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "3013"))
    logger.info(f"Starting thalamus-py on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
