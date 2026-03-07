"""
Experiment v2: Two tests for MCP tool calling via Cursor API.

Test A: Zero native tools + full MCP injection via protobuf fields
  - supported_tools = [19, 49]
  - mcp_tools (field 34) = McpTools with tool definitions

Test B: Zero tools at all + prompt injection of tool definitions in user message
  - supported_tools = [] (empty)
  - User message contains JSON tool definitions and asks model to call them

Token: from thalamus-py .env (CURSOR_TOKEN) via token_manager
Model: gpt-5.3-codex-spark-preview-xhigh (GPT-5.3 Spark)
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import ssl as _ssl
import struct
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import httpcore
from dotenv import load_dotenv
from google.protobuf import struct_pb2

# Load .env from thalamus-py root
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)

from core.token_manager import get_cursor_access_token
from core.bearer_token import strip_cursor_user_prefix

CURSOR_CLOUDFLARE_IP = os.environ.get("CURSOR_CLOUDFLARE_IP", "104.18.19.125")
CURSOR_API_HOST = "https://api2.cursor.sh"
CURSOR_CLIENT_VERSION = "2.5.25"
MCP_SERVER_ID = "claude-tools"
MCP_SERVER_NAME = "Claude Code Tools"
MODEL = "gpt-5.3-codex-spark-preview-xhigh"


def get_token() -> str:
    raw = get_cursor_access_token()
    return strip_cursor_user_prefix(raw)


def sha256_hex(s: str, salt: str = "") -> str:
    return hashlib.sha256((s + salt).encode()).hexdigest()


def xor_chain(ba: bytearray) -> bytearray:
    t = 165
    for i in range(len(ba)):
        ba[i] = ((ba[i] ^ t) + (i % 256)) & 0xFF
        t = ba[i]
    return ba


def generate_checksum(token: str) -> str:
    mid = sha256_hex(token, "machineId")
    mac = sha256_hex(token, "macMachineId")
    ts = int(time.time() * 1000) // 1_000_000
    raw = bytearray([(ts >> 40) & 0xFF, (ts >> 32) & 0xFF, (ts >> 24) & 0xFF,
                      (ts >> 16) & 0xFF, (ts >> 8) & 0xFF, ts & 0xFF])
    enc = base64.b64encode(bytes(xor_chain(raw))).decode("ascii")
    return f"{enc}{mid}/{mac}"


# ── protobuf primitives ──

def pv(value: int) -> bytes:
    r = bytearray()
    while value > 0x7F:
        r.append((value & 0x7F) | 0x80); value >>= 7
    r.append(value & 0x7F)
    return bytes(r)

def pf(fno: int, wt: int, data: bytes) -> bytes:
    tag = pv((fno << 3) | wt)
    return tag + data if wt == 0 else tag + pv(len(data)) + data

def ps(fno: int, v: str) -> bytes: return pf(fno, 2, v.encode("utf-8"))
def pi(fno: int, v: int) -> bytes: return pf(fno, 0, pv(v))
def pb(fno: int, v: bytes) -> bytes: return pf(fno, 2, v)
def pm(fno: int, inner: bytes) -> bytes: return pf(fno, 2, inner)

def struct_pb(obj: dict) -> bytes:
    s = struct_pb2.Struct()
    s.update(obj)
    return s.SerializeToString()


# ── tool definitions ──

TOOLS = [
    {
        "name": "Bash",
        "description": "Execute a bash command. Use for running scripts, installing packages, file operations, git commands, or any system task. Returns stdout, stderr and exit code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The bash command to execute"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "Read",
        "description": "Read the contents of a file at the given path. Returns file content as text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path of the file to read"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "Write",
        "description": "Write content to a file. Creates parent directories if needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path of the file"},
                "contents": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "contents"],
        },
    },
]

MCP_INSTRUCTIONS_TEXT = f"""The {MCP_SERVER_NAME} MCP server provides these tools:
- Bash: Execute bash commands
- Read: Read file contents
- Write: Write files

