from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.token_manager import (
    get_token_status,
    set_cursor_access_token,
    get_cursor_access_token,
)
from utils.structured_logging import ThalamusStructuredLogger

logger = ThalamusStructuredLogger.get_logger("token-routes", "DEBUG")
router = APIRouter()

@router.get("/token/status")
async def token_status():
    return JSONResponse(content=get_token_status())

@router.post("/token/update")
async def token_update(request: Request):
    body = await request.json()
    token = body.get("token", "")
    if not token:
        return JSONResponse(status_code=400, content={"error": "Token required"})
    set_cursor_access_token(token, source="api")
    return JSONResponse(content={"ok": True, "length": len(token)})

@router.post("/token/clear")
async def token_clear():
    set_cursor_access_token("", source="cleared")
    return JSONResponse(content={"ok": True})
