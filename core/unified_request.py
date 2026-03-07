from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UnifiedRequest:
    """Internal representation for all API requests flowing through the pipeline.

    Produced by normalize_anthropic() or normalize_openai(), consumed by
    run_pipeline().  The pipeline never inspects original_format except to
    choose the output SSE assembler.
    """

    # --- core fields used by the pipeline ---
    messages: list[dict[str, Any]]
    system: str
    tools: list[dict[str, Any]]
    model: str
    stream: bool
    max_tokens: int | None = None

    # --- routing / output ---
    original_format: str = "anthropic"
    original_model: str = ""
    original_tools: list[dict[str, Any]] = field(default_factory=list)

    # --- CC pass-through fields (never silently dropped) ---
    metadata: dict[str, Any] | None = None
    thinking: dict[str, Any] | None = None
    context_management: dict[str, Any] | None = None
    tool_choice: dict[str, Any] | str | None = None
