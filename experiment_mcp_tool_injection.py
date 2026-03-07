"""
Experiment: Inject MCP tool definitions into Cursor API request.

Goal: Verify that when we send `supported_tools=[19,49]` + `mcp_tools` (field 34)
containing fake MCP tool definitions (disguised Claude Code tools), the Cursor API
returns structured `ClientSideToolV2Call` with tool=19 (MCP) or tool=49 (CALL_MCP_TOOL).

Proto structure:
  StreamUnifiedChatRequest {
    ...
    repeated int32 supported_tools = 29;   // [19, 49, ...]
    repeated McpTools mcp_tools = 34;      // MCP tool definitions
    ...
  }

  agent.v1.McpTools {
    repeated McpToolDefinition mcp_tools = 1;
  }

  agent.v1.McpToolDefinition {
    string name = 1;                    // full tool name
    string description = 2;
    google.protobuf.Struct input_schema = 3;
    string provider_identifier = 4;     // server identifier
    string tool_name = 5;              // tool name on server
  }
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import struct
import subprocess
import sys
import time
from uuid import uuid4

try:
    import httpx
    import httpcore
except ImportError:
    print("pip install httpx httpcore h2")
    sys.exit(1)

try:
    from google.protobuf import struct_pb2
except ImportError:
    print("pip install protobuf")
    sys.exit(1)

CURSOR_CLOUDFLARE_IP = os.environ.get("CURSOR_CLOUDFLARE_IP", "104.18.19.125")
CURSOR_API_HOST = "https://api2.cursor.sh"
CURSOR_CLIENT_VERSION = "2.5.25"


def get_token() -> str:
    result = subprocess.run(
        ["sqlite3",
         os.path.expanduser("~/Library/Application Support/Cursor/User/globalStorage/state.vscdb"),
         "SELECT value FROM ItemTable WHERE key = 'cursorAuth/accessToken';"],
        capture_output=True, text=True
    )
    return result.stdout.strip()


def sha256_hex(s: str, salt: str = "") -> str:
    return hashlib.sha256((s + salt).encode()).hexdigest()


def xor_chain(ba: bytearray) -> bytearray:
    t = 165
    for i in range(len(ba)):
        ba[i] = ((ba[i] ^ t) + (i % 256)) & 0xFF
        t = ba[i]
    return ba


def generate_checksum(token: str) -> str:
    machine_id = sha256_hex(token, "machineId")
    mac_machine_id = sha256_hex(token, "macMachineId")
    ts = int(time.time() * 1000) // 1_000_000
    raw = bytearray([
        (ts >> 40) & 0xFF, (ts >> 32) & 0xFF, (ts >> 24) & 0xFF,
        (ts >> 16) & 0xFF, (ts >> 8) & 0xFF, ts & 0xFF,
    ])
    encoded = base64.b64encode(bytes(xor_chain(raw))).decode("ascii")
    return f"{encoded}{machine_id}/{mac_machine_id}"


# ── Low-level protobuf encoding ──

def pb_varint(value: int) -> bytes:
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def pb_field(field_no: int, wire_type: int, data: bytes) -> bytes:
    tag = pb_varint((field_no << 3) | wire_type)
    if wire_type == 0:
        return tag + data
    elif wire_type == 2:
        return tag + pb_varint(len(data)) + data
    return tag + data


def pb_string(field_no: int, value: str) -> bytes:
    return pb_field(field_no, 2, value.encode("utf-8"))


def pb_int32(field_no: int, value: int) -> bytes:
    return pb_field(field_no, 0, pb_varint(value))


def pb_bytes_field(field_no: int, value: bytes) -> bytes:
    return pb_field(field_no, 2, value)


def pb_message(field_no: int, inner: bytes) -> bytes:
    return pb_field(field_no, 2, inner)


def json_to_struct_pb(obj: dict) -> bytes:
    s = struct_pb2.Struct()
    s.update(obj)
    return s.SerializeToString()


def build_mcp_tool_definition(
    name: str,
    description: str,
    input_schema: dict,
    provider_identifier: str,
    tool_name: str,
) -> bytes:
    """Build agent.v1.McpToolDefinition"""
    msg = b""
    msg += pb_string(1, name)
    msg += pb_string(2, description)
    msg += pb_bytes_field(3, json_to_struct_pb(input_schema))
    msg += pb_string(4, provider_identifier)
    msg += pb_string(5, tool_name)
    return msg


def build_mcp_tools(tool_defs: list[bytes]) -> bytes:
    """Build agent.v1.McpTools { repeated McpToolDefinition mcp_tools = 1; }"""
    msg = b""
    for td in tool_defs:
        msg += pb_message(1, td)
    return msg


CC_TOOLS = [
    {
        "name": "Bash",
        "description": "Execute a bash command in the terminal. Use for running scripts, installing packages, or system operations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The bash command to execute"},
                "description": {"type": "string", "description": "Short description of what this command does"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "Read",
        "description": "Read the contents of a file at the specified path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The absolute path of the file to read"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "Write",
        "description": "Write content to a file at the specified path. Creates the file if it doesn't exist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The absolute path of the file to write"},
                "contents": {"type": "string", "description": "The contents to write"},
            },
            "required": ["path", "contents"],
        },
    },
]

MCP_SERVER_ID = "claude-tools"


def build_request_body(user_prompt: str, model: str = "claude-sonnet-4-20250514") -> bytes:
    """Build StreamUnifiedChatWithToolsRequest with MCP tool definitions."""

    msg_id = str(uuid4())
    conv_id = str(uuid4())

    inner_request = b""

    user_msg = (
        pb_string(1, user_prompt)
        + pb_int32(2, 1)
        + pb_string(13, msg_id)
        + pb_int32(47, 2)
    )
    inner_request += pb_message(1, user_msg)

    inner_request += pb_int32(2, 1)
    inner_request += pb_message(3, pb_string(1, ""))
    inner_request += pb_int32(4, 1)
    inner_request += pb_message(5, pb_string(1, model) + pb_bytes_field(4, b""))
    inner_request += pb_string(8, "")
    inner_request += pb_int32(13, 1)

    cursor_setting = (
        pb_string(1, "cursor\\aisettings")
        + pb_bytes_field(3, b"")
        + pb_message(6, pb_bytes_field(1, b"") + pb_bytes_field(2, b""))
        + pb_int32(8, 1)
        + pb_int32(9, 1)
    )
    inner_request += pb_message(15, cursor_setting)

    inner_request += pb_int32(19, 1)
    inner_request += pb_string(23, conv_id)

    ts_str = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    metadata = (
        pb_string(1, "darwin")
        + pb_string(2, "arm64")
        + pb_string(3, "24.0.0")
        + pb_string(4, "/bin/zsh")
        + pb_string(5, ts_str)
    )
    inner_request += pb_message(26, metadata)

    inner_request += pb_int32(27, 1)

    supported_tool_ids = [19, 49]
    for tid in supported_tool_ids:
        inner_request += pb_int32(29, tid)

    mid_entry = pb_string(1, msg_id) + pb_int32(3, 1)
    inner_request += pb_message(30, mid_entry)

    tool_defs = []
    for tool in CC_TOOLS:
        td = build_mcp_tool_definition(
            name=tool["name"],
            description=tool["description"],
            input_schema=tool["input_schema"],
            provider_identifier=MCP_SERVER_ID,
            tool_name=tool["name"],
        )
        tool_defs.append(td)

    mcp_tools_msg = build_mcp_tools(tool_defs)
    inner_request += pb_message(34, mcp_tools_msg)

    inner_request += pb_int32(35, 0)
    inner_request += pb_int32(38, 0)
    inner_request += pb_int32(46, 2)
    inner_request += pb_string(47, "")
    inner_request += pb_int32(48, 1)
    inner_request += pb_int32(49, 0)
    inner_request += pb_int32(51, 0)
    inner_request += pb_int32(53, 1)
    inner_request += pb_string(54, "Agent")

    outer = pb_message(1, inner_request)

    payload = outer
    magic = 0x00
    if len(payload) > 1024:
        payload = gzip.compress(payload)
        magic = 0x01
    return bytes([magic]) + struct.pack(">I", len(payload)) + payload


def parse_response_frames(data: bytes) -> list[dict]:
    """Parse Cursor's framed protobuf response, extract text and tool calls."""
    frames = []
    buf = bytearray(data)
    idx = 0

    while idx + 5 <= len(buf):
        magic = buf[idx]
        frame_len = struct.unpack(">I", buf[idx+1:idx+5])[0]
        if idx + 5 + frame_len > len(buf):
            break
        frame_data = bytes(buf[idx+5:idx+5+frame_len])
        idx += 5 + frame_len

        if magic == 1:
            try:
                frame_data = gzip.decompress(frame_data)
            except Exception:
                pass

        frames.append({"magic": magic, "raw": frame_data, "hex_preview": frame_data[:200].hex()})

    return frames


