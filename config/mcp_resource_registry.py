from __future__ import annotations
"""
MCP Resource URI Registry — maps Claude Code tools to/from custom URI schemes.

Each Claude Code tool is exposed to Cursor as an MCP Resource with a custom URI
scheme. Cursor calls fetch_mcp_resource (enum=45) with the URI; thalamus-py
intercepts and parses the URI back into the original tool name + arguments.

URI format:  <scheme>://<authority>#<json-params>
Example:     bash://run#{"command":"ls -la"}
"""

import json
from urllib.parse import parse_qs, unquote, urlparse


MCP_SERVER_NAME = "claude-tools"

TOOL_TO_URI_SCHEME: dict[str, str] = {
    "Bash":             "bash://run",
    "Read":             "read://file",
    "Write":            "write://file",
    "Edit":             "edit://replace",
    "MultiEdit":        "edit://multi",
    "Glob":             "glob://search",
    "Grep":             "grep://search",
    "WebSearch":        "websearch://query",
    "WebFetch":         "webfetch://url",
    "TodoWrite":        "todo://write",
    "TodoRead":         "todo://read",
    "Agent":            "agent://launch",
    "Task":             "agent://task",
    "TaskOutput":       "task://output",
    "TaskStop":         "task://stop",
    "KillShell":        "task://kill",
    "NotebookEdit":     "notebook://edit",
    "AskUserQuestion":  "ask://user",
    "Config":           "config://setting",
    "EnterPlanMode":    "plan://enter",
    "ExitPlanMode":     "plan://exit",
    "ListDir":          "fs://listdir",
    "DeleteFile":       "fs://delete",
    "Sleep":            "util://sleep",
    "Computer":         "util://computer",
    "LSP":              "util://lsp",
    "Skill":            "util://skill",
    "BatchTool":        "util://batch",
    "ToolSearch":       "mcp://toolsearch",
    "ListMcpResources": "mcp://list",
    "ReadMcpResource":  "mcp://read",
    "Mcp":              "mcp://call",
}

_URI_SCHEME_TO_TOOL: dict[str, str] = {v: k for k, v in TOOL_TO_URI_SCHEME.items()}

_PARAM_ALIASES: dict[str, dict[str, str]] = {
    "Bash":  {"cmd": "command", "shell_command": "command"},
    "Glob":  {"glob_pattern": "glob_pattern"},
    "Grep":  {"query": "pattern", "search": "pattern", "regex": "pattern"},
}


def _normalize_param_names(tool_name: str, args: dict) -> dict:
    """Fix common parameter name mismatches from Cursor's model."""
    aliases = _PARAM_ALIASES.get(tool_name)
    if not aliases:
        return args
    normalized = {}
    for k, v in args.items():
        canonical = aliases.get(k, k)
        normalized[canonical] = v
    return normalized


def _coerce_param_types(args: dict) -> dict:
    """Convert string values to appropriate types (int, float, bool).

    URI query params are always strings but tool schemas expect numbers/booleans.
    """
    coerced = {}
    for k, v in args.items():
        if not isinstance(v, str):
            coerced[k] = v
            continue
        if v.lstrip("-").isdigit():
            coerced[k] = int(v)
        elif v.lower() in ("true", "false"):
            coerced[k] = v.lower() == "true"
        else:
            try:
                coerced[k] = float(v)
            except ValueError:
                coerced[k] = v
    return coerced


_CONTENT_PARAM_NAMES = {"content", "contents", "file_content", "command"}


def _parse_query_string_lenient(qs: str) -> dict:
    """Parse query string handling content params that may contain & and =.

    Content-like parameters (content, contents, command) are extracted
    greedily: everything from '&content=' to end-of-string is the value.
    This prevents file content containing & or = from being split.

    For non-content params: unquote_plus (+ → space).
    For content params: unquote (+ preserved as literal +).
    """
    from urllib.parse import unquote, unquote_plus
    args: dict[str, str] = {}
    if not qs:
        return args

    content_idx = -1
    content_key = ""
    for cname in _CONTENT_PARAM_NAMES:
        for prefix in [f"&{cname}=", f"{cname}="]:
            idx = qs.find(prefix)
            if idx >= 0:
                actual = idx + len(prefix)
                if prefix.startswith("&") or idx == 0:
                    if content_idx < 0 or idx < content_idx:
                        content_idx = idx
                        content_key = cname

    if content_idx >= 0:
        before = qs[:content_idx]
        sep = f"&{content_key}=" if content_idx > 0 else f"{content_key}="
        raw_val = qs[content_idx + len(sep):]
        args[content_key] = unquote(raw_val)

        for pair in before.split("&"):
            if not pair:
                continue
            eq_idx = pair.find("=")
            if eq_idx < 0:
                continue
            args[pair[:eq_idx]] = unquote_plus(pair[eq_idx + 1:])
    else:
        for pair in qs.split("&"):
            eq_idx = pair.find("=")
            if eq_idx < 0:
                continue
            args[pair[:eq_idx]] = unquote_plus(pair[eq_idx + 1:])
    return args


