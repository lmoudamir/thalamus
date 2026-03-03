"""Tool call prompt builder — Python port of claude_tool_prompt_and_parser.js (prompt-building only)."""

import re

from config.system_prompt import (
    DECONTAMINATION_REMINDER,
    EXECUTION_NUDGE,
    TURN1_USER,
    TURN2_ASSISTANT,
    TURN3_USER,
    TURN4_ASSISTANT,
    TURN5_EXECUTION_RULES,
    TURN6_ASSISTANT_ACK,
    TURN7_BEHAVIORAL_STANDARDS,
    TURN8_ASSISTANT_ACK,
)

ASK_MODE_CONTAMINATION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ask\s*mode", re.IGNORECASE),
    re.compile(r"read[\s-]*only", re.IGNORECASE),
    re.compile(r"只能.*读"),
    re.compile(r"只能.*分析"),
    re.compile(r"不能.*写入"),
    re.compile(r"不能.*write", re.IGNORECASE),
    re.compile(r"无法.*写入"),
    re.compile(r"无法.*落盘"),
    re.compile(r"无法.*执行.*写"),
    re.compile(r"手动.*写入"),
    re.compile(r"手动.*粘贴"),
    re.compile(r"手动.*复制"),
    re.compile(r"手动.*apply", re.IGNORECASE),
    re.compile(r"可直接粘贴"),
    re.compile(r"可直接复制"),
    re.compile(r"直接粘贴替换"),
    re.compile(r"粘贴.*替换"),
    re.compile(r"copy.*paste", re.IGNORECASE),
    re.compile(r"paste.*into", re.IGNORECASE),
    re.compile(r"directly\s+pasteable", re.IGNORECASE),
    re.compile(
        r"I\s+can(?:'t|not)\s+(?:actually\s+)?(?:write|create|modify|execute)",
        re.IGNORECASE,
    ),
    re.compile(r"I\s+(?:don't|do\s+not)\s+have\s+write", re.IGNORECASE),
    re.compile(r"no\s+write\s+(?:access|permission)", re.IGNORECASE),
    re.compile(
        r"cannot\s+(?:actually\s+)?(?:write|create|save|execute)", re.IGNORECASE
    ),
    re.compile(r"工具.*约束"),
    re.compile(r"(?:读|read)\s*\+\s*(?:分析|analysis)", re.IGNORECASE),
]

