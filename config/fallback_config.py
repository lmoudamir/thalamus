from __future__ import annotations
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
    # --- Tier 1: top-tier ---
    'gemini-3.1-pro': [
        'gemini-3-pro', 'claude-4.5-sonnet', 'gpt-5.3-codex-spark-preview-high',
        'claude-4-sonnet', 'claude-4.5-haiku', 'gemini-3-flash',
        'grok-code-fast-1', 'composer-1.5', 'default',
    ],
    'gemini-3-pro': [
        'claude-4.5-sonnet', 'gpt-5.3-codex-spark-preview-high',
        'claude-4-sonnet', 'claude-4.5-haiku', 'gemini-3-flash',
        'grok-code-fast-1', 'composer-1.5', 'default',
    ],
    'claude-4.5-sonnet-thinking': [
        'claude-4.5-sonnet', 'gemini-3.1-pro', 'gemini-3-pro',
        'gpt-5.3-codex-spark-preview-high', 'claude-4-sonnet',
        'claude-4.5-haiku', 'gemini-3-flash', 'composer-1.5', 'default',
    ],
    'claude-4.5-sonnet': [
        'gemini-3.1-pro', 'gemini-3-pro', 'gpt-5.3-codex-spark-preview-high',
        'claude-4-sonnet', 'claude-4.5-haiku', 'gemini-3-flash',
        'grok-code-fast-1', 'composer-1.5', 'default',
    ],
    'claude-4.5-opus-high': [
        'claude-4.5-sonnet', 'gemini-3.1-pro',
        'gpt-5.3-codex-spark-preview-high', 'claude-4-sonnet',
        'claude-4.5-haiku', 'gemini-3-flash', 'composer-1.5', 'default',
    ],

    # --- Tier 2: strong coding + fast ---
    'gpt-5.3-codex-spark-preview-xhigh': [
        'gpt-5.3-codex-spark-preview-high', 'gpt-5.3-codex-spark-preview',
        'claude-4.5-sonnet', 'claude-4-sonnet', 'claude-4.5-haiku',
        'gemini-3-flash', 'composer-1.5', 'default',
    ],
    'gpt-5.3-codex-spark-preview-high': [
        'gpt-5.3-codex-spark-preview', 'claude-4.5-sonnet',
        'claude-4-sonnet', 'claude-4.5-haiku', 'gemini-3-flash',
        'grok-code-fast-1', 'composer-1.5', 'default',
    ],
    'gpt-5.3-codex-spark-preview': [
        'gpt-5.3-codex-spark-preview-high', 'claude-4-sonnet',
        'claude-4.5-haiku', 'gemini-3-flash', 'grok-code-fast-1',
        'composer-1.5', 'default',
    ],
    'claude-4-sonnet-thinking': [
        'claude-4-sonnet', 'claude-4.5-haiku', 'kimi-k2.5',
        'gemini-3-flash', 'grok-code-fast-1', 'composer-1.5', 'default',
    ],
    'claude-4-sonnet': [
        'kimi-k2.5', 'claude-4.5-haiku', 'gpt-5.1-codex-mini-high',
        'gemini-3-flash', 'grok-code-fast-1', 'composer-1.5', 'default',
    ],

    # --- Tier 3: mid-performance ---
    'kimi-k2.5': [
        'gpt-5.1-codex-mini-high', 'gpt-5.1-codex-mini',
        'claude-4.5-haiku', 'gemini-3-flash', 'grok-code-fast-1',
        'gemini-2.5-flash', 'composer-1.5', 'default',
    ],
    'gpt-5.1-codex-mini-high': [
        'gpt-5.1-codex-mini', 'claude-4.5-haiku', 'gemini-3-flash',
        'grok-code-fast-1', 'gemini-2.5-flash', 'composer-1.5', 'default',
    ],
    'gpt-5.1-codex-mini': [
        'claude-4.5-haiku', 'gemini-3-flash', 'grok-code-fast-1',
        'gemini-2.5-flash', 'gpt-5-mini', 'composer-1.5', 'default',
    ],
    'claude-4.5-haiku-thinking': [
        'claude-4.5-haiku', 'gemini-3-flash', 'grok-code-fast-1',
        'gemini-2.5-flash', 'gpt-5-mini', 'composer-1.5', 'default',
    ],
    'claude-4.5-haiku': [
        'gemini-3-flash', 'grok-code-fast-1', 'gemini-2.5-flash',
        'gpt-5-mini', 'gpt-5.1-codex-mini-low', 'composer-1.5', 'default',
    ],

    # --- Tier 4: fast & lightweight ---
    'gemini-3-flash': [
        'grok-code-fast-1', 'gemini-2.5-flash', 'claude-4.5-haiku',
        'gpt-5-mini', 'gpt-5.1-codex-mini-low', 'composer-1.5', 'default',
    ],
    'grok-code-fast-1': [
        'gemini-3-flash', 'gemini-2.5-flash', 'gpt-5-mini',
        'gpt-5.3-codex-spark-preview-low', 'composer-1.5', 'default',
    ],
    'gemini-2.5-flash': [
        'gemini-3-flash', 'grok-code-fast-1', 'gpt-5-mini',
        'gpt-5.3-codex-spark-preview-low', 'composer-1.5', 'default',
    ],
    'gpt-5-mini': [
        'gemini-3-flash', 'grok-code-fast-1', 'gemini-2.5-flash',
        'gpt-5.3-codex-spark-preview-low', 'gpt-5.1-codex-mini-low',
        'composer-1.5', 'default',
    ],

    # --- Fallback: last resort ---
    'gpt-5.3-codex-spark-preview-low': [
        'gpt-5.1-codex-mini-low', 'composer-1.5', 'default',
    ],
    'gpt-5.1-codex-mini-low': [
        'composer-1.5', 'default',
    ],
    'composer-1.5': ['default'],
    'default': [],

    # --- fast virtual model: speed-optimized chain ---
    # Direct Cursor API benchmark (bypassing Thalamus fallback):
    #   1.03s cursor-small       | 1.06s spark-preview-low  | 1.14s composer-1.5
    #   1.15s spark-preview-xhigh| 1.61s gpt-4o-mini        | 1.64s gemini-2.5-flash
    #   1.71s spark-preview      | 1.81s grok-code-fast-1   | 4.25s grok-3-mini
    # Excluded: gpt-5.2-fast/5.4-medium-fast (usage cap), claude/deepseek (invalid),
    #           o3-mini/o4-mini/gpt-4o (20s+), grok-3/gemini-3-flash/claude-4.x (90s+)
    'fast': [
        'gpt-5.3-codex-spark-preview-low',
        'composer-1.5',
        'gpt-5.3-codex-spark-preview-xhigh',
        'gpt-4o-mini',
        'gemini-2.5-flash',
        'gpt-5.3-codex-spark-preview',
        'grok-code-fast-1',
        'grok-3-mini',
        'gpt-5-mini',
    ],

    # --- thalamus virtual model: full 22-stop chain ---
    'thalamus': [
        'gemini-3.1-pro', 'gemini-3-pro', 'claude-4.5-sonnet-thinking',
        'claude-4.5-sonnet', 'gpt-5.3-codex-spark-preview-xhigh',
        'gpt-5.3-codex-spark-preview-high', 'gpt-5.3-codex-spark-preview',
        'claude-4-sonnet-thinking', 'claude-4-sonnet', 'kimi-k2.5',
        'gpt-5.1-codex-mini-high', 'gpt-5.1-codex-mini',
        'claude-4.5-haiku-thinking', 'claude-4.5-haiku',
        'gemini-3-flash', 'grok-code-fast-1', 'gemini-2.5-flash',
        'gpt-5-mini', 'gpt-5.3-codex-spark-preview-low',
        'gpt-5.1-codex-mini-low', 'composer-1.5', 'default',
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
