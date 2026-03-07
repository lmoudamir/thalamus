from __future__ import annotations

"""Tool call prompt builder — injects tool descriptions into messages.

Tool calling is handled entirely via prompt injection: tool descriptions
are serialized into the system/user prompt as text, and the model outputs
tool calls as JSON in its text response. No MCP/URI/protobuf tool call
mechanism is used.
"""

import json
import logging
import re

from config.system_prompt import (
    DECONTAMINATION_REMINDER,
    TURN1_USER,
    TURN2_ASSISTANT,
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


def build_tool_call_prompt(tools: list[dict]) -> str:
    """Build a text prompt describing available tools.

    The model should output tool calls as JSON:
      {"tool_calls": [{"function": {"name": "ToolName", "arguments": {...}}}]}
    """
    lines = [
        "You have access to the following tools.\n"
        "When you need to perform an action, output a JSON object:\n"
        '  {"tool_calls": [{"function": {"name": "<ToolName>", "arguments": {<params>}}}]}\n\n'
        "Examples:\n"
        '  {"tool_calls": [{"function": {"name": "Bash", "arguments": {"command": "ls -la"}}}]}\n'
        '  {"tool_calls": [{"function": {"name": "Read", "arguments": {"file_path": "/tmp/app.go"}}}]}\n'
        '  {"tool_calls": [{"function": {"name": "Write", "arguments": {"file_path": "/tmp/app.go", "content": "package main\\n"}}}]}\n'
        '  {"tool_calls": [{"function": {"name": "Edit", "arguments": {"file_path": "/tmp/app.go", "old_string": "old", "new_string": "new"}}}]}\n'
    ]

    count = 0
    for tool_def in tools:
        fn = tool_def.get("function") or tool_def
        name = fn.get("name", "")
        if not name:
            continue

        desc = fn.get("description", "")

        input_schema = fn.get("input_schema") or fn.get("parameters") or {}
        properties = input_schema.get("properties") or {}
        required = set(input_schema.get("required") or [])

        param_parts = []
        for pname, pdef in properties.items():
            ptype = pdef.get("type", "string")
            pdesc = pdef.get("description", "")
            req_marker = " [required]" if pname in required else ""
            line = f"    {pname}: {ptype}{req_marker}"
            if pdesc:
                line += f" — {pdesc}"
            param_parts.append(line)
        params_block = "\n".join(param_parts) if param_parts else "    (no parameters)"

        count += 1
        lines.append(
            f"{count}. Tool: {name}\n"
            f"  Description: {desc}\n"
            f"  Parameters:\n{params_block}"
        )

    lines.append(
        f"\nTotal: {count} tool(s). Use tool_calls JSON for ALL actions — never narrate."
    )

    return "\n\n".join(lines)


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


def _extract_tool_results_from_content(content) -> list[dict]:
    """Extract tool_result blocks from Anthropic-format content arrays.

    Returns a list of dicts with keys: tool_use_id, content_text, is_error.
    """
    if not isinstance(content, list):
        return []
    results = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        tool_use_id = block.get("tool_use_id", "")
        is_error = block.get("is_error", False)
        inner = block.get("content", "")
        if isinstance(inner, str):
            text = inner
        elif isinstance(inner, list):
            text = "".join(
                p.get("text", "") if isinstance(p, dict) else str(p) for p in inner
            )
        else:
            text = str(inner) if inner else ""
        results.append({
            "tool_use_id": tool_use_id,
            "content_text": text,
            "is_error": is_error,
        })
    return results


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
    messages: list[dict], tools: list[dict],
    stub_reminder: str = "",
    reminder_interval: int = 15,
) -> list[dict]:
    """Inject tool-call prompt and system turns into OpenAI-format messages.

    If stub_reminder is provided, it's injected every reminder_interval
    user-turns to keep tool protocol fresh in the LLM's attention window.
    """
    result: list[dict] = []

    result.append({"role": "user", "content": TURN1_USER})
    result.append({"role": "assistant", "content": TURN2_ASSISTANT})

    # Build tool_use_id → tool_name map for rich few-shot context
    _tool_id_to_name: dict[str, str] = {}
    for m in messages:
        for src in [m.get("content", []), m.get("tool_calls", [])]:
            if not isinstance(src, list):
                continue
            for block in src:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    _tool_id_to_name[block.get("id", "")] = block.get("name", "unknown")
                fn = block.get("function")
                if isinstance(fn, dict) and fn.get("name"):
                    _tool_id_to_name[block.get("id", "")] = fn["name"]

    for m in messages:
        role = m.get("role", "")
        raw_content = m.get("content")

        if role == "tool":
            content = _extract_message_content(m)
            tid = m.get("tool_call_id", "")
            tname = _tool_id_to_name.get(tid, "")
            tag = f" name=\"{tname}\"" if tname else ""
            result.append({
                "role": "user",
                "content": f"<tool_result{tag}>\n{content}\n</tool_result>",
            })
            continue

        if role == "user" and isinstance(raw_content, list):
            tool_results = _extract_tool_results_from_content(raw_content)
            if tool_results:
                parts = []
                for tr in tool_results:
                    tname = _tool_id_to_name.get(tr["tool_use_id"], "")
                    tag = f" name=\"{tname}\"" if tname else ""
                    if tr["is_error"]:
                        parts.append(
                            f"<tool_error{tag}>\n"
                            f"{tr['content_text']}\n"
                            f"Fix the parameters and retry.\n"
                            f"</tool_error>"
                        )
                    else:
                        parts.append(
                            f"<tool_result{tag}>\n"
                            f"{tr['content_text']}\n"
                            f"</tool_result>"
                        )
                non_tr_text = _extract_message_content(m)
                if non_tr_text.strip():
                    parts.append(non_tr_text)
                result.append({
                    "role": "user",
                    "content": "\n\n".join(parts),
                })
                continue

        if role == "user" and isinstance(raw_content, str):
            if "<tool_use_error>" in raw_content:
                result.append({
                    "role": "user",
                    "content": (
                        f"<tool_error>\n"
                        f"{raw_content}\n"
                        f"Fix the parameters and retry.\n"
                        f"</tool_error>"
                    ),
                })
                continue

        if role == "assistant":
            import json as _json
            tool_calls_list = m.get("tool_calls") or []
            if tool_calls_list:
                parts = []
                content_text = _extract_message_content(m)
                if content_text.strip():
                    parts.append(content_text)
                tc_json_list = []
                for tc in tool_calls_list:
                    fn = tc.get("function") or tc
                    tc_json_list.append({"function": {"name": fn.get("name", "unknown"), "arguments": _json.loads(fn.get("arguments", "{}")) if isinstance(fn.get("arguments"), str) else fn.get("arguments", {})}})
                parts.append(_json.dumps({"tool_calls": tc_json_list}, ensure_ascii=False))
                result.append({
                    "role": "assistant",
                    "content": "\n".join(parts),
                })
                continue

            if isinstance(raw_content, list):
                has_tool_use = any(
                    isinstance(b, dict) and b.get("type") == "tool_use"
                    for b in raw_content
                )
                if has_tool_use:
                    parts = []
                    tc_json_list = []
                    for block in raw_content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                t = block.get("text", "")
                                if t.strip():
                                    parts.append(t)
                            elif block.get("type") == "tool_use":
                                tc_json_list.append({"function": {"name": block.get("name", "unknown"), "arguments": block.get("input", {})}})
                    if tc_json_list:
                        parts.append(_json.dumps({"tool_calls": tc_json_list}, ensure_ascii=False))
                    result.append({
                        "role": "assistant",
                        "content": "\n".join(parts) if parts else "(ok)",
                    })
                    continue

            content = _extract_message_content(m)
            if _is_contaminated_assistant_message(content):
                result.append(m)
                result.append({"role": "user", "content": DECONTAMINATION_REMINDER})
                continue

        result.append(m)

    if stub_reminder and reminder_interval > 0:
        result = _inject_periodic_reminders(result, stub_reminder, reminder_interval)

    result = _merge_consecutive_same_role(result)
    return result


