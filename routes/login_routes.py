from __future__ import annotations
"""
Routes for browser-based Cursor PKCE login session management.

Two-step flow:
  GET /cursor/login  — generate PKCE URL (instant response)
  GET /cursor/poll   — client polls until browser login completes

Port of: cursor_browser_login_session_management_routes.js
"""

import time
import uuid

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from core.cursor_pkce_login import (
    assemble_cursor_token,
    build_cursor_login_url,
    generate_pkce_verifier_and_challenge,
    poll_cursor_auth_for_token,
)
from core.token_manager import set_cursor_access_token
from utils.structured_logging import ThalamusStructuredLogger

logger = ThalamusStructuredLogger.get_logger("login-routes", "DEBUG")
router = APIRouter(prefix="/cursor")

# Ephemeral in-memory store; sessions expire after 10 minutes.
_pending_sessions: dict[str, dict] = {}
SESSION_TTL_S = 10 * 60


def _cleanup_expired() -> None:
    now = time.time()
    expired = [k for k, v in _pending_sessions.items() if now - v["created"] > SESSION_TTL_S]
    for k in expired:
        _pending_sessions.pop(k, None)


@router.get("/login")
async def cursor_login():
    _cleanup_expired()

    verifier, challenge = generate_pkce_verifier_and_challenge()
    login_uuid = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    login_url = build_cursor_login_url(login_uuid, challenge)

    _pending_sessions[session_id] = {
        "uuid": login_uuid,
        "verifier": verifier,
        "created": time.time(),
    }

    logger.info(f"Generated login URL, session={session_id}")
    return JSONResponse(content={"url": login_url, "session_id": session_id})


@router.get("/poll")
async def cursor_poll(session_id: str = Query(...)):
    session = _pending_sessions.get(session_id)
    if not session:
        return JSONResponse(content={"status": "error", "message": "Invalid or expired session_id"})

    data = await poll_cursor_auth_for_token(session["uuid"], session["verifier"])
    if not data:
        return JSONResponse(content={"status": "waiting"})

    token = assemble_cursor_token(data)
    _pending_sessions.pop(session_id, None)

    set_cursor_access_token(token, source="browser-login")
    logger.info(f"Login success, session={session_id}")
    return JSONResponse(content={"status": "ok", "token": token})
