from __future__ import annotations

"""Tool call prompt builder — injects MCP resource descriptions into messages."""

import re

from config.mcp_resource_registry import build_resource_prompt
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


def build_tool_call_prompt(tools: list[dict]) -> str:
    """Build prompt describing tools as MCP resources for Cursor to call via fetch_mcp_resource."""
    return build_resource_prompt(tools)


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
            "content": (
                f"Understood. I have access to {len(tools)} MCP resources from server 'claude-tools'. "
                "I will use fetch_mcp_resource to perform actions. Ready to serve the client."
            ),
        })

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
                for tc in tool_calls_list:
                    fn = tc.get("function") or tc
                    tc_name = fn.get("name", "unknown")
                    tc_args = fn.get("arguments", "{}")
                    parts.append(f"<tool_executed name=\"{tc_name}\" input={tc_args} />")
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
                    for block in raw_content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                t = block.get("text", "")
                                if t.strip():
                                    parts.append(t)
                            elif block.get("type") == "tool_use":
                                tool_name = block.get("name", "unknown")
                                tool_input = block.get("input", {})
                                parts.append(
                                    f"<tool_executed name=\"{tool_name}\" input={_json.dumps(tool_input, ensure_ascii=False)} />"
                                )
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

    result = _merge_consecutive_same_role(result)
    return result


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