When the user asks you to perform file operations or run commands, you MUST use these MCP tools by generating a structured tool call. Do NOT output the result as text - actually call the tool."""


def build_mcp_tool_def(t: dict) -> bytes:
    msg = ps(1, t["name"])
    msg += ps(2, t["description"])
    msg += pb(3, struct_pb(t["input_schema"]))
    msg += ps(4, MCP_SERVER_ID)
    msg += ps(5, t["name"])
    return msg


def build_mcp_tools_msg() -> bytes:
    msg = b""
    for t in TOOLS:
        msg += pm(1, build_mcp_tool_def(t))
    return msg


def build_mcp_instructions() -> bytes:
    """aiserver.v1.MCPInstructions: server_name=1, server_identifier=2, instructions=3"""
    return ps(1, MCP_SERVER_NAME) + ps(2, MCP_SERVER_ID) + ps(3, MCP_INSTRUCTIONS_TEXT)


def build_mcp_descriptor() -> bytes:
    """aiserver.v1.McpDescriptor: name=1, description=2, source_path=3, source_url=4"""
    return ps(1, MCP_SERVER_NAME) + ps(2, "Claude Code tools exposed as MCP server")


# ── request builders ──

def _common_request_fields(conv_id: str) -> bytes:
    r = b""
    r += pi(2, 1)
    r += pm(3, ps(1, ""))
    r += pi(4, 1)
    r += pm(5, ps(1, MODEL) + pb(4, b""))
    r += ps(8, "")
    r += pi(13, 1)
    r += pm(15, ps(1, "cursor\\aisettings") + pb(3, b"") +
            pm(6, pb(1, b"") + pb(2, b"")) + pi(8, 1) + pi(9, 1))
    r += pi(19, 1)
    r += ps(23, conv_id)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    r += pm(26, ps(1, "darwin") + ps(2, "arm64") + ps(3, "24.0.0") +
            ps(4, "/bin/zsh") + ps(5, ts))
    r += pi(27, 1)  # is_agentic
    return r


def build_test_a(prompt: str, variant: str = "full") -> bytes:
    """Test A: MCP injection via protobuf fields.
    variant='tools_only': mcp_tools (field 34) only
    variant='full': mcp_tools + has_mcp_descriptors=true (field 90)
    variant='tools+native': mcp_tools + all native tools
    variant='prompt+mcp': mcp_tools + instructions in system message
    """
    msg_id = str(uuid4())
    conv_id = str(uuid4())

    req = b""

    if variant == "prompt+mcp":
        sys_msg = ps(1, MCP_INSTRUCTIONS_TEXT) + pi(2, 2)
        req += pm(1, sys_msg)
        user_msg = ps(1, prompt) + pi(2, 1) + ps(13, msg_id) + pi(47, 2)
        req += pm(1, user_msg)
    else:
        user_msg = ps(1, prompt) + pi(2, 1) + ps(13, msg_id) + pi(47, 2)
        req += pm(1, user_msg)

    req += _common_request_fields(conv_id)

    if variant == "tools+native":
        for tid in [5, 6, 7, 8, 11, 15, 18, 19, 38, 39, 40, 41, 42, 44, 45, 49]:
            req += pi(29, tid)
    else:
        for tid in [19, 49]:
            req += pi(29, tid)

    req += pm(30, ps(1, msg_id) + pi(3, 1))

    req += pm(34, build_mcp_tools_msg())

    req += pi(35, 0)
    req += pi(38, 0)
    req += pi(46, 2)
    req += ps(47, "")
    req += pi(48, 1)
    req += pi(49, 0)
    req += pi(51, 0)
    req += pi(53, 1)
    req += ps(54, "Agent")

    if variant == "full":
        req += pi(90, 1)  # has_mcp_descriptors = true

    outer = pm(1, req)
    payload = outer
    magic = 0x00
    if len(payload) > 1024:
        payload = gzip.compress(payload)
        magic = 0x01
    return bytes([magic]) + struct.pack(">I", len(payload)) + payload


def build_test_b(prompt: str) -> bytes:
    """Test B: Zero tools, prompt injection via user message."""
    msg_id = str(uuid4())
    conv_id = str(uuid4())

    tools_json = json.dumps([{
        "name": t["name"],
        "description": t["description"],
        "input_schema": t["input_schema"],
    } for t in TOOLS], indent=2)

    injected_prompt = f"""You have access to these tools. When you need to use a tool, output ONLY a JSON object in this exact format, with no other text before or after:

