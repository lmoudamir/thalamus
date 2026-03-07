"""
Experiment: Agent RPC (agent.v1.AgentService/Run)

This uses the NEW Agent RPC endpoint instead of the Chat RPC.
Key advantage: AgentRunRequest has custom_system_prompt (field 8).

Proto structure:
  AgentClientMessage {
    oneof message {
      AgentRunRequest run_request = 1;
      ...
    }
  }

  AgentRunRequest {
    ConversationStateStructure conversation_state = 1;
    ConversationAction action = 2;
    ModelDetails model_details = 3;
    McpTools mcp_tools = 4;
    optional string conversation_id = 5;
    optional McpFileSystemOptions mcp_file_system_options = 6;
    optional SkillOptions skill_options = 7;
    optional string custom_system_prompt = 8;
    optional RequestedModel requested_model = 9;
    optional bool suggest_next_prompt = 10;
    optional string subagent_type_name = 11;
  }

  ConversationAction {
    oneof action {
      UserMessageAction user_message_action = 1;
      ...
    }
  }

  UserMessageAction {
    UserMessage user_message = 1;
    RequestContext request_context = 2;
    optional bool send_to_interaction_listener = 3;
    repeated UserMessage prepend_user_messages = 4;
  }

  UserMessage {
    string text = 1;
    string message_id = 2;
    optional SelectedContext selected_context = 3;
    Mode mode = 4;  // enum
    ...
  }

  ModelDetails {
    string model_id = 1;
    string display_model_id = 3;
    string display_name = 4;
    ...
  }

  AgentServerMessage {
    oneof message {
      InteractionUpdate interaction_update = 1;
      ExecServerMessage exec_server_message = 2;
      ...
    }
  }

  InteractionUpdate {
    oneof message {
      TextDelta text_delta = 1;      (text)
      ToolCallStarted tool_call_started = 2;
      ToolCallCompleted tool_call_completed = 3;
      ThinkingDelta thinking_delta = 4;
      ...
    }
  }
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import ssl as _ssl
import struct
import time
from pathlib import Path
from uuid import uuid4

import httpx
import httpcore
from dotenv import load_dotenv
from google.protobuf import struct_pb2

_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)

from core.token_manager import get_cursor_access_token
from core.bearer_token import strip_cursor_user_prefix

CURSOR_CLOUDFLARE_IP = os.environ.get("CURSOR_CLOUDFLARE_IP", "104.18.19.125")
CURSOR_API_HOST = "https://api2.cursor.sh"
CURSOR_CLIENT_VERSION = "2.5.25"
MODEL = "claude-4.5-sonnet"
MCP_SERVER_ID = "claude-tools"

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


# ── auth ──

def get_token() -> str:
    return strip_cursor_user_prefix(get_cursor_access_token())

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


# ── tool definitions ──

TOOLS = [
    {
        "name": "Bash",
        "description": "Execute a bash command. Returns stdout, stderr and exit code.",
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
        "description": "Read the contents of a file at the given path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path of the file"},
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

CUSTOM_SYSTEM_PROMPT = """You are a coding assistant with access to tools.

When you need to perform an action, you MUST output a tool call in this exact JSON format on a single line:
{"tool_call": {"name": "<tool_name>", "arguments": {<args>}}}

