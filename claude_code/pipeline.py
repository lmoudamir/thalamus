"""
Main pipeline module — the heart of thalamus-py.

Ports claude_messages_pipeline_service.js and claude_code_direct_cursor_api_caller.js
into a single Python module.

Pipeline flow:
  1. Receive Anthropic Messages API request
  2. Normalize to OpenAI format
  3. Inject tool prompts
  4. Call Cursor API via H2
  5. Parse tool calls from text response
  6. Assemble Anthropic SSE output
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from typing import Any, AsyncIterator, Callable

from core.token_manager import get_cursor_access_token
from core.bearer_token import strip_cursor_user_prefix
from core.protobuf_builder import (
    build_gzip_framed_protobuf_chat_request_body,
    compute_sha256_hex_digest,
    generate_obfuscated_machine_id_checksum,
)
from core.protobuf_frame_parser import ProtobufFrameParser
from core.cursor_h2_client import open_streaming_h2_request
from claude_code.tool_prompt_builder import (
    build_tool_call_prompt,
    inject_tool_prompt_into_messages,
)
from claude_code.tool_parser import try_parse_tool_calls_from_text
from claude_code.sse_assembler import (
    StreamingAnthropicSession,
    build_unary_anthropic_response,
)
from config.tool_registry import post_process_tool_calls
from config.fallback_config import load_fallback_config

logger = logging.getLogger("thalamus.pipeline")

FATAL_ERROR_PATTERNS: list[re.Pattern] = [
    re.compile(r"unable\s+to\s+reach\s+the\s+model\s+provider", re.I),
    re.compile(r"trouble\s+connecting", re.I),
    re.compile(r'code["\']?\s*:\s*["\']?unavailable', re.I),
    re.compile(r"ERROR_OPENAI", re.I),
    re.compile(r"service.*unavailable", re.I),
]

TOOL_JSON_START_MARKERS: list[str] = [
    '{"tool_calls"',
    '"tool_calls":',
    "```json",
    '{"function"',
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def normalize_content(content: Any) -> str:
    """Flatten Anthropic content (string / list / dict) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            item.get("text") or item.get("content") or ""
            for item in content
            if isinstance(item, dict)
        ).strip()
    if isinstance(content, dict):
        return content.get("text") or content.get("content") or ""
    return ""


def _remove_uri_format(schema: Any) -> Any:
    """Recursively strip format:'uri' from JSON-Schema nodes (Cursor rejects it)."""
    if not schema or not isinstance(schema, dict):
        return schema
    if isinstance(schema, list):
        return [_remove_uri_format(item) for item in schema]

    if schema.get("type") == "string" and schema.get("format") == "uri":
        return {k: v for k, v in schema.items() if k != "format"}

    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            result[key] = {pk: _remove_uri_format(pv) for pk, pv in value.items()}
        elif key in ("items", "additionalProperties") and isinstance(value, dict):
            result[key] = _remove_uri_format(value)
        elif key in ("anyOf", "allOf", "oneOf") and isinstance(value, list):
            result[key] = [_remove_uri_format(item) for item in value]
        else:
            result[key] = _remove_uri_format(value)
    return result


def resolve_model_name(model_name: str) -> str:
    """Map legacy Claude model names to current equivalents."""
    resolved = model_name or "claude-4.5-sonnet"
    lower = resolved.lower()

    if "claude-3-5-sonnet" in lower or "claude-3.5-sonnet" in lower:
        return "claude-4.5-sonnet"
    if "claude-3-7-sonnet" in lower or "claude-3.7-sonnet" in lower:
        return "claude-4.5-sonnet"
    if "claude-3-opus" in lower or "claude-3.5-opus" in lower:
        return "claude-4.5-opus-high"
    if "claude-3-haiku" in lower or "claude-3.5-haiku" in lower:
        return "claude-4.5-haiku"
    return resolved


