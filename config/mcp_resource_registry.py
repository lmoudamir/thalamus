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
    "Read":  {"path": "file_path", "filepath": "file_path", "file": "file_path"},
    "Write": {"path": "file_path", "filepath": "file_path", "file": "file_path",
              "contents": "content", "text": "content", "data": "content"},
    "Edit":  {"path": "file_path", "filepath": "file_path", "file": "file_path"},
    "Glob":  {"pattern": "glob_pattern"},
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


_SAFE_DECODE_MAP = {
    "%0A": "\n", "%0a": "\n",
    "%0D": "\r", "%0d": "\r",
    "%09": "\t",
    "%20": " ",
    "%25": "%",
    "%26": "&",
    "%3D": "=", "%3d": "=",
    "%23": "#",
    "%22": '"',
    "%27": "'",
    "%5C": "\\", "%5c": "\\",
}


def _safe_unquote(s: str) -> str:
    """Decode only known safe percent-sequences, leaving everything else literal.

    This prevents Go modulo '%10', printf '%d', etc. from being corrupted
    while still correctly decoding whitespace and control characters.
    """
    import re
    def _replace(m: re.Match) -> str:
        seq = m.group(0)
        return _SAFE_DECODE_MAP.get(seq, _SAFE_DECODE_MAP.get(seq.upper(), seq))
    return re.sub(r"%[0-9A-Fa-f]{2}", _replace, s)


def _parse_query_string_lenient(qs: str) -> dict:
    """Parse query string handling content params that may contain & and =.

    Content-like parameters (content, contents, command) are extracted
    greedily: everything from '&content=' to end-of-string is the value.
    This prevents file content containing & or = from being split.

    Uses _safe_unquote for all values — only decodes whitespace/control
    sequences, preserving literal % in source code (e.g. Go's %10).
    """
    from urllib.parse import unquote_plus
    args: dict[str, str] = {}
    if not qs:
        return args

    content_idx = -1
    content_key = ""
    for cname in _CONTENT_PARAM_NAMES:
        for prefix in [f"&{cname}=", f"{cname}="]:
            idx = qs.find(prefix)
            if idx >= 0:
                if prefix.startswith("&") or idx == 0:
                    if content_idx < 0 or idx < content_idx:
                        content_idx = idx
                        content_key = cname

    if content_idx >= 0:
        before = qs[:content_idx]
        sep = f"&{content_key}=" if content_idx > 0 else f"{content_key}="
        raw_val = qs[content_idx + len(sep):]
        args[content_key] = _safe_unquote(raw_val)

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


def _parse_standard_uri_to_tool(uri: str) -> tuple[str | None, dict]:
    """Map standard URI schemes (file://, http://) to tool calls.

    Handles cases where the model uses standard URIs instead of our custom schemes:
      file:///path/to/file  →  Read(path="/path/to/file")
      http://...            →  WebFetch(url="http://...")
      https://...           →  WebFetch(url="https://...")
    """
    if uri.startswith("file:///"):
        path = uri[7:]
        if path:
            return "Read", {"file_path": path}
    elif uri.startswith("file://"):
        path = uri[7:]
        if path:
            return "Read", {"file_path": path}
    elif uri.startswith(("http://", "https://")):
        return "WebFetch", {"url": uri}
    return None, {}