Available tools:
""" + json.dumps([{"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]} for t in TOOLS], indent=2)


def build_mcp_tool_def(t: dict) -> bytes:
    msg = ps(1, t["name"])
    msg += ps(2, t["description"])
    msg += pb(3, struct_pb(t["input_schema"]))
    msg += ps(4, MCP_SERVER_ID)
    msg += ps(5, t["name"])
    return msg


def build_mcp_tools() -> bytes:
    msg = b""
    for t in TOOLS:
        msg += pm(1, build_mcp_tool_def(t))
    return msg


# ── request builder ──

def build_agent_request(prompt: str, with_custom_sp: bool = True, with_mcp: bool = True) -> bytes:
    """Build AgentClientMessage wrapping AgentRunRequest."""
    msg_id = str(uuid4())
    conv_id = str(uuid4())

    # UserMessage: text=1, message_id=2, mode=4 (enum, 0=UNSPECIFIED)
    user_msg = ps(1, prompt) + ps(2, msg_id)

    # UserMessageAction: user_message=1
    user_msg_action = pm(1, user_msg)

    # ConversationAction: user_message_action=1
    conv_action = pm(1, user_msg_action)

    # ModelDetails: model_id=1
    model_details = ps(1, MODEL)

    # AgentRunRequest
    run_req = b""
    # conversation_state=1: ConversationStateStructure (required, even if empty)
    run_req += pm(1, b"")
    # action=2
    run_req += pm(2, conv_action)
    # model_details=3
    run_req += pm(3, model_details)
    # mcp_tools=4
    if with_mcp:
        run_req += pm(4, build_mcp_tools())
    # conversation_id=5
    run_req += ps(5, conv_id)
    # custom_system_prompt=8
    if with_custom_sp:
        run_req += ps(8, CUSTOM_SYSTEM_PROMPT)

    # AgentClientMessage: run_request=1
    client_msg = pm(1, run_req)

    payload = client_msg
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
    printable = ''.join(c if c.isprintable() or c in '\n\t' else f'[{ord(c):02x}]' for c in txt)

    is_json_error = raw[:1] == b'{' and b'"error"' in raw[:50]
    has_tool_sig = (b'tool' in raw.lower() or b'call_mcp' in raw.lower() or b'toolu_' in raw)
    has_json_tool = b'"tool_call"' in raw or b'"name"' in raw

    if is_json_error:
        try:
            err = json.loads(raw)
            detail = err.get("error", {}).get("details", [{}])[0].get("debug", {}).get("details", {}).get("detail", "")
            msg = err.get("error", {}).get("message", "")
            print(f"  Frame {i} [ERROR]: {detail or msg or raw[:200].decode()}")
        except:
            print(f"  Frame {i} [ERROR]: {printable[:300]}")
    elif has_json_tool:
        print(f"  Frame {i} [JSON TOOL] ({len(raw)}B):")
        print(f"    {printable[:500]}")
    elif has_tool_sig:
        print(f"  Frame {i} [TOOL?] ({len(raw)}B):")
        print(f"    hex: {raw[:150].hex()}")
        print(f"    txt: {printable[:400]}")
    elif len(raw) > 3:
        clean = ''.join(c if c.isprintable() else '' for c in txt[:400]).strip()
        if clean:
            print(f"  Frame {i}: {clean[:300]}")
        else:
            print(f"  Frame {i}: ({len(raw)}B hex) {raw[:80].hex()}")


def build_bidi_envelope(request_id: str, agent_client_msg_bytes: bytes) -> bytes:
    """For RunPoll: wrap AgentClientMessage in a BidiPollRequest-like format.
    Actually for BiDi connect-rpc, we send the message as a stream frame
    then read responses. We'll try sending the AgentClientMessage directly.
    """
    return agent_client_msg_bytes


async def send_request(label: str, body: bytes, token: str, endpoint: str, timeout_s: int = 30):
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
    print(f"  Endpoint: {endpoint}")
    print(f"  Body: {len(body)}B, magic=0x{body[0]:02x}")
    print(f"{'='*60}")

    full = bytearray()
    import asyncio
    async with make_client(timeout=httpx.Timeout(timeout_s, connect=15)) as client:
        try:
            async with client.stream("POST",
                f"{CURSOR_API_HOST}/{endpoint}",
                headers=headers, content=body) as resp:
                print(f"  HTTP {resp.status_code}")
                if resp.status_code != 200:
                    err = await resp.aread()
                    print(f"  Error: {err[:500]}")
                    return
                try:
                    read_deadline = asyncio.get_event_loop().time() + timeout_s
                    async for chunk in resp.aiter_bytes():
                        full.extend(chunk)
                        if len(full) > 100_000:
                            break
                        if asyncio.get_event_loop().time() > read_deadline:
                            print(f"  Read deadline reached, collected {len(full)}B")
                            break
                except Exception as e:
                    print(f"  Stream read exception: {e}")
        except httpx.ReadTimeout:
            print(f"  Read timeout after {timeout_s}s")
        except Exception as e:
            print(f"  Request error: {e}")

    if not full:
        print("  No response data received")
        return

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

    agent_endpoint = "agent.v1.AgentService/Run"

    # Test 1: minimal - no custom SP, no MCP
    print("\n" + "#"*60)
    print("# TEST 1: Agent RPC minimal (no SP, no MCP)")
    print("#"*60)
    body1 = build_agent_request(prompt, with_custom_sp=False, with_mcp=False)
    await send_request("Agent minimal", body1, token, agent_endpoint, timeout_s=30)

    # Test 2: with custom_system_prompt
    print("\n" + "#"*60)
    print("# TEST 2: Agent RPC with custom_system_prompt")
    print("#"*60)
    body2 = build_agent_request(prompt, with_custom_sp=True, with_mcp=False)
    await send_request("Agent + SP", body2, token, agent_endpoint, timeout_s=30)

    # Test 3: with custom_system_prompt + mcp_tools
    print("\n" + "#"*60)
    print("# TEST 3: Agent RPC full (SP + MCP)")
    print("#"*60)
    body3 = build_agent_request(prompt, with_custom_sp=True, with_mcp=True)
    await send_request("Agent + SP + MCP", body3, token, agent_endpoint, timeout_s=30)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