import ssl as _ssl


class _CloudflareOverrideBackend(httpcore.AsyncNetworkBackend):
    def __init__(self):
        from httpcore._backends.auto import AutoBackend
        self._inner = AutoBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        target = CURSOR_CLOUDFLARE_IP if host == "api2.cursor.sh" else host
        return await self._inner.connect_tcp(target, port, timeout=timeout,
                                              local_address=local_address, socket_options=socket_options)

    async def connect_unix_socket(self, path, **kw):
        return await self._inner.connect_unix_socket(path, **kw)

    async def sleep(self, seconds):
        await self._inner.sleep(seconds)


def make_h2_client(**kwargs):
    ctx = _ssl.create_default_context()
    ctx.set_alpn_protocols(["h2"])
    backend = _CloudflareOverrideBackend()
    pool = httpcore.AsyncConnectionPool(
        ssl_context=ctx, http2=True,
        max_connections=10, max_keepalive_connections=5,
        network_backend=backend,
    )
    transport = httpx.AsyncHTTPTransport(http2=True, verify=ctx)
    transport._pool = pool
    return httpx.AsyncClient(transport=transport, **kwargs)


async def run_experiment():
    token = get_token()
    if not token:
        print("ERROR: No Cursor token found")
        return

    print(f"Token length: {len(token)}")
    print(f"Token prefix: {token[:30]}...")

    checksum = generate_checksum(token)
    client_key = sha256_hex(token)

    prompt = "Please list the files in /tmp using the Bash tool."
    body = build_request_body(prompt, model="claude-4.5-sonnet")

    print(f"\nRequest body size: {len(body)} bytes")
    print(f"Magic byte: 0x{body[0]:02x}")

    headers = {
        "authorization": f"Bearer {token}",
        "connect-accept-encoding": "gzip",
        "connect-protocol-version": "1",
        "content-type": "application/connect+proto",
        "user-agent": "connect-es/1.6.1",
        "x-amzn-trace-id": f"Root={uuid4()}",
        "x-client-key": client_key,
        "x-cursor-checksum": checksum,
        "x-cursor-client-version": CURSOR_CLIENT_VERSION,
        "x-cursor-config-version": str(uuid4()),
        "x-cursor-timezone": "Asia/Shanghai",
        "x-ghost-mode": "true",
        "x-request-id": str(uuid4()),
        "Host": "api2.cursor.sh",
    }

    if body[0] == 0x01:
        headers["connect-content-encoding"] = "gzip"

    print("\n--- Sending request to Cursor API ---")
    print(f"Prompt: {prompt}")
    print(f"Model: claude-4.5-sonnet")
    print(f"Supported tools: [19, 49] (MCP only)")
    print(f"MCP tools injected: {[t['name'] for t in CC_TOOLS]}")

    response_chunks = []
    tool_call_detected = False

    async with make_h2_client(timeout=httpx.Timeout(120, connect=15)) as client:
        async with client.stream(
            "POST",
            f"{CURSOR_API_HOST}/aiserver.v1.ChatService/StreamUnifiedChatWithTools",
            headers=headers,
            content=body,
        ) as resp:
            print(f"\nHTTP status: {resp.status_code}")

            if resp.status_code != 200:
                error = await resp.aread()
                print(f"Error: {error[:500]}")
                return

            full_data = bytearray()
            async for chunk in resp.aiter_bytes():
                full_data.extend(chunk)

    print(f"\nTotal response size: {len(full_data)} bytes")

    frames = parse_response_frames(bytes(full_data))
    print(f"Frames parsed: {len(frames)}")

    for i, frame in enumerate(frames):
        raw = frame["raw"]
        text_content = ""
        try:
            text_content = raw.decode("utf-8", errors="replace")
        except Exception:
            pass

        if "tool" in text_content.lower() or b"\x08\x13" in raw or b"\x08\x31" in raw:
            print(f"\n=== Frame {i} (potential tool call) ===")
            print(f"  Size: {len(raw)} bytes")
            print(f"  Hex (first 300): {raw[:300].hex()}")
            if text_content:
                printable = ''.join(c if c.isprintable() or c in '\n\t' else f'[{ord(c):02x}]' for c in text_content[:500])
                print(f"  Text: {printable}")
            tool_call_detected = True
        elif len(raw) > 10:
            printable = ''.join(c if c.isprintable() or c in '\n\t' else '.' for c in text_content[:200])
            if printable.strip():
                print(f"\n--- Frame {i}: {printable[:150]}...")

    if not tool_call_detected:
        print("\n*** No obvious tool calls detected in response ***")
        print("Dumping all frames for manual inspection:")
        for i, frame in enumerate(frames[:20]):
            raw = frame["raw"]
            print(f"\n  Frame {i}: {len(raw)} bytes")
            print(f"    Hex: {raw[:100].hex()}")
            try:
                text = raw.decode("utf-8", errors="replace")
                printable = ''.join(c if c.isprintable() or c in '\n\t' else f'[{ord(c):02x}]' for c in text[:300])
                print(f"    Text: {printable}")
            except Exception:
                pass


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_experiment())