def parse_resource_uri(uri: str) -> tuple[str | None, dict]:
    """Parse a fetch_mcp_resource URI back to (tool_name, args_dict).

    Supports formats (tried in order):
    1. Query string:   bash://run?command=ls+-la          (preferred, shorter)
    2. Fragment JSON:  bash://run#{"command":"ls -la"}     (legacy/fallback)
    """
    if not uri:
        return None, {}

    query_idx = uri.find("?")
    fragment_idx = uri.find("#")

    if query_idx >= 0 and (fragment_idx < 0 or query_idx < fragment_idx):
        scheme_part = uri[:query_idx]
        qs_end = fragment_idx if fragment_idx > query_idx else len(uri)
        qs_str = uri[query_idx + 1:qs_end]
        tool_name = _URI_SCHEME_TO_TOOL.get(scheme_part)
        if tool_name and qs_str:
            args = _parse_query_string_lenient(qs_str)
            if args:
                args = _normalize_param_names(tool_name, args)
                args = _coerce_param_types(args)
                return tool_name, args

    if fragment_idx >= 0:
        scheme_part = uri[:fragment_idx]
        fragment = uri[fragment_idx + 1:].strip()
        tool_name = _URI_SCHEME_TO_TOOL.get(scheme_part)
        if tool_name and fragment and fragment != "{}":
            try:
                args = json.loads(unquote(fragment))
                if isinstance(args, dict) and args:
                    args = _normalize_param_names(tool_name, args)
                    return tool_name, args
            except (json.JSONDecodeError, ValueError):
                pass
        if tool_name:
            return tool_name, {}

    base_uri = uri.split("?")[0].split("#")[0]
    tool_name = _URI_SCHEME_TO_TOOL.get(base_uri)
    if tool_name:
        return tool_name, {}

    return None, {}


def build_resource_uri(tool_name: str, args: dict | None = None) -> str | None:
    """Build a resource URI for a given tool name and arguments."""
    from urllib.parse import quote
    scheme = TOOL_TO_URI_SCHEME.get(tool_name)
    if not scheme:
        return None
    if not args:
        return scheme
    pairs = [f"{k}={quote(str(v), safe='')}" for k, v in args.items()]
    return f"{scheme}?{'&'.join(pairs)}"


def build_resource_description(tool_name: str, tool_schema: dict) -> str | None:
    """Generate a single MCP resource description from a Claude Code tool schema.

    Uses URL query parameters (?key=value) instead of JSON fragment (#) to avoid
    Cursor's protobuf field length truncation on long URI fragments.
    """
    scheme = TOOL_TO_URI_SCHEME.get(tool_name)
    if not scheme:
        return None

    desc = tool_schema.get("description", "")
    if len(desc) > 300:
        desc = desc[:297] + "..."

    input_schema = tool_schema.get("input_schema") or {}
    properties = input_schema.get("properties") or {}
    required = set(input_schema.get("required") or [])

    param_parts = []
    for pname, pdef in properties.items():
        ptype = pdef.get("type", "string")
        req_marker = " [required]" if pname in required else ""
        param_parts.append(f"    {pname}: {ptype}{req_marker}")
    params_block = "\n".join(param_parts) if param_parts else "    (no parameters)"

    example_pairs = []
    for pname, pdef in properties.items():
        if pname in required:
            example_pairs.append(f"{pname}=<value>")
    example_qs = "&".join(example_pairs) if example_pairs else ""
    example_uri = f"{scheme}?{example_qs}" if example_qs else scheme

    return (
        f"- Resource: {scheme}\n"
        f"  Name: {tool_name}\n"
        f"  Description: {desc}\n"
        f"  Parameters:\n{params_block}\n"
        f"  URI format: {scheme}?param1=value1&param2=value2\n"
        f"  Example: {example_uri}"
    )


def build_resource_prompt(tools: list[dict]) -> str:
    """Convert a Claude Code tools array into an MCP resource list prompt.

    Each tool in the array has {name, description, input_schema} (possibly
    nested under a 'function' key for OpenAI-style format).
    """
    lines = [
        f"You have access to the following MCP resources from server '{MCP_SERVER_NAME}'.\n"
        "When you need to perform an action, fetch the appropriate MCP resource.\n"
        "CRITICAL URI FORMAT RULES:\n"
        "- Use URL query string: scheme://authority?key=value&key2=value2\n"
        "- Do NOT URL-encode file paths, slashes, spaces, or special characters in values.\n"
        "- Only encode & as %26 and = as %3D if they appear literally in a value.\n"
        "- For multi-line content, encode newlines as %0A.\n"
        "- Example: read://file?file_path=/path/to/my file.txt (spaces OK, no encoding needed)\n"
    ]

    count = 0
    for tool_def in tools:
        fn = tool_def.get("function") or tool_def
        name = fn.get("name", "")
        if not name:
            continue

        schema = {
            "description": fn.get("description", ""),
            "input_schema": fn.get("input_schema") or fn.get("parameters") or {},
        }

        entry = build_resource_description(name, schema)
        if entry:
            count += 1
            lines.append(f"{count}. {entry[2:]}")

    lines.append(
        f"\nTotal: {count} resource(s) available. "
        "You MUST use MCP resources to perform actions. "
        "Do NOT describe actions in text — fetch the resource instead."
    )

    return "\n\n".join(lines)