def normalize_anthropic_payload(payload: dict) -> dict:
    """Convert an Anthropic Messages API payload to internal (OpenAI-ish) format."""
    messages: list[dict] = []

    sys_content = payload.get("system")
    if isinstance(sys_content, list):
        for item in sys_content:
            text = normalize_content(
                item.get("text") or item.get("content") or item
                if isinstance(item, dict) else item
            )
            if text:
                messages.append({"role": "system", "content": text})
    elif isinstance(sys_content, str) and sys_content:
        messages.append({"role": "system", "content": sys_content})

    for msg in payload.get("messages") or []:
        parts = msg.get("content") if isinstance(msg.get("content"), list) else []

        tool_calls = [
            {
                "type": "function",
                "id": tc.get("id", ""),
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": json.dumps(tc.get("input") or {}),
                },
            }
            for tc in parts
            if isinstance(tc, dict) and tc.get("type") == "tool_use"
        ]

        normalized = normalize_content(msg.get("content"))
        new_msg: dict[str, Any] = {"role": msg.get("role", "user")}
        if normalized:
            new_msg["content"] = normalized
        if tool_calls:
            new_msg["tool_calls"] = tool_calls
        if new_msg.get("content") or new_msg.get("tool_calls"):
            messages.append(new_msg)

        for tr in parts:
            if isinstance(tr, dict) and tr.get("type") == "tool_result":
                messages.append({
                    "role": "tool",
                    "content": tr.get("text") or tr.get("content") or json.dumps(tr),
                    "tool_call_id": tr.get("tool_use_id", ""),
                })

    tools = [
        {
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": _remove_uri_format(t.get("input_schema")),
            },
        }
        for t in (payload.get("tools") or [])
        if t.get("name") != "BatchTool"
    ]

    return {
        "messages": messages,
        "tools": tools,
        "stream": payload.get("stream") is True,
        "resolved_model": resolve_model_name(payload.get("model", "")),
        "request_controls": {
            "max_tokens": payload.get("max_tokens"),
            "temperature": payload.get("temperature"),
            "top_p": payload.get("top_p"),
            "stop": payload.get("stop_sequences") or payload.get("stop"),
        },
    }


def _to_api_error_body(message: str, error_type: str = "api_error") -> dict:
    return {"type": "error", "error": {"type": error_type, "message": message}}


def _extract_raw_auth_token(value: Any) -> str:
    if not value:
        return ""
    raw = value[0] if isinstance(value, list) else value
    return re.sub(r"^Bearer\s+", "", str(raw), flags=re.I).strip()


# ---------------------------------------------------------------------------
# max_tokens limiter
# ---------------------------------------------------------------------------


def _parse_max_tokens(value: Any) -> dict:
    if value is None:
        return {"ok": True, "value": None}
    try:
        n = int(value)
    except (TypeError, ValueError):
        return {"ok": False, "error": f"Invalid max_tokens: {value}"}
    if n < 1:
        return {"ok": False, "error": f"Invalid max_tokens: {value}"}
    return {"ok": True, "value": n}


class _OutputLimiter:
    """Approximate char-budget limiter (1 token ~ 4 chars)."""

    def __init__(self, max_tokens: int | None) -> None:
        if max_tokens and max_tokens > 0:
            self.has_limit = True
            self.char_budget = max_tokens * 4
        else:
            self.has_limit = False
            self.char_budget = None
        self._emitted = 0
        self._exhausted = False

    def emit_within_limit(self, text: str) -> str:
        if not text or self._exhausted:
            return ""
        if not self.has_limit:
            return text
        remaining = self.char_budget - self._emitted
        if remaining <= 0:
            self._exhausted = True
            return ""
        out = text[:remaining]
        self._emitted += len(out)
        if len(out) < len(text) or self._emitted >= self.char_budget:
            self._exhausted = True
        return out

    @property
    def is_exhausted(self) -> bool:
        return self._exhausted

    @property
    def emitted_chars(self) -> int:
        return self._emitted


# ---------------------------------------------------------------------------
# Tool-JSON-aware text forwarder
# ---------------------------------------------------------------------------