def parse_resource_uri(uri: str) -> tuple[str | None, dict]:
    """Parse a fetch_mcp_resource URI back to (tool_name, args_dict).

    Supports formats (tried in order):
    1. Fragment JSON:  bash://run#{"command":"ls -la"}     (preferred — JSON handles all escaping)
    2. Query string:   bash://run?command=ls+-la          (fallback for simple params)
    3. Standard URIs:  file:///path → Read(path)           (fallback for model using standard schemes)
    """
    if not uri:
        return None, {}

    fragment_idx = uri.find("#")
    query_idx = uri.find("?")

    if fragment_idx >= 0:
        scheme_part = uri[:fragment_idx]
        fragment = uri[fragment_idx + 1:].strip()
        tool_name = _URI_SCHEME_TO_TOOL.get(scheme_part)
        if tool_name and fragment and fragment != "{}":
            try:
                args = json.loads(fragment)
                if isinstance(args, dict) and args:
                    args = _normalize_param_names(tool_name, args)
                    return tool_name, args
            except (json.JSONDecodeError, ValueError):
                pass
        if tool_name:
            return tool_name, {}

    if query_idx >= 0:
        scheme_part = uri[:query_idx]
        qs_str = uri[query_idx + 1:]
        tool_name = _URI_SCHEME_TO_TOOL.get(scheme_part)
        if tool_name and qs_str:
            args = _parse_query_string_lenient(qs_str)
            if args:
                args = _normalize_param_names(tool_name, args)
                args = _coerce_param_types(args)
                return tool_name, args

    base_uri = uri.split("?")[0].split("#")[0]
    tool_name = _URI_SCHEME_TO_TOOL.get(base_uri)
    if tool_name:
        return tool_name, {}

    return _parse_standard_uri_to_tool(uri)


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

    Uses JSON fragment (#) format — JSON handles all escaping natively,
    avoiding URL-encoding issues with %, #, newlines in file content.
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

    example_obj = {}
    for pname, pdef in properties.items():
        if pname in required:
            example_obj[pname] = "<value>"
    example_json = json.dumps(example_obj) if example_obj else "{}"
    example_uri = f'{scheme}#{example_json}'

    return (
        f"- Resource: {scheme}\n"
        f"  Name: {tool_name}\n"
        f"  Description: {desc}\n"
        f"  Parameters:\n{params_block}\n"
        f'  URI format: {scheme}#{{"param1":"value1","param2":"value2"}}\n'
        f"  Example: {example_uri}"
    )


def build_resource_prompt(tools: list[dict]) -> str:
    """Convert a Claude Code tools array into an MCP resource list prompt.

    LEGACY — kept as fallback for enum=45 path. Prefer build_tool_prompt().
    """
    lines = [
        f"You have access to the following MCP resources from server '{MCP_SERVER_NAME}'.\n"
        "When you need to perform an action, fetch the appropriate MCP resource.\n"
        "CRITICAL URI FORMAT RULES:\n"
        '- Use JSON fragment: scheme://authority#{{"key":"value","key2":"value2"}}\n'
        "- The JSON after # follows standard JSON escaping (\\n for newline, \\t for tab, etc.).\n"
        "- Do NOT URL-encode anything. Just write valid JSON after the # character.\n"
        '- Example: read://file#{{"path":"/path/to/my file.txt"}}\n'
        '- Example: write://file#{{"path":"/tmp/app.go","contents":"package main\\n\\nfunc main() {{}}\\n"}}\n'
        '- Example: bash://run#{{"command":"ls -la /tmp"}}\n'
        '- Example: edit://replace#{{"path":"/tmp/app.go","old_string":"func main","new_string":"func Main"}}\n'
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


# ---------------------------------------------------------------------------
# enum=49 call_mcp_tool prompt (preferred path)
# ---------------------------------------------------------------------------


def _build_tool_description_for_mcp(tool_name: str, tool_schema: dict) -> str | None:
    """Generate a single MCP tool description for call_mcp_tool invocation."""
    desc = tool_schema.get("description", "")
    if len(desc) > 300:
        desc = desc[:297] + "..."

    input_schema = tool_schema.get("input_schema") or {}
    properties = input_schema.get("properties") or {}
    required = set(input_schema.get("required") or [])

    param_parts = []
    for pname, pdef in properties.items():
        ptype = pdef.get("type", "string")
        pdesc = pdef.get("description", "")
        req_marker = " [required]" if pname in required else ""
        line = f"    {pname}: {ptype}{req_marker}"
        if pdesc:
            short_desc = pdesc[:120] + "..." if len(pdesc) > 120 else pdesc
            line += f" — {short_desc}"
        param_parts.append(line)
    params_block = "\n".join(param_parts) if param_parts else "    (no parameters)"

    example_args = {}
    for pname in properties:
        if pname in required:
            example_args[pname] = "<value>"

    return (
        f"- Tool: {tool_name}\n"
        f"  Description: {desc}\n"
        f"  Parameters:\n{params_block}\n"
        f"  Example arguments: {json.dumps(example_args)}"
    )


def build_tool_prompt(tools: list[dict]) -> str:
    """Convert a Claude Code tools array into MCP tool descriptions.

    Uses a hybrid format: tools are described as both MCP tools (call_mcp_tool)
    and MCP resources (URI with JSON fragment). Cursor currently routes most
    tool calls through enum=45 (fetch_mcp_resource), so the URI format is
    the primary invocation path. enum=49 (call_mcp_tool) is described for
    forward compatibility.
    """
    srv = MCP_SERVER_NAME
    lines = [
        f"You have access to the following tools via MCP server '{srv}'.\n\n"
        f"HOW TO INVOKE:\n"
        f"Option A (preferred): fetch_mcp_resource with JSON fragment URI:\n"
        f'  server: "{srv}"\n'
        f'  uri: "<scheme>://<authority>#{{"param1":"value1","param2":"value2"}}"\n'
        f"  The JSON after # uses standard JSON escaping (\\n for newline, \\t for tab, etc.).\n"
        f"  Do NOT URL-encode anything. Just write valid JSON after the # character.\n\n"
        f"Option B: call_mcp_tool with structured JSON:\n"
        f'  server: "{srv}"\n'
        f'  toolName: "<ToolName>"\n'
        f'  arguments: {{ ... }}\n\n'
        f"URI EXAMPLES:\n"
        f'  read://file#{{"file_path":"/path/to/file.txt"}}\n'
        f'  write://file#{{"file_path":"/tmp/app.go","content":"package main\\n\\nfunc main() {{}}\\n"}}\n'
        f'  bash://run#{{"command":"ls -la /tmp"}}\n'
        f'  edit://replace#{{"file_path":"/tmp/app.go","old_string":"func main","new_string":"func Main"}}\n'
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

        entry = _build_tool_description_for_mcp(name, schema)
        uri_scheme = TOOL_TO_URI_SCHEME.get(name, "")
        if entry and uri_scheme:
            count += 1
            lines.append(f"{count}. {entry[2:]}\n  URI scheme: {uri_scheme}")
        elif entry:
            count += 1
            lines.append(f"{count}. {entry[2:]}")

    lines.append(
        f"\nTotal: {count} tool(s) on MCP server '{srv}'. "
        "You MUST use these tools to perform actions. "
        "Do NOT describe or narrate actions — call the tool."
    )

    return "\n\n".join(lines)
