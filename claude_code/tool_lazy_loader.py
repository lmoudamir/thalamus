"""Tool utilities — task_complete detection and continuation constants."""

from __future__ import annotations

import json
from typing import Any

TASK_COMPLETE_SCHEMA: dict[str, Any] = {
    "name": "task_complete",
    "description": "Signal that the current task is complete. Provide a summary of what was accomplished.",
    "input_schema": {
        "type": "object",
        "properties": {
            "result": {
                "type": "string",
                "description": "Summary of completed work",
            }
        },
        "required": ["result"],
        "additionalProperties": False,
    },
}

MAX_CONTINUATION_RETRIES = 2

CONTINUATION_PROMPT = (
    "You described what you plan to do but did not execute it. "
    'Now output tool_use JSON: {"type":"tool_use","id":"toolu_<id>","name":"<ToolName>","input":{...}} '
    "If the task is fully complete, call task_complete."
)


def is_task_complete_call(tool_call: dict) -> bool:
    """Check if a tool call is a valid task_complete call (has result param)."""
    fn = tool_call.get("function", {})
    if fn.get("name") != "task_complete":
        return False
    raw_args = fn.get("arguments", "{}")
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args)
        except (json.JSONDecodeError, ValueError):
            return False
    else:
        args = raw_args
    return isinstance(args, dict) and bool(args.get("result"))


def extract_task_complete_result(tool_call: dict) -> str:
    """Extract the result string from a task_complete call."""
    fn = tool_call.get("function", {})
    raw_args = fn.get("arguments", "{}")
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args)
        except (json.JSONDecodeError, ValueError):
            return ""
    else:
        args = raw_args
    return str(args.get("result", "")) if isinstance(args, dict) else ""
