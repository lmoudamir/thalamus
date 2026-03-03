"""
HTTP/2 client for Cursor API (api2.cursor.sh).

Connects to the Cloudflare IP while preserving correct TLS SNI (api2.cursor.sh).
"""

from __future__ import annotations

import logging
import os
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import httpcore

logger = logging.getLogger(__name__)

CURSOR_CLOUDFLARE_IP: str = os.environ.get("CURSOR_CLOUDFLARE_IP", "104.18.19.125")
CURSOR_API_HOST: str = "api2.cursor.sh"

_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def _build_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.set_alpn_protocols(["h2"])
    return ctx


class _CloudflareOverrideBackend(httpcore.AsyncNetworkBackend):
    """Redirects TCP connections for api2.cursor.sh to the Cloudflare IP
    while keeping the original hostname for TLS SNI."""

    def __init__(self) -> None:
        from httpcore._backends.auto import AutoBackend
        self._inner = AutoBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: object | None = None,
    ) -> httpcore.AsyncNetworkStream:
        target = CURSOR_CLOUDFLARE_IP if host == CURSOR_API_HOST else host
        if target != host:
            logger.debug("DNS override: %s -> %s:%d", host, target, port)
        return await self._inner.connect_tcp(
            target, port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self, path: str, timeout: float | None = None, socket_options: object | None = None,
    ) -> httpcore.AsyncNetworkStream:
        return await self._inner.connect_unix_socket(path, timeout=timeout, socket_options=socket_options)

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def _build_client() -> httpx.AsyncClient:
    """Build an httpx AsyncClient that routes api2.cursor.sh to the Cloudflare IP.

    The URL host stays as api2.cursor.sh so httpx/httpcore use it for TLS SNI.
    The custom network backend intercepts the TCP connect and redirects to the IP.
    """
    ssl_ctx = _build_ssl_context()
    backend = _CloudflareOverrideBackend()

    pool = httpcore.AsyncConnectionPool(
        ssl_context=ssl_ctx,
        http2=True,
        max_connections=10,
        max_keepalive_connections=5,
        network_backend=backend,
    )

    transport = httpx.AsyncHTTPTransport(http2=True, verify=ssl_ctx)
    transport._pool = pool  # noqa: SLF001

    return httpx.AsyncClient(
        transport=transport,
        base_url=f"https://{CURSOR_API_HOST}",
        timeout=_TIMEOUT,
    )


@asynccontextmanager
async def open_streaming_h2_request(
    path: str,
    headers: dict[str, str],
    body: bytes,
) -> AsyncIterator[AsyncIterator[bytes]]:
    """Open a server-streaming HTTP/2 POST to api2.cursor.sh."""
    client = _build_client()
    try:
        async with client.stream(
            "POST", path, headers=headers, content=body,
        ) as response:
            logger.debug(
                "Streaming response started: status=%d path=%s",
                response.status_code, path,
            )
            yield response.aiter_bytes()
    finally:
        await client.aclose()


async def send_unary_h2_request(
    path: str,
    headers: dict[str, str],
    body: bytes,
) -> dict:
    """Send a unary (non-streaming) HTTP/2 POST and return the full response."""
    async with _build_client() as client:
        response = await client.post(path, headers=headers, content=body)
        logger.debug(
            "Unary response: status=%d path=%s size=%d",
            response.status_code, path, len(response.content),
        )
        return {"status": response.status_code, "buffer": response.content}
