import logging
import time
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse

from claude_code.pipeline import run_claude_messages_pipeline
from core.token_manager import capture_token_from_request

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/v1/messages")
async def create_message(request: Request):
    """Handle Anthropic Messages API requests."""
    start_time = time.time()

    auth_token = request.headers.get("x-api-key", "") or request.headers.get("authorization", "")

    capture_token_from_request(request.headers.get("authorization", ""))

    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"type": "error", "error": {"type": "invalid_request_error", "message": str(e)}}
        )

    request_id = f"req_{time.time_ns() // 1000000}"

    logger.info(f"[{request_id}] POST /v1/messages model={payload.get('model', '?')} stream={payload.get('stream', False)} tools={len(payload.get('tools', []))}")

    result = await run_claude_messages_pipeline(
        payload=payload,
        request_id=request_id,
        auth_token=auth_token,
    )

    if not result.get("ok"):
        status = result.get("status", 500)
        body = result.get("body", {"type": "error", "error": {"type": "api_error", "message": "Internal error"}})
        return JSONResponse(status_code=status, content=body)

    if result.get("stream"):
        stream_handler = result.get("stream_handler")
        if stream_handler:
            return StreamingResponse(
                stream_handler(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Thalamus-Request-Id": request_id,
                },
            )
        return JSONResponse(status_code=500, content={"type": "error", "error": {"type": "api_error", "message": "No stream handler"}})

    return JSONResponse(content=result.get("body", {}))


@router.post("/v1/messages/count_tokens")
async def count_tokens(request: Request):
    """Estimate token count for a messages request."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"input_tokens": 0})

    total_chars = 0
    if payload.get("system"):
        if isinstance(payload["system"], str):
            total_chars += len(payload["system"])
        elif isinstance(payload["system"], list):
            for block in payload["system"]:
                total_chars += len(block.get("text", ""))

    for msg in payload.get("messages", []):
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                total_chars += len(block.get("text", ""))

    estimated_tokens = max(1, total_chars // 4)
    return JSONResponse(content={"input_tokens": estimated_tokens})
