"""
Bearer token extraction and Cursor JWT conversion.

Cursor session tokens come in two formats:
  - "user_xxx::eyJ..." (from PKCE browser login, with userId prefix)
  - "eyJ..."           (raw JWT, from IDE internal storage)

The Cursor API only accepts the raw JWT part, so we strip the prefix.
Clients may also pass multiple comma-separated tokens for load-distribution.
"""

import logging
import re
from urllib.parse import unquote

logger = logging.getLogger('thalamus.bearer-token')


def extract_bearer_tokens(authorization_header: str | None) -> list[str]:
    if not authorization_header:
        return []

    m = re.match(r'^Bearer\s+(.+)$', authorization_header, re.IGNORECASE)
    if not m:
        return []

    tokens = []
    for part in m.group(1).split(','):
        part = part.strip()
        if not part:
            continue
        try:
            part = unquote(part)
        except Exception:
            pass
        part = re.sub(r'%3A%3A', '::', part, flags=re.IGNORECASE)
        tokens.append(part)

    return tokens


def strip_cursor_user_prefix(token: str | None) -> str:
    if not token:
        return token or ''
    if '::' in token:
        return token.split('::', 1)[1]
    return token