def _find_first_tool_json_start_index(full_text: str) -> int:
    if not full_text:
        return -1
    first = -1
    for marker in TOOL_JSON_START_MARKERS:
        idx = full_text.find(marker)
        if idx >= 0 and (first < 0 or idx < first):
            first = idx
    return first


class ToolJsonAwareTextForwarder:
    """Buffer streaming text deltas and stop forwarding once tool JSON begins."""

    def __init__(
        self,
        emit_text_delta: Callable[[str], str | None],
        limiter: _OutputLimiter,
    ) -> None:
        self._emit = emit_text_delta
        self._limiter = limiter
        self.full_text_seen = ""
        self._pending_buffer = ""
        self._safe_text_consumed_len = 0
        self.stopped_due_to_tool_json = False
        self._tail_buffer_len = 30

    def _process_safe_chunk(self, chunk: str) -> str | None:
        if not chunk:
            return None
        self._safe_text_consumed_len += len(chunk)
        limited = self._limiter.emit_within_limit(chunk)
        if limited:
            return self._emit(limited)
        return None

    def on_delta(self, delta_text: str) -> str | None:
        """Feed a new text delta. Returns SSE string if text was forwarded."""
        delta = delta_text or ""
        if not delta:
            return None
        self.full_text_seen += delta
        if self.stopped_due_to_tool_json:
            return None

        self._pending_buffer += delta
        split_idx = _find_first_tool_json_start_index(self.full_text_seen)
        if split_idx >= 0:
            self.stopped_due_to_tool_json = True
            remaining_safe = max(0, split_idx - self._safe_text_consumed_len)
            if remaining_safe > 0:
                return self._process_safe_chunk(
                    self._pending_buffer[:remaining_safe]
                )
            self._pending_buffer = ""
            return None

        safe_flush_len = max(0, len(self._pending_buffer) - self._tail_buffer_len)
        if safe_flush_len > 0:
            result = self._process_safe_chunk(self._pending_buffer[:safe_flush_len])
            self._pending_buffer = self._pending_buffer[safe_flush_len:]
            return result
        return None

    def flush_using_final_safe_text(self, final_safe_text: str) -> str | None:
        """Flush remaining buffered text after the stream has ended."""
        final = final_safe_text or ""

        result_parts: list[str] = []
        if not self.stopped_due_to_tool_json and self._pending_buffer:
            r = self._process_safe_chunk(self._pending_buffer)
            if r:
                result_parts.append(r)
            self._pending_buffer = ""

        if len(final) > self._safe_text_consumed_len:
            r = self._process_safe_chunk(final[self._safe_text_consumed_len:])
            if r:
                result_parts.append(r)

        return "".join(result_parts) if result_parts else None


# ---------------------------------------------------------------------------
# Tool-call requirement detection
# ---------------------------------------------------------------------------


def is_tool_call_explicitly_required(messages: list[dict]) -> bool:
    """Check if the last user message explicitly demands a tool call."""
    if not messages:
        return False

    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            last_user_idx = i
            break
    if last_user_idx < 0:
        return False

    content = messages[last_user_idx].get("content", "")
    if isinstance(content, list):
        content = " ".join(
            (p.get("text", "") if isinstance(p, dict) else str(p)) for p in content
        )
    user_text = str(content).lower()
    if not user_text:
        return False

    general = [
        re.compile(r"must\s+call\s+at\s+least\s+one\s+tool"),
        re.compile(r"you\s+must\s+output\s+a\s+valid\s+tool_calls\s+json"),
        re.compile(r"必须.*至少.*调用.*工具"),
    ]
    if any(p.search(user_text) for p in general):
        return True

    first_msg = [
        re.compile(r"first\s+(assistant\s+)?message\s+must\s+be\s+tool-?call\s+json"),
        re.compile(r"第一条.*assistant.*消息.*必须.*tool-?call"),
        re.compile(r"第一条.*消息.*必须.*tool-?call"),
    ]
    if not any(p.search(user_text) for p in first_msg):
        return False

    has_assistant_before = any(
        m.get("role") == "assistant" for m in messages[:last_user_idx]
    )
    return not has_assistant_before


