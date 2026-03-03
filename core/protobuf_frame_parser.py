"""
Cursor streaming response frame parser with cross-chunk buffering.

Cursor's server-streaming RPC sends data in a custom framing format
(not standard gRPC-Web). Each frame is [1-byte magic][4-byte BE length][payload].
HTTP/2 data frames can split a logical frame across multiple chunks, so we
accumulate a buffer and only decode complete frames.

Magic 0/1 carry protobuf payloads (raw / gzip-compressed).
Magic 2/3 carry JSON error messages (raw / gzip-compressed).

Port of: cursor_streaming_response_protobuf_frame_parser.js
"""

from __future__ import annotations

import gzip
import json
import logging
import struct
from dataclasses import dataclass, field

from proto import cursor_api_pb2 as pb

logger = logging.getLogger(__name__)


@dataclass
class ParsedError:
    raw: str
    parsed: dict | None = None
    detail: str = ""
    error_code: str | None = None


@dataclass
class ParseResult:
    thinking: str = ""
    text: str = ""
    errors: list[ParsedError] = field(default_factory=list)


class ProtobufFrameParser:
    """Stateful parser that accumulates a buffer across successive HTTP/2 chunks."""

    __slots__ = ("_buf",)

    def __init__(self) -> None:
        self._buf = b""

    def parse(self, chunk: bytes) -> ParseResult:
        self._buf += bytes(chunk)

        thinking_parts: list[str] = []
        text_parts: list[str] = []
        errors: list[ParsedError] = []

        while len(self._buf) >= 5:
            magic = self._buf[0]
            (data_length,) = struct.unpack(">I", self._buf[1:5])

            if len(self._buf) < 5 + data_length:
                break

            data = self._buf[5 : 5 + data_length]
            self._buf = self._buf[5 + data_length :]

            try:
                if magic in (0, 1):
                    raw_data = gzip.decompress(data) if magic == 1 else data
                    response = pb.StreamUnifiedChatWithToolsResponse()
                    response.ParseFromString(raw_data)

                    if response.HasField("message"):
                        msg = response.message
                        if msg.HasField("thinking") and msg.thinking.content:
                            thinking_parts.append(msg.thinking.content)
                        if msg.content:
                            text_parts.append(msg.content)

                elif magic in (2, 3):
                    raw_data = gzip.decompress(data) if magic == 3 else data
                    utf8 = raw_data.decode("utf-8", errors="replace")

                    if utf8 and utf8 not in ("{}", "null"):
                        logger.warning("Cursor error frame: %s", utf8[:500])
                        try:
                            err_obj = json.loads(utf8)
                            detail = (
                                _deep_get(err_obj, "error", "details", 0, "debug", "details", "detail")
                                or _deep_get(err_obj, "error", "message")
                                or utf8
                            )
                            errors.append(ParsedError(
                                raw=utf8,
                                parsed=err_obj,
                                detail=detail,
                                error_code=_deep_get(err_obj, "error", "details", 0, "debug", "error"),
                            ))
                            text_parts.append(f"[Error] {detail}")
                        except (json.JSONDecodeError, ValueError):
                            text_parts.append(f"[Error] {utf8}")
                            errors.append(ParsedError(raw=utf8, detail=utf8))

            except Exception as exc:
                logger.warning("Frame decode error: %s", exc)

        return ParseResult(
            thinking="".join(thinking_parts),
            text="".join(text_parts),
            errors=errors,
        )


def _deep_get(obj, *keys):
    """Safely traverse nested dicts/lists. Returns None on any miss."""
    for k in keys:
        if obj is None:
            return None
        if isinstance(k, int):
            if isinstance(obj, list) and 0 <= k < len(obj):
                obj = obj[k]
            else:
                return None
        elif isinstance(obj, dict):
            obj = obj.get(k)
        else:
            return None
    return obj