_TOOL_PROMPT_TEMPLATE = """You have access to {tool_count} tool(s).

You MUST choose exactly ONE output mode per reply:
- MODE A (tool execution): output ONLY a tool-call payload
- MODE B (normal response): output ONLY natural-language text
Never mix both modes in one reply.

When you need to use a tool, respond with a JSON object in this format:

{{"tool_calls":[{{"function":{{"name":"TOOL_NAME","arguments":{{...}}}}}}]}}

=== TOOL PARAMETER REFERENCE (from Claude Code official schema, additionalProperties=false) ===
The host system does NOT provide parameter schemas in the tools array. You MUST use EXACTLY these parameter names and types. Wrong names cause InputValidationError. Every tool has additionalProperties=false — unlisted parameters are rejected.

Write(file_path: string [required], content: string [required])
  Create or overwrite a file. MUST use absolute path.
  WRONG: {{"path":"a.txt","contents":"..."}}  ← "path" and "contents" do NOT exist
  CORRECT: {{"file_path":"/abs/path/a.txt","content":"file content here"}}

Read(file_path: string [required], offset?: number, limit?: number)
  Read a file. MUST use absolute path. Optional offset (1-based line number) and limit (line count).
  WRONG: {{"path":"file.txt"}}  ← "path" does NOT exist, use "file_path"
  CORRECT: {{"file_path":"/abs/path/file.txt"}}
  CORRECT: {{"file_path":"/abs/path/file.txt","offset":10,"limit":50}}

Edit(file_path: string [required], old_string: string [required], new_string: string [required], replace_all?: boolean)
  Exact string replacement. MUST use absolute path. new_string must differ from old_string.
  CORRECT: {{"file_path":"/abs/path/file.js","old_string":"const x = 1;","new_string":"const x = 2;"}}
  With replace_all: {{"file_path":"/abs/path/file.js","old_string":"foo","new_string":"bar","replace_all":true}}

Bash(command: string [required], description?: string, timeout?: number, run_in_background?: boolean)
  Execute shell command. Optional description (5-10 words), timeout (ms, max 600000, default 120000).
  CORRECT: {{"command":"ls -la /some/path"}}
  CORRECT: {{"command":"npm test","description":"Run test suite","timeout":300000}}

Glob(pattern: string [required], path?: string)
  Find files by glob pattern. Optional path = directory to search (omit for cwd).
  WRONG: {{"glob_pattern":"*.js"}}  ← "glob_pattern" does NOT exist
  WRONG: {{"pattern":"*.js","max_depth":3}}  ← "max_depth" does NOT exist
  CORRECT: {{"pattern":"src/**/*.js"}}
  CORRECT: {{"pattern":"**/*.ts","path":"/abs/path/to/dir"}}

Grep(pattern: string [required], path?: string, output_mode?: string, glob?: string, type?: string, -i?: boolean, -A?: number, -B?: number, -C?: number, multiline?: boolean, head_limit?: number)
  Search file contents with regex (ripgrep). output_mode: "content"|"files_with_matches" (default)|"count".
  WRONG: {{"pattern":"foo","include":"*.js"}}  ← "include" does NOT exist, use "glob"
  CORRECT: {{"pattern":"function\\\\s+main","path":"/project/src","glob":"*.js"}}
  CORRECT: {{"pattern":"TODO","output_mode":"content","-C":3}}

WebFetch(url: string [required])
  Fetch content from a URL.
  CORRECT: {{"url":"https://example.com"}}

Agent(prompt: string [required], model?: string)
  Launch a sub-agent. prompt = task description.
  CORRECT: {{"prompt":"Search the codebase for all API endpoints"}}

NotebookEdit(notebook_path: string [required], new_source: string [required], cell_id?: string, cell_type?: string, edit_mode?: string)
  Edit Jupyter notebook cell. notebook_path = absolute path. edit_mode: "replace" (default)|"insert"|"delete".
  CORRECT: {{"notebook_path":"/abs/path/notebook.ipynb","new_source":"print('hello')","cell_id":"abc123"}}

TodoWrite(todos: array [required])
  Track task progress. todos = array of {{id, content, status}} objects. status: "pending"|"in_progress"|"completed".
  CORRECT: {{"todos":[{{"id":"1","content":"Fix bug","status":"in_progress"}}]}}

BashOutput(bash_id: string [required], filter?: string)
  Read output from background shell. bash_id = ID returned by Bash with run_in_background=true.
  CORRECT: {{"bash_id":"bg_abc123"}}

IMPORTANT: When creating files, ALWAYS use Write tool directly. When modifying files, ALWAYS use Edit tool directly. Do NOT paste code in your text response. NEVER narrate code — EXECUTE it via tool calls.

=== CRITICAL CONSTRAINTS ===
1. Tool names are CASE-SENSITIVE. Do NOT change capitalization.
   WRONG: "bash", "read", "edit"    CORRECT: "Bash", "Read", "Edit"
2. ONLY use tools from this list: [{tool_name_list}]. Do NOT invent, fabricate, or hallucinate tool names not listed here.
3. If none of the available tools match what you need, respond in natural language instead of inventing a tool name.
4. If the user explicitly requires at least one tool call (for example: "MUST call at least one tool" or "first message must be tool-call JSON"), you MUST output a valid tool_calls JSON before any final narrative response.
5. NEVER fabricate capability inventories or permissions.
   WRONG: "I have access to 44 tools..." / "I can use TeamCreate, TaskCreate, ..."
   If you are executing a tool, emit the tool call directly instead of narrating tool lists.
6. arguments must be a JSON OBJECT (not string/array/number/null).
7. ALWAYS prefer tool execution over pasting code. If the task is to write/create/modify a file, USE Write or Edit. NEVER dump code blocks in your text response as a substitute for tool execution.

=== OUTPUT FORMAT ===
When calling a tool, output ONLY the tool payload. Do not include text before/after, and do not wrap in markdown code blocks.

CRITICAL: You MUST NEVER describe a tool call in natural language instead of executing it.
If you intend to use a tool, OUTPUT THE JSON — do not narrate your intent.
WRONG: "I will now search for..." or "Let me read the file..." or "准备执行命令..."
CORRECT: {{"tool_calls":[{{"function":{{"name":"...","arguments":{{...}}}}}}]}}

Examples:
- Read: {{"tool_calls":[{{"function":{{"name":"Read","arguments":{{"file_path":"/abs/path/config.json"}}}}}}]}}
- Write: {{"tool_calls":[{{"function":{{"name":"Write","arguments":{{"file_path":"/abs/path/a.txt","content":"hello world"}}}}}}]}}
- Multiple: {{"tool_calls":[{{"function":{{"name":"Write","arguments":{{"file_path":"/abs/path/a.txt","content":"..."}}}}}},{{"function":{{"name":"Write","arguments":{{"file_path":"/abs/path/b.txt","content":"..."}}}}}}]}}
- Hermes/Qwen style (also accepted): <tool_call>{{"name":"Read","arguments":{{"file_path":"/abs/path/config.json"}}}}</tool_call>
- Llama style (also accepted): <<function=Read>>{{"file_path":"/abs/path/config.json"}}<</function>>

If the user's request doesn't require a tool, respond normally in natural language."""


