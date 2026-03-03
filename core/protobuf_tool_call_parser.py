from __future__ import annotations
"""
Protobuf wire-level parser for ClientSideToolV2Call messages.

Cursor's Agent mode returns structured tool calls embedded in the streaming
protobuf response. These are not accessible via the generated protobuf classes
(which lack the tool call message definitions), so we parse the raw wire format.

ClientSideToolV2Call wire fields (empirically determined from tests):
  field 1 (varint):  ClientSideToolV2 enum value (e.g. 45 = READ_MCP_RESOURCE)
  field 3 (bytes):   tool_call_id (string, e.g. "call_abc123...")
  field 9 (bytes):   tool name (string, e.g. "fetch_mcp_resource")
  field 10 (bytes):  raw arguments JSON (string)
  field 14 (varint): streaming flag
  field 15 (varint): last flag
"""

import json
from dataclasses import dataclass


@dataclass
class ToolCall:
    enum: int
    tool_call_id: str
    name: str
    raw_args: str
    args: dict
    is_streaming: bool = False
    is_last: bool = True


def _decode_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while pos < len(buf):
        b = buf[pos]
        result |= (b & 0x7F) << shift
        pos += 1
        if (b & 0x80) == 0:
            return result, pos
        shift += 7
    return result, pos


def _parse_wire_fields(buf: bytes) -> dict[int, list[tuple[str, bytes | int]]]:
    """Parse protobuf wire format into {field_number: [(wire_type_tag, value)]}."""
    fields: dict[int, list[tuple[str, bytes | int]]] = {}
    pos = 0
    while pos < len(buf):
        tag, pos = _decode_varint(buf, pos)
        field_num = tag >> 3
        wire_type = tag & 7

        if wire_type == 0:
            val, pos = _decode_varint(buf, pos)
            fields.setdefault(field_num, []).append(("varint", val))
        elif wire_type == 2:
            length, pos = _decode_varint(buf, pos)
            if pos + length > len(buf):
                break
            fields.setdefault(field_num, []).append(("bytes", buf[pos:pos + length]))
            pos += length
        elif wire_type == 1:
            if pos + 8 > len(buf):
                break
            fields.setdefault(field_num, []).append(("fixed64", buf[pos:pos + 8]))
            pos += 8
        elif wire_type == 5:
            if pos + 4 > len(buf):
                break
            fields.setdefault(field_num, []).append(("fixed32", buf[pos:pos + 4]))
            pos += 4
        else:
            break
    return fields


def _try_decode_utf8(data: bytes) -> str | None:
    try:
        s = data.decode("utf-8")
        if all(32 <= ord(c) < 127 or c in "\n\r\t" for c in s[:100]):
            return s
    except (UnicodeDecodeError, ValueError):
        pass
    return None


def _extract_tool_calls_recursive(data: bytes, depth: int = 0) -> list[ToolCall]:
    """Recursively search protobuf wire data for ClientSideToolV2Call patterns."""
    results: list[ToolCall] = []
    if depth > 4 or len(data) < 5:
        return results

    fields = _parse_wire_fields(data)

    tc_enum = 0
    tc_id = ""
    tc_name = ""
    tc_raw_args = ""
    tc_streaming = False
    tc_last = False

    for field_num, entries in fields.items():
        for wtype, val in entries:
            if field_num == 1 and wtype == "varint":
                tc_enum = val
            elif field_num == 3 and wtype == "bytes":
                s = _try_decode_utf8(val)
                if s:
                    tc_id = s
            elif field_num == 9 and wtype == "bytes":
                s = _try_decode_utf8(val)
                if s:
                    tc_name = s
            elif field_num == 10 and wtype == "bytes":
                s = _try_decode_utf8(val)
                if s:
                    tc_raw_args = s
            elif field_num == 14 and wtype == "varint":
                tc_streaming = bool(val)
            elif field_num == 15 and wtype == "varint":
                tc_last = bool(val)

    if tc_enum > 0 and tc_id and tc_raw_args:
        if "\n" in tc_id:
            tc_id = tc_id.split("\n")[0]
        args = {}
        try:
            parsed = json.loads(tc_raw_args)
            if isinstance(parsed, dict):
                args = parsed
        except (json.JSONDecodeError, ValueError):
            pass
        if args:
            results.append(ToolCall(
                enum=tc_enum,
                tool_call_id=tc_id,
                name=tc_name,
                raw_args=tc_raw_args,
                args=args,
                is_streaming=tc_streaming,
                is_last=tc_last,
            ))

    for field_num, entries in fields.items():
        for wtype, val in entries:
            if wtype == "bytes" and isinstance(val, bytes) and len(val) > 5:
                results.extend(_extract_tool_calls_recursive(val, depth + 1))

    return results


def extract_tool_calls_from_frame(frame_data: bytes) -> list[ToolCall]:
    """Extract all ClientSideToolV2Call messages from a decompressed protobuf frame.

    Returns deduplicated tool calls (by tool_call_id).
    """
    raw = _extract_tool_calls_recursive(frame_data)

    seen_ids: set[str] = set()
    deduped: list[ToolCall] = []
    for tc in raw:
        if tc.tool_call_id and tc.tool_call_id not in seen_ids:
            seen_ids.add(tc.tool_call_id)
            deduped.append(tc)

    return deduped
