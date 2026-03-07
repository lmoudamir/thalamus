"""
Probe which GPT-5.3/Codex Spark models are available via Cursor API.
Sends a minimal "hello" request to each model variant and checks the response.
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

_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)

from core.token_manager import get_cursor_access_token
from core.bearer_token import strip_cursor_user_prefix

CURSOR_CLOUDFLARE_IP = os.environ.get("CURSOR_CLOUDFLARE_IP", "104.18.19.125")
CURSOR_API_HOST = "https://api2.cursor.sh"
CURSOR_CLIENT_VERSION = "2.5.25"


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


def build_hello(model: str) -> bytes:
    msg_id = str(uuid4())
    conv_id = str(uuid4())

    req = b""
    user_msg = ps(1, "Say hi in 5 words or less.") + pi(2, 1) + ps(13, msg_id) + pi(47, 2)
    req += pm(1, user_msg)

    req += pi(2, 1)
    req += pm(3, ps(1, ""))
    req += pi(4, 1)
    req += pm(5, ps(1, model) + pb(4, b""))
    req += ps(8, "")
    req += pi(13, 1)
    req += pm(15, ps(1, "cursor\\aisettings") + pb(3, b"") +
            pm(6, pb(1, b"") + pb(2, b"")) + pi(8, 1) + pi(9, 1))
    req += pi(19, 1)
    req += ps(23, conv_id)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    req += pm(26, ps(1, "darwin") + ps(2, "arm64") + ps(3, "24.0.0") +
            ps(4, "/bin/zsh") + ps(5, ts))
    req += pi(27, 1)

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


def extract_text(data: bytes) -> str:
    parts = []
    idx = 0
    while idx < len(data):
        if idx >= len(data): break
        byte = data[idx]
        wire_type = byte & 0x07
        if wire_type == 0:
            idx += 1
            while idx < len(data) and data[idx] & 0x80: idx += 1
            idx += 1
        elif wire_type == 2:
            idx += 1
            length = 0; shift = 0
            while idx < len(data) and data[idx] & 0x80:
                length |= (data[idx] & 0x7F) << shift; shift += 7; idx += 1
            if idx < len(data):
                length |= (data[idx] & 0x7F) << shift; idx += 1
            chunk = data[idx:idx+length]; idx += length
            try:
                text = chunk.decode("utf-8")
                if text.isprintable() or any(c in text for c in '\n\t'):
                    clean = text.strip()
                    if 0 < len(clean) < 200 and not clean.startswith('{'):
                        parts.append(text)
                    else:
                        sub = extract_text(chunk)
                        if sub: parts.append(sub)
                else:
                    sub = extract_text(chunk)
                    if sub: parts.append(sub)
            except UnicodeDecodeError:
                sub = extract_text(chunk)
                if sub: parts.append(sub)
        else:
            idx += 1
    return ''.join(parts)


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


async def probe_model(model: str, token: str) -> str:
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
    body = build_hello(model)
    if body[0] == 0x01:
        headers["connect-content-encoding"] = "gzip"

    full = bytearray()
    try:
        async with make_client(timeout=httpx.Timeout(120, connect=15, read=120)) as client:
            async with client.stream("POST",
                f"{CURSOR_API_HOST}/aiserver.v1.ChatService/StreamUnifiedChatWithTools",
                headers=headers, content=body) as resp:
                if resp.status_code != 200:
                    return f"HTTP {resp.status_code}"
                async for chunk in resp.aiter_bytes():
                    full.extend(chunk)
                    if len(full) > 10_000:
                        break
    except Exception as e:
        if len(full) == 0:
            return f"ERROR: {type(e).__name__}: {e}"

    frames = parse_frames(bytes(full))
    for f in frames:
        raw = f["raw"]
        if b'"error"' in raw[:100]:
            try:
                err = json.loads(raw)
                code = err.get("error", {}).get("code", "?")
                msg = err.get("error", {}).get("message", "?")
                debug = err.get("error", {}).get("details", [{}])[0].get("debug", {})
                detail = debug.get("error", "") or debug.get("details", {}).get("detail", "")
                return f"ERR [{code}]: {detail or msg}"
            except:
                return f"ERR: {raw[:200].decode('utf-8', errors='replace')}"

    text_parts = []
    for f in frames:
        raw = f["raw"]
        if b'"error"' in raw[:100]: continue
        t = extract_text(raw)
        if t: text_parts.append(t)
    text = ''.join(text_parts).strip()
    if text:
        return f"OK: {text[:120]}"
    return f"OK (no text, {len(full)}B, {len(frames)} frames)"


async def main():
    token = get_token()
    if not token:
        print("No token"); return

    models = [
        "gpt-5.3-codex-spark-preview",
        "gpt-5.3-codex-spark-preview-high",
        "gpt-5.3-codex-spark-preview-xhigh",
        "gpt-5.3-codex-spark-preview-low",
        "gpt-5.3-codex-spark",
        "o3",
        "o3-mini",
        "o4-mini",
        "gpt-4o",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4.1-nano",
    ]

    print(f"Probing {len(models)} models...\n")
    print(f"{'Model':<45} {'Result'}")
    print("-" * 90)

    for model in models:
        result = await probe_model(model, token)
        print(f"{model:<45} {result}")

    print("\nDone.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