{{"tool_call": {{"name": "<tool_name>", "arguments": {{...}}}}}}

Available tools:
{tools_json}

User request: {prompt}"""

    req = b""
    user_msg = ps(1, injected_prompt) + pi(2, 1) + ps(13, msg_id) + pi(47, 2)
    req += pm(1, user_msg)

    req += _common_request_fields(conv_id)
    # NO supported_tools at all
    req += pm(30, ps(1, msg_id) + pi(3, 1))
    req += pi(35, 0)
    req += pi(38, 0)
    req += pi(46, 2)
    req += ps(47, "")
    req += pi(48, 1)
    req += pi(49, 0)
    req += pi(51, 0)
    req += pi(53, 1)
    req += ps(54, "Agent")

    outer = pm(1, req)
    payload = outer
    magic = 0x00
    if len(payload) > 1024:
        payload = gzip.compress(payload)
        magic = 0x01
    return bytes([magic]) + struct.pack(">I", len(payload)) + payload


# ── network ──

class _CFBackend(httpcore.AsyncNetworkBackend):
    def __init__(self):
        from httpcore._backends.auto import AutoBackend
        self._inner = AutoBackend()
    async def connect_tcp(self, host, port, **kw):
        target = CURSOR_CLOUDFLARE_IP if host == "api2.cursor.sh" else host
        return await self._inner.connect_tcp(target, port, **kw)
    async def connect_unix_socket(self, path, **kw):
        return await self._inner.connect_unix_socket(path, **kw)
    async def sleep(self, s): await self._inner.sleep(s)


def make_client(**kw):
    ctx = _ssl.create_default_context(); ctx.set_alpn_protocols(["h2"])
    pool = httpcore.AsyncConnectionPool(ssl_context=ctx, http2=True,
        max_connections=10, max_keepalive_connections=5, network_backend=_CFBackend())
    t = httpx.AsyncHTTPTransport(http2=True, verify=ctx)
    t._pool = pool
    return httpx.AsyncClient(transport=t, **kw)


def parse_frames(data: bytes) -> list[dict]:
    frames, buf, idx = [], bytearray(data), 0
    while idx + 5 <= len(buf):
        magic = buf[idx]
        flen = struct.unpack(">I", buf[idx+1:idx+5])[0]
        if idx + 5 + flen > len(buf): break
        raw = bytes(buf[idx+5:idx+5+flen]); idx += 5 + flen
        if magic == 1:
            try: raw = gzip.decompress(raw)
            except: pass
        frames.append({"magic": magic, "raw": raw})
    return frames


def print_frame(i: int, raw: bytes):
    txt = raw.decode("utf-8", errors="replace")
    printable = ''.join(c if c.isprintable() or c in '\n\t' else f'[{ord(c):02x}]' for c in txt[:600])

    is_json_error = raw[:1] == b'{' and b'"error"' in raw[:50]
    has_tool_sig = (b'\x08\x13' in raw or b'\x08\x31' in raw or
                    b'tool' in raw.lower() or b'call_mcp' in raw.lower() or
                    b'toolu_' in raw)
    has_json_tool = b'"tool_call"' in raw or b'"name"' in raw

    if is_json_error:
        try:
            err = json.loads(raw)
            detail = err.get("error", {}).get("details", [{}])[0].get("debug", {}).get("details", {}).get("detail", "")
            print(f"  Frame {i} [ERROR]: {detail or raw[:200].decode()}")
        except:
            print(f"  Frame {i} [ERROR]: {printable[:200]}")
    elif has_tool_sig:
        print(f"  Frame {i} [TOOL CALL?] ({len(raw)}B):")
        print(f"    hex: {raw[:200].hex()}")
        print(f"    txt: {printable[:400]}")
    elif has_json_tool:
        print(f"  Frame {i} [JSON TOOL?] ({len(raw)}B):")
        print(f"    {printable[:400]}")
    elif len(raw) > 5:
        clean = ''.join(c if c.isprintable() else '' for c in txt[:300]).strip()
        if clean:
            print(f"  Frame {i}: {clean[:200]}")


async def send_request(label: str, body: bytes, token: str):
    checksum = generate_checksum(token)
    headers = {
        "authorization": f"Bearer {token}",
        "connect-accept-encoding": "gzip",
        "connect-protocol-version": "1",
        "content-type": "application/connect+proto",
        "user-agent": "connect-es/1.6.1",
        "x-amzn-trace-id": f"Root={uuid4()}",
        "x-client-key": sha256_hex(token),
        "x-cursor-checksum": checksum,
        "x-cursor-client-version": CURSOR_CLIENT_VERSION,
        "x-cursor-timezone": "Asia/Shanghai",
        "x-ghost-mode": "true",
        "x-request-id": str(uuid4()),
        "Host": "api2.cursor.sh",
    }
    if body[0] == 0x01:
        headers["connect-content-encoding"] = "gzip"

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  Body: {len(body)}B, magic=0x{body[0]:02x}")
    print(f"{'='*60}")

    full = bytearray()
    async with make_client(timeout=httpx.Timeout(120, connect=15)) as client:
        async with client.stream("POST",
            f"{CURSOR_API_HOST}/aiserver.v1.ChatService/StreamUnifiedChatWithTools",
            headers=headers, content=body) as resp:
            print(f"  HTTP {resp.status_code}")
            if resp.status_code != 200:
                err = await resp.aread()
                print(f"  Error: {err[:300]}")
                return
            async for chunk in resp.aiter_bytes():
                full.extend(chunk)

    frames = parse_frames(bytes(full))
    print(f"  Response: {len(full)}B, {len(frames)} frames")
    print()
    for i, f in enumerate(frames):
        print_frame(i, f["raw"])
    print()


async def main():
    token = get_token()
    if not token:
        print("No token"); return
    print(f"Token: {token[:30]}... ({len(token)} chars)")
    print(f"Model: {MODEL}")

    prompt = "List the files in /tmp directory."

    print("\n\n" + "#"*60)
    print("# TEST A1: MCP tools_only (field 34 only)")
    print(f"# supported_tools=[19,49], mcp_tools with {len(TOOLS)} tools")
    print("#"*60)
    await send_request("A1: MCP tools_only", build_test_a(prompt, "tools_only"), token)

    print("\n\n" + "#"*60)
    print("# TEST A2: MCP full + has_mcp_descriptors=true (field 90)")
    print(f"# supported_tools=[19,49], mcp_tools + has_mcp_descriptors")
    print("#"*60)
    await send_request("A2: MCP full", build_test_a(prompt, "full"), token)

    print("\n\n" + "#"*60)
    print("# TEST A3: MCP tools + system prompt with instructions")
    print(f"# supported_tools=[19,49], mcp_tools + sys msg instructions")
    print("#"*60)
    await send_request("A3: MCP + prompt", build_test_a(prompt, "prompt+mcp"), token)

    print("\n\n" + "#"*60)
    print("# TEST A4: MCP tools + ALL native tools")
    print(f"# supported_tools=[5..49], mcp_tools with {len(TOOLS)} tools")
    print("#"*60)
    await send_request("A4: MCP + native", build_test_a(prompt, "tools+native"), token)

    print("\n\n" + "#"*60)
    print("# TEST B: Prompt injection (zero tools)")
    print(f"# supported_tools=[] (empty), tool defs in user message")
    print("#"*60)
    await send_request("Test B: Prompt injection", build_test_b(prompt), token)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