# ---------------------------------------------------------------------------
# Text-before-JSON extraction
# ---------------------------------------------------------------------------


def extract_text_before_json(full_text: str) -> str:
    """Extract text appearing before tool-call JSON in LLM output."""
    if not full_text:
        return ""
    patterns = [
        re.compile(r'\{[\s\S]*?"tool_calls"\s*:\s*\['),
        re.compile(r'```(?:json)?\s*\{[\s\S]*?"tool_calls"'),
        re.compile(r"<tool_call>\s*\{"),
        re.compile(r"<<function=[^>]+>>\s*\{"),
        re.compile(r'\{[\s\S]*?"function_call"\s*:\s*\{'),
    ]
    for pattern in patterns:
        m = pattern.search(full_text)
        if m and m.start() > 0:
            before = full_text[: m.start()].strip()
            if before:
                return before
    return ""


# ---------------------------------------------------------------------------
# Fatal error detection
# ---------------------------------------------------------------------------


def _is_fatal_stream_error(error: Any) -> bool:
    text = (
        error if isinstance(error, str)
        else str(
            getattr(error, "detail", None)
            or getattr(error, "raw", None)
            or getattr(error, "message", None)
            or json.dumps(error if isinstance(error, dict) else {})
        )
    )
    return any(p.search(text) for p in FATAL_ERROR_PATTERNS)


# ---------------------------------------------------------------------------
# Cursor stream plumbing
# ---------------------------------------------------------------------------


def build_cursor_stream_params(
    token: str, messages: list[dict], model: str
) -> tuple[str, dict[str, str], bytes]:
    """Build H2 path, headers, and protobuf body for a Cursor streaming request."""
    chosen_auth = strip_cursor_user_prefix(token)
    checksum = generate_obfuscated_machine_id_checksum(chosen_auth.strip())
    session_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chosen_auth))
    client_key = compute_sha256_hex_digest(chosen_auth)
    client_version = os.environ.get("CURSOR_CLIENT_VERSION", "2.5.25")

    body = build_gzip_framed_protobuf_chat_request_body(
        messages, model, agent_mode=True
    )
    is_gzipped = body[0] == 0x01

    headers = {
        "authorization": f"Bearer {chosen_auth}",
        "connect-accept-encoding": "gzip",
        "connect-protocol-version": "1",
        "content-type": "application/connect+proto",
        "user-agent": "connect-es/1.6.1",
        "x-amzn-trace-id": f"Root={uuid.uuid4()}",
        "x-client-key": client_key,
        "x-cursor-checksum": checksum,
        "x-cursor-client-version": client_version,
        "x-cursor-config-version": str(uuid.uuid4()),
        "x-cursor-timezone": "Asia/Shanghai",
        "x-ghost-mode": "true",
        "x-request-id": str(uuid.uuid4()),
        "x-session-id": session_id,
        "Host": "api2.cursor.sh",
    }
    if is_gzipped:
        headers["connect-content-encoding"] = "gzip"

    path = "/aiserver.v1.ChatService/StreamUnifiedChatWithTools"
    return path, headers, body