def _inject_periodic_reminders(
    messages: list[dict], reminder: str, interval: int
) -> list[dict]:
    """Insert a tool-protocol reminder every `interval` user turns.

    Walks the converted message list and counts user messages (skipping
    the initial TURN1 priming message at index 0).  After every `interval`th
    user message, a synthetic assistant ack + user reminder pair is inserted
    so the LLM re-attends to the tool-calling protocol.

    The injection only happens between user→assistant boundaries — never
    inside a tool_result flow — to avoid breaking the conversation structure.
    """
    if interval <= 0 or not reminder:
        return messages

    out: list[dict] = []
    user_count = 0
    skip_first_user = True

    for i, m in enumerate(messages):
        if m.get("role") == "user":
            if skip_first_user:
                skip_first_user = False
                out.append(m)
                continue
            user_count += 1
            if user_count > 0 and user_count % interval == 0:
                content = m.get("content", "")
                is_tool_result = (
                    "<tool_result" in str(content) or "<tool_error" in str(content)
                )
                if not is_tool_result:
                    logging.getLogger("thalamus.tool-prompt").info(
                        f"LTLP stub reminder injected at user turn {user_count}"
                    )
                    out.append({"role": "user", "content": reminder})
                    out.append({"role": "assistant", "content": "(tools noted)"})
        out.append(m)

    return out


def _merge_consecutive_same_role(messages: list[dict]) -> list[dict]:
    """Merge consecutive messages with the same role to avoid API errors.

    Preserves [Tool Result] / [Tool Error] boundaries to maintain conversation context.
    """
    if not messages:
        return messages
    merged: list[dict] = [messages[0]]
    for m in messages[1:]:
        prev = merged[-1]
        cur_text = _extract_message_content(m)
        if m.get("role") == prev.get("role"):
            prev_text = _extract_message_content(prev)
            combined = f"{prev_text}\n\n{cur_text}" if prev_text and cur_text else (prev_text or cur_text)
            merged[-1] = {"role": prev.get("role"), "content": combined}
        else:
            if m.get("role") == "assistant" and not cur_text.strip():
                merged.append({"role": "assistant", "content": "(continued)"})
            else:
                merged.append(m)
    return merged