def build_tool_call_prompt(tools: list[dict]) -> str:
    """Build prompt string teaching the model how to output structured tool_calls JSON."""
    available_tool_names = [
        str((t.get("function") or t).get("name", "")) for t in tools
    ]
    tool_name_list = ", ".join(f'"{n}"' for n in available_tool_names)
    return _TOOL_PROMPT_TEMPLATE.format(
        tool_count=len(tools), tool_name_list=tool_name_list
    )


def _extract_message_content(msg: dict) -> str:
    content = msg.get("content")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return str(content) if content else ""


def _is_contaminated_assistant_message(content: str) -> bool:
    if not content:
        return False
    return any(p.search(content) for p in ASK_MODE_CONTAMINATION_PATTERNS)


def _is_text_only_assistant_needing_nudge(content: str) -> bool:
    if not content or not content.strip():
        return False
    if "done!!" in content:
        return False
    if re.search(r'\{"tool_calls"\s*:', content):
        return False
    if re.search(r'\{"function"\s*:', content):
        return False
    return True


def inject_tool_prompt_into_messages(
    messages: list[dict], tools: list[dict]
) -> list[dict]:
    """Inject tool-call prompt and system turns into OpenAI-format messages."""
    result: list[dict] = []

    result.append({"role": "user", "content": TURN1_USER})
    result.append({"role": "assistant", "content": TURN2_ASSISTANT})

    result.append({"role": "user", "content": TURN3_USER})
    result.append({"role": "assistant", "content": TURN4_ASSISTANT})

    result.append({"role": "user", "content": TURN5_EXECUTION_RULES})
    result.append({"role": "assistant", "content": TURN6_ASSISTANT_ACK})

    result.append({"role": "user", "content": TURN7_BEHAVIORAL_STANDARDS})
    result.append({"role": "assistant", "content": TURN8_ASSISTANT_ACK})

    if tools:
        prompt = build_tool_call_prompt(tools)
        result.append({"role": "user", "content": prompt})
        result.append({
            "role": "assistant",
            "content": f"Understood. I have {len(tools)} tools available. I will output tool calls as JSON and never narrate my intent. Ready to serve the client.",
        })

    for m in messages:
        if m.get("role") == "tool":
            content = _extract_message_content(m)
            result.append({
                "role": "user",
                "content": f"[Tool Result]\n{content}",
            })
            continue

        if m.get("role") == "assistant":
            content = _extract_message_content(m)
            if _is_contaminated_assistant_message(content):
                result.append(m)
                result.append({"role": "user", "content": DECONTAMINATION_REMINDER})
                continue

        result.append(m)

    recent_assistant = None
    for i in range(len(result) - 1, -1, -1):
        if result[i].get("role") == "assistant":
            recent_assistant = result[i]
            break
        if result[i].get("role") == "user":
            break
    if recent_assistant and _is_text_only_assistant_needing_nudge(
        _extract_message_content(recent_assistant)
    ):
        result.append({"role": "user", "content": EXECUTION_NUDGE})

    return result