async def consume_stream(
    stream_iterator: AsyncIterator[bytes],
    on_text_delta: Callable[[str], Any] | None = None,
    on_thinking_delta: Callable[[str], Any] | None = None,
) -> dict:
    """Consume a Cursor protobuf stream, accumulating text/thinking/errors."""
    parser = ProtobufFrameParser()
    text = ""
    thinking = ""
    errors: list[Any] = []
    had_content = False
    has_fatal_error = False
    chunk_count = 0
    text_delta_count = 0
    thinking_delta_count = 0
    stream_start = time.monotonic()
    first_chunk_latency_ms: float | None = None

    async for chunk in stream_iterator:
        chunk_count += 1
        if first_chunk_latency_ms is None:
            first_chunk_latency_ms = (time.monotonic() - stream_start) * 1000

        result = parser.parse(chunk)

        if result.errors:
            errors.extend(result.errors)
            for err in result.errors:
                if _is_fatal_stream_error(err):
                    has_fatal_error = True

        if result.thinking:
            thinking += result.thinking
            thinking_delta_count += 1
            had_content = True
            if on_thinking_delta:
                on_thinking_delta(result.thinking)

        if result.text:
            text += result.text
            text_delta_count += 1
            had_content = True
            if on_text_delta:
                on_text_delta(result.text)

    return {
        "text": text,
        "thinking": thinking,
        "errors": errors,
        "had_content": had_content,
        "has_fatal_error": has_fatal_error,
        "metrics": {
            "stream_duration_ms": (time.monotonic() - stream_start) * 1000,
            "first_chunk_latency_ms": first_chunk_latency_ms if first_chunk_latency_ms is not None else -1,
            "chunk_count": chunk_count,
            "text_delta_count": text_delta_count,
            "thinking_delta_count": thinking_delta_count,
            "protocol_error_count": len(errors),
        },
    }


# ---------------------------------------------------------------------------
# Internal Cursor caller with fallback
# ---------------------------------------------------------------------------


