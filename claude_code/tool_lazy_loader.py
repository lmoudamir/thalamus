"""
Lazy Tool Loading Protocol (LTLP) — dynamic stub generation and schema-on-demand.

Fully dynamic: works with ANY tools[] passed by ANY client (DA, CC, MCP, etc.).
No tool names, counts, or types are hardcoded.

Flow:
  1. Client sends tools[] → build_stub_prompt() generates one-line stubs
  2. build_schema_store() stores full schemas keyed by name (request-scoped)
  3. LLM outputs a tool call → is_stub_call() checks if required params are missing
  4. If stub call → format_schema_for_loading() returns full schema as tool_result
  5. LLM retries with correct params → pass through as real call
  6. Few-shot: schema stays in conversation context for future calls
"""

from __future__ import annotations

import json
from typing import Any

from utils.structured_logging import ThalamusStructuredLogger

logger = ThalamusStructuredLogger.get_logger("tool-lazy-loader", "DEBUG")

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

STUB_PROMPT_HEADER = (
    '## Tools (call via JSON: {"tool_calls": [{"function": {"name": "NAME", "arguments": {...}}}]})\n'
    'When done: {"tool_calls": [{"function": {"name": "task_complete", "arguments": {"result": "summary"}}}]}\n'
)

MAX_CONTINUATION_RETRIES = 2

CONTINUATION_PROMPT = (
    "You described what you plan to do but did not execute it. "
    "Now output the tool_calls JSON to perform the action. "
    "If the task is fully complete, call task_complete."
)


def _extract_fn(tool_def: dict) -> dict:
    """Extract the function-level dict from either OpenAI or Anthropic format."""
    return tool_def.get("function") or tool_def


def _first_sentence(text: str) -> str:
    """Extract the first meaningful sentence from a description."""
    if not text:
        return ""
    line = text.split("\n")[0].strip()
    for sep in (". ", ".\n", "。"):
        idx = line.find(sep)
        if idx > 0:
            return line[: idx + 1] if sep != "。" else line[: idx + 1]
    if len(line) > 120:
        return line[:117] + "..."
    return line


def generate_stub(tool_def: dict) -> str:
    """Generate a one-line stub from any tool definition. Fully generic."""
    fn = _extract_fn(tool_def)
    name = fn.get("name", "")
    desc = fn.get("description", "")
    short = _first_sentence(desc)
    return f"- {name}: {short}" if short else f"- {name}"


def build_stub_prompt(tools: list[dict]) -> str:
    """Dynamically generate stub prompt from tools[]. Input N tools → output N+1 lines (+ task_complete)."""
    stubs = [generate_stub(t) for t in tools]
    stubs.append(f"- task_complete: {_first_sentence(TASK_COMPLETE_SCHEMA['description'])}")
    return STUB_PROMPT_HEADER + "\n".join(stubs)


STUB_REMINDER_INTERVAL = 15

def build_stub_reminder(tools: list[dict]) -> str:
    """Ultra-compact periodic reminder derived dynamically from tools[].

    Injected every STUB_REMINDER_INTERVAL turns to keep tool-calling
    protocol fresh in the LLM's attention window.  ~20 tokens + 1 per tool.
    """
    names = [_extract_fn(t).get("name", "") for t in tools if _extract_fn(t).get("name")]
    names.append("task_complete")
    return (
        f'[TOOL_REMINDER] {len(names)} tools: {", ".join(names)}. '
        'Use {"tool_calls":[{"function":{"name":"NAME","arguments":{...}}}]} to call them.'
    )


def build_schema_store(tools: list[dict]) -> dict[str, dict]:
    """Build name → full_schema mapping from tools[]. Request-scoped, not cached."""
    store: dict[str, dict] = {}
    for tool_def in tools:
        fn = _extract_fn(tool_def)
        name = fn.get("name", "")
        if name:
            store[name] = fn
    store[TASK_COMPLETE_SCHEMA["name"]] = TASK_COMPLETE_SCHEMA
    return store


def _get_params_schema(full_schema: dict) -> dict:
    """Get the parameters/input_schema dict, handling both OpenAI and Anthropic formats."""
    return (
        full_schema.get("input_schema")
        or full_schema.get("parameters")
        or {}
    )


def is_stub_call(tool_name: str, arguments: dict | str, schema_store: dict) -> bool:
    """Check if a tool call is missing required params (needs schema loading).

    Works for ANY tool — reads required params from the tool's own schema.
    """
    full_schema = schema_store.get(tool_name)
    if not full_schema:
        return False

    params_schema = _get_params_schema(full_schema)
    required_params = set(params_schema.get("required", []))

    if not required_params:
        return False

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except (json.JSONDecodeError, ValueError):
            return True
    if not isinstance(arguments, dict):
        return True

    provided = set(arguments.keys())
    missing = required_params - provided
    return bool(missing)


def partition_stub_calls(
    tool_calls: list[dict], schema_store: dict
) -> tuple[list[dict], list[dict]]:
    """Partition tool calls into stub calls (need schema) and real calls (ready to execute)."""
    stubs: list[dict] = []
    real: list[dict] = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        name = fn.get("name", "")
        raw_args = fn.get("arguments", "{}")
        if is_stub_call(name, raw_args, schema_store):
            stubs.append(tc)
        else:
            real.append(tc)
    return stubs, real


def _example_value(ptype: str, pname: str) -> Any:
    """Generate a placeholder example value based on type and param name."""
    if ptype in ("integer", "number"):
        return 1
    if ptype == "boolean":
        return True
    if ptype == "array":
        return []
    pname_lower = pname.lower()
    if "path" in pname_lower or "file" in pname_lower:
        return "/path/to/file"
    if "pattern" in pname_lower:
        return "*.txt"
    if "command" in pname_lower:
        return "echo hello"
    if "content" in pname_lower:
        return "file content here"
    return f"<{pname}>"


def format_schema_for_loading(full_schema: dict) -> str:
    """Dynamically generate schema loading text from any tool's original definition."""
    name = full_schema.get("name", "unknown")
    desc = full_schema.get("description", "")
    params_schema = _get_params_schema(full_schema)
    properties = params_schema.get("properties", {})
    required = set(params_schema.get("required", []))

    param_lines: list[str] = []
    example_args: dict[str, Any] = {}
    for pname, pdef in properties.items():
        ptype = pdef.get("type", "string")
        pdesc = pdef.get("description", "")
        req_mark = "*" if pname in required else ""
        param_lines.append(f"- {pname}{req_mark} ({ptype}): {pdesc}")
        if pname in required:
            example_args[pname] = _example_value(ptype, pname)

    params_text = "\n".join(param_lines) if param_lines else "(no parameters)"
    example_json = json.dumps(
        {"tool_calls": [{"function": {"name": name, "arguments": example_args}}]},
        ensure_ascii=False,
    )

    return (
        f"[TOOL_LOADED] {name}\n"
        f"{desc}\n\n"
        f"Parameters:\n{params_text}\n\n"
        f"Example:\n{example_json}\n\n"
        f"Now call {name} again with the correct arguments."
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
