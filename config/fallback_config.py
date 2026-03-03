"""
Claude Code model fallback configuration.

Keeps fallback behavior short and predictable for Claude Code traffic,
instead of using the broad universal chain.
"""

import os
import re
from dataclasses import dataclass, field


@dataclass
class FallbackConfig:
    enabled: bool = True
    max_attempts: int = 5
    first_token_timeout_ms: int = 10000
    first_token_timeout_enabled: bool = True

    error_patterns: list[re.Pattern] = field(default_factory=list)

    fallback_chains: dict[str, list[str]] = field(default_factory=dict)

    def should_fallback(self, error_text: str) -> bool:
        if not error_text:
            return False
        return any(p.search(error_text) for p in self.error_patterns)

    def select_next_model(
        self,
        requested: str,
        tried: set[str] | list[str],
        cooldown_set: set[str] | None = None,
    ) -> str | None:
        if not self.enabled:
            return None

        tried_set = set(tried)
        cooldown = cooldown_set or set()

        chain = self.fallback_chains.get(requested, self.fallback_chains.get('default', []))

        for candidate in chain:
            if candidate not in tried_set and candidate not in cooldown:
                return candidate

        return None


_DEFAULT_ERROR_PATTERNS = [
    re.compile(r'rate.*limit', re.IGNORECASE),
    re.compile(r'too.*many.*requests', re.IGNORECASE),
    re.compile(r'\b429\b', re.IGNORECASE),
    re.compile(r'quota.*exceeded', re.IGNORECASE),
    re.compile(r'usage.*cap', re.IGNORECASE),
    re.compile(r'resource_exhausted', re.IGNORECASE),
    re.compile(r'service.*unavailable', re.IGNORECASE),
    re.compile(r'\b503\b', re.IGNORECASE),
    re.compile(r'internal.*server.*error', re.IGNORECASE),
    re.compile(r'\b500\b', re.IGNORECASE),
    re.compile(r'trouble connecting', re.IGNORECASE),
    re.compile(r'connection.*(failed|error)', re.IGNORECASE),
    re.compile(r'ECONNREFUSED|ECONNRESET|ETIMEDOUT', re.IGNORECASE),
    re.compile(r'First token timeout', re.IGNORECASE),
    re.compile(r'\btimed?\s*out\b', re.IGNORECASE),
    re.compile(r'\brequest.*timeout\b', re.IGNORECASE),
    re.compile(r'model.*not.*(available|found|valid)', re.IGNORECASE),
]

_DEFAULT_FALLBACK_CHAINS = {
    'gpt-5.3-codex-spark-preview': [
        'gpt-5.3-codex-spark-preview-high',
        'gpt-5.3-codex-spark-preview-low',
        'claude-4.5-haiku',
        'gemini-3-flash',
        'default',
    ],
    'gpt-5.3-codex-spark-preview-high': [
        'gpt-5.3-codex-spark-preview',
        'gpt-5.3-codex-spark-preview-low',
        'claude-4.5-haiku',
        'gemini-3-flash',
        'default',
    ],
    'gpt-5.3-codex-spark-preview-low': [
        'gpt-5.3-codex-spark-preview',
        'claude-4.5-haiku',
        'gemini-3-flash',
        'default',
    ],
    'claude-4.5-sonnet': [
        'claude-4.5-haiku',
        'gpt-5.3-codex-spark-preview',
        'gemini-3-flash',
        'default',
    ],
    'claude-4.5-opus-high': [
        'claude-4.5-sonnet',
        'claude-4.5-haiku',
        'gpt-5.3-codex-spark-preview',
        'default',
    ],
    'claude-4.5-haiku': [
        'gpt-5.3-codex-spark-preview',
        'gemini-3-flash',
        'default',
    ],
    'gemini-3.1-pro': [
        'claude-4.5-haiku',
        'gpt-5.3-codex-spark-preview',
        'gemini-3-flash',
        'default',
    ],
    'gemini-3-flash': [
        'claude-4.5-haiku',
        'gpt-5.3-codex-spark-preview',
        'default',
    ],
    'default': [
        'gpt-5.3-codex-spark-preview',
        'claude-4.5-haiku',
        'gemini-3-flash',
        'default',
    ],
}


def load_fallback_config() -> FallbackConfig:
    return FallbackConfig(
        enabled=os.environ.get('CLAUDE_CODE_MODEL_FALLBACK_ENABLED', 'true').lower() != 'false',
        max_attempts=int(os.environ.get('CLAUDE_CODE_MAX_MODEL_ATTEMPTS', '5')),
        first_token_timeout_ms=int(os.environ.get('CLAUDE_CODE_FIRST_TOKEN_TIMEOUT_MS', '10000')),
        first_token_timeout_enabled=os.environ.get('CLAUDE_CODE_FIRST_TOKEN_TIMEOUT_ENABLED', 'true').lower() != 'false',
        error_patterns=list(_DEFAULT_ERROR_PATTERNS),
        fallback_chains=dict(_DEFAULT_FALLBACK_CHAINS),
    )