async def _call_cursor_direct(
    messages: list[dict],
    model: str,
    tools: list[dict],
    valid_tool_names: list[str],
    auth_token: str,
    on_stream_delta: Callable[[str], Any] | None = None,
    on_thinking_delta: Callable[[str], Any] | None = None,
) -> dict:
    """Call Cursor API with tool prompt injection, parsing, post-processing, and fallback."""
    start_time = time.monotonic()
    request_id = f"cc_{uuid.uuid4().hex[:12]}"

    injected_base = inject_tool_prompt_into_messages(messages, tools)
    has_valid_tools = bool(valid_tool_names)
    requires_tool_call = has_valid_tools and is_tool_call_explicitly_required(messages)

    fallback_cfg = load_fallback_config()
    tried_models: list[str] = []
    current_model = model

    while len(tried_models) < fallback_cfg.max_attempts:
        logger.info(
            "[%s] Calling Cursor direct | model=%s | tools=%d | msgs=%d | attempt=%d",
            request_id, current_model, len(valid_tool_names),
            len(injected_base), len(tried_models) + 1,
        )

        attempt_start = time.monotonic()

        try:
            path, headers, body = build_cursor_stream_params(
                auth_token, injected_base, current_model
            )
            async with open_streaming_h2_request(path, headers, body) as stream_iter:
                consumed = await consume_stream(
                    stream_iter,
                    on_text_delta=on_stream_delta,
                    on_thinking_delta=on_thinking_delta,
                )
        except Exception as exc:
            err_msg = str(exc)
            logger.error("[%s] Connection/stream error: %s", request_id, err_msg)
            if fallback_cfg.should_fallback(err_msg):
                tried_models.append(current_model)
                next_model = fallback_cfg.select_next_model(
                    model, tried_models
                )
                if next_model:
                    logger.info(
                        "[%s] Fallback: %s -> %s", request_id, current_model, next_model
                    )
                    current_model = next_model
                    continue
            return {
                "error": err_msg,
                "status": 503,
                "fallback_attempts": len(tried_models),
                "model": current_model,
            }

        should_fallback_from_stream = (
            (consumed["errors"] and not consumed["had_content"])
            or consumed["has_fatal_error"]
        )

        if should_fallback_from_stream:
            err_detail = _first_error_detail(consumed["errors"])
            logger.warning(
                "[%s] Stream error: %s | had_content=%s fatal=%s",
                request_id, err_detail,
                consumed["had_content"], consumed["has_fatal_error"],
            )
            if fallback_cfg.should_fallback(err_detail):
                tried_models.append(current_model)
                next_model = fallback_cfg.select_next_model(model, tried_models)
                if next_model:
                    logger.info(
                        "[%s] Fallback: %s -> %s (stream error)",
                        request_id, current_model, next_model,
                    )
                    current_model = next_model
                    continue
            return {
                "error": err_detail,
                "status": 503,
                "fallback_attempts": len(tried_models),
                "model": current_model,
            }

        metrics = consumed["metrics"]
        logger.info(
            "[%s] Stream consumed | text_len=%d thinking_len=%d errors=%d chunks=%d first_token_ms=%.0f",
            request_id, len(consumed["text"]), len(consumed["thinking"]),
            len(consumed["errors"]), metrics["chunk_count"],
            metrics["first_chunk_latency_ms"],
        )

        if not has_valid_tools:
            return {
                "text": consumed["text"],
                "thinking": consumed["thinking"],
                "model": current_model,
                "fallback_attempts": len(tried_models),
                "stats": {"passed": 0, "normalized": 0, "filtered": 0, "invalid_arguments_filtered": 0},
            }

        raw_tool_calls = try_parse_tool_calls_from_text(consumed["text"])

        if raw_tool_calls:
            raw_names = [
                (tc.get("function") or {}).get("name", "?") for tc in raw_tool_calls
            ]
            logger.info(
                "[%s] Parsed tool calls: %s", request_id,
                json.dumps([{"name": n} for n in raw_names]),
            )

            result = post_process_tool_calls(raw_tool_calls, valid_tool_names)
            processed = result["processed"]
            stats = result["stats"]

            if processed:
                text_before = extract_text_before_json(consumed["text"])
                return {
                    "tool_calls": processed,
                    "text": text_before,
                    "thinking": consumed["thinking"],
                    "model": current_model,
                    "stats": stats,
                    "fallback_attempts": len(tried_models),
                }

            logger.info(
                "[%s] All parsed tool calls filtered (false positive) — returning as text",
                request_id,
            )
            return {
                "text": consumed["text"],
                "thinking": consumed["thinking"],
                "model": current_model,
                "stats": stats,
                "fallback_attempts": len(tried_models),
            }

        logger.info(
            "[%s] Text response (no tool calls) | len=%d | %.0fms",
            request_id, len(consumed["text"]),
            (time.monotonic() - start_time) * 1000,
        )
        return {
            "text": consumed["text"],
            "thinking": consumed["thinking"],
            "model": current_model,
            "fallback_attempts": len(tried_models),
            "stats": {"passed": 0, "normalized": 0, "filtered": 0, "invalid_arguments_filtered": 0},
        }

    logger.error("[%s] All fallback models exhausted", request_id)
    return {
        "error": "All available models are currently unavailable",
        "status": 503,
        "fallback_attempts": len(tried_models),
        "model": None,
    }


def _first_error_detail(errors: list) -> str:
    if not errors:
        return "Unknown stream error"
    err = errors[0]
    if isinstance(err, str):
        return err
    return str(
        getattr(err, "detail", None)
        or getattr(err, "raw", None)
        or getattr(err, "message", None)
        or err
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_claude_messages_pipeline(
    payload: dict,
    request_id: str,
    auth_token: str = "",
) -> dict:
    """Main pipeline entry point.

    Returns a dict with:
      - ok (bool)
      - stream (bool, if streaming)
      - body (dict, if non-streaming)
      - stream_handler (async generator, if streaming)
      - telemetry (dict)
    """
    pipeline_start = time.monotonic()

    normalized = normalize_anthropic_payload(payload)
    messages = normalized["messages"]
    tools = normalized["tools"]
    stream = normalized["stream"]
    resolved_model = normalized["resolved_model"]
    controls = normalized["request_controls"]
    valid_tool_names = [(t.get("function") or t).get("name", "") for t in tools]

    parsed_mt = _parse_max_tokens(controls.get("max_tokens"))
    if not parsed_mt["ok"]:
        return {
            "ok": False,
            "status": 400,
            "body": _to_api_error_body(parsed_mt["error"], "invalid_request_error"),
            "telemetry": {
                "request_id": request_id,
                "pipeline": "claude_code",
                "model_requested": resolved_model,
                "model_used": None,
                "latency_ms": _elapsed_ms(pipeline_start),
                "stream": stream,
            },
        }
    max_tokens = parsed_mt["value"]

    unsupported: list[str] = []
    if controls.get("temperature") is not None:
        unsupported.append("temperature")
    if controls.get("top_p") is not None:
        unsupported.append("top_p")
    if controls.get("stop") is not None:
        unsupported.append("stop")

    token = _extract_raw_auth_token(auth_token) or get_cursor_access_token()

    logger.info(
        "[%s] pipeline=claude_code model=%s stream=%s tools=%d msgs=%d max_tokens=%s",
        request_id, resolved_model, stream,
        len(valid_tool_names), len(messages),
        max_tokens or "-",
    )

    if unsupported:
        logger.warning(
            "[%s] Unsupported controls: %s", request_id, ", ".join(unsupported)
        )
        return {
            "ok": False,
            "status": 400,
            "body": _to_api_error_body(
                f"Unsupported request controls: {', '.join(unsupported)}",
                "invalid_request_error",
            ),
            "telemetry": {
                "request_id": request_id,
                "pipeline": "claude_code",
                "model_requested": resolved_model,
                "model_used": None,
                "latency_ms": _elapsed_ms(pipeline_start),
                "stream": stream,
                "unsupported_controls": unsupported,
            },
        }

    base_telemetry: dict[str, Any] = {
        "request_id": request_id,
        "pipeline": "claude_code",
        "model_requested": resolved_model,
        "max_tokens": max_tokens,
        "stream": stream,
        "agent_mode": True,
    }

    if stream:
        message_id = f"msg_{uuid.uuid4().hex}"

        async def stream_handler() -> AsyncIterator[str]:
            """Async generator that yields SSE strings."""
            session = StreamingAnthropicSession(message_id, resolved_model)
            yield session.emit_message_start()

            limiter = _OutputLimiter(max_tokens)
            sse_queue: asyncio.Queue[str | None] = asyncio.Queue()

            forwarder = ToolJsonAwareTextForwarder(
                emit_text_delta=lambda chunk: session.emit_text_delta(chunk),
                limiter=limiter,
            )

            def on_text_delta(delta: str) -> None:
                sse = forwarder.on_delta(delta)
                if sse:
                    sse_queue.put_nowait(sse)

            def on_thinking_delta(delta: str) -> None:
                if not delta:
                    return
                limited = limiter.emit_within_limit(delta)
                if limited:
                    sse = session.emit_thinking_delta(limited)
                    if sse:
                        sse_queue.put_nowait(sse)

            async def run_cursor_call() -> dict:
                return await _call_cursor_direct(
                    messages, resolved_model, tools, valid_tool_names, token,
                    on_stream_delta=on_text_delta,
                    on_thinking_delta=on_thinking_delta,
                )

            cursor_task = asyncio.create_task(run_cursor_call())

            while not cursor_task.done() or not sse_queue.empty():
                try:
                    sse = await asyncio.wait_for(sse_queue.get(), timeout=0.05)
                    if sse:
                        yield sse
                except asyncio.TimeoutError:
                    continue

            direct_result = cursor_task.result()

            if direct_result.get("error"):
                logger.error(
                    "[%s] pipeline=claude_code stage=error(stream) error=%s",
                    request_id, direct_result["error"],
                )
                yield session.finish(stop_reason="end_turn")
                return

            safe_text = direct_result.get("text", "")
            tool_calls = direct_result.get("tool_calls") or []
            stats = direct_result.get("stats") or {}

            flush_sse = forwarder.flush_using_final_safe_text(safe_text)
            if flush_sse:
                yield flush_sse

            yield session.close_open_blocks()

            text_is_done = "done!!" in safe_text
            needs_continuation = (
                not tool_calls
                and not text_is_done
                and safe_text
                and "Bash" in valid_tool_names
            )

            if needs_continuation:
                nudge_id = f"toolu_nudge_{uuid.uuid4().hex[:12]}"
                nudge_msg = (
                    "[SYSTEM] Your previous turn was text-only. "
                    "Task NOT done -> call a tool now (Write/Edit/Bash/Read). "
                    "Task IS done -> respond with done!! as your FINAL word. "
                    "No exceptions. Act immediately."
                )
                tool_calls.append({
                    "id": nudge_id,
                    "type": "function",
                    "function": {
                        "name": "Bash",
                        "arguments": json.dumps({
                            "command": f"echo '{nudge_msg}'",
                            "description": "continuation nudge",
                        }),
                    },
                })
                logger.info(
                    "[%s] Injected continuation nudge (no tool calls, no done!!)",
                    request_id,
                )

            if tool_calls:
                yield session.emit_tool_use_blocks(tool_calls)

            stop_reason: str
            if tool_calls:
                stop_reason = "tool_use"
            elif limiter.is_exhausted and not tool_calls:
                stop_reason = "max_tokens"
            else:
                stop_reason = "end_turn"

            yield session.finish(stop_reason=stop_reason)

            used_model = direct_result.get("model") or resolved_model
            latency = _elapsed_ms(pipeline_start)
            logger.info(
                "[%s] pipeline=claude_code stage=result(stream) model=%s "
                "tool_calls=%d stop_reason=%s latency_ms=%.0f",
                request_id, used_model, len(tool_calls), stop_reason, latency,
            )

        return {
            "ok": True,
            "stream": True,
            "stream_handler": stream_handler,
            "telemetry": {**base_telemetry, "model_used": resolved_model},
        }

    # --- Non-streaming (unary) path ---

    direct_result = await _call_cursor_direct(
        messages, resolved_model, tools, valid_tool_names, token,
    )

    logger.info(
        "[%s] DIRECT_RESULT(unary): text_len=%d tool_calls=%d error=%s",
        request_id,
        len(direct_result.get("text", "")),
        len(direct_result.get("tool_calls") or []),
        direct_result.get("error"),
    )

    if direct_result.get("error"):
        return {
            "ok": False,
            "status": direct_result.get("status", 500),
            "body": _to_api_error_body(direct_result["error"]),
            "telemetry": {
                **base_telemetry,
                "model_used": direct_result.get("model"),
                "latency_ms": _elapsed_ms(pipeline_start),
            },
        }

    used_model = direct_result.get("model") or resolved_model
    tool_calls = direct_result.get("tool_calls") or []
    text = direct_result.get("text", "")
    thinking = direct_result.get("thinking", "")
    message_id = f"msg_{uuid.uuid4().hex}"

    truncated = False
    if max_tokens and max_tokens > 0:
        char_budget = max_tokens * 4
        if len(text) > char_budget:
            text = text[:char_budget]
            truncated = True

    stop_reason_override = ""
    if not tool_calls and truncated:
        stop_reason_override = "max_tokens"

    telemetry = {
        **base_telemetry,
        "model_used": used_model,
        "fallback_attempts": direct_result.get("fallback_attempts", 0),
        "latency_ms": _elapsed_ms(pipeline_start),
        "stream": False,
        "output_truncated": truncated,
    }

    logger.info(
        "[%s] pipeline=claude_code stage=result model=%s tool_calls=%d "
        "text_len=%d latency_ms=%.0f",
        request_id, used_model, len(tool_calls), len(text), telemetry["latency_ms"],
    )

    return {
        "ok": True,
        "stream": False,
        "body": build_unary_anthropic_response(
            message_id=message_id,
            model=used_model,
            text=text,
            thinking="",
            tool_calls=tool_calls,
            stop_reason_override=stop_reason_override,
        ),
        "telemetry": telemetry,
    }


def _elapsed_ms(start: float) -> float:
    return (time.monotonic() - start) * 1000
