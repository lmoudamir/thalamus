"""Test the full tool calling flow: request → tool_use → tool_result → final answer.

Simulates what Claude Code does:
1. Send a prompt asking to read a file
2. Receive tool_use response 
3. Execute the tool locally (read the file)
4. Send tool_result back
5. Receive final answer
"""
import json
import os
import requests

BASE_URL = "http://localhost:3013"
MODEL = "gpt-5.3-codex-spark-preview-xhigh"

TOOLS = [
    {
        "name": "Read",
        "description": "Read a file",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path to file"}
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "Bash",
        "description": "Execute a command",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to execute"}
            },
            "required": ["command"],
        },
    },
]


def parse_sse_events(text: str) -> list[dict]:
    events = []
    current_event = {}
    for line in text.split("\n"):
        if line.startswith("event: "):
            current_event["event"] = line[7:]
        elif line.startswith("data: "):
            try:
                current_event["data"] = json.loads(line[6:])
            except json.JSONDecodeError:
                current_event["data"] = line[6:]
        elif line == "":
            if current_event:
                events.append(current_event)
                current_event = {}
    if current_event:
        events.append(current_event)
    return events


def extract_tool_calls(events: list[dict]) -> list[dict]:
    tool_calls = []
    current_tc = None
    for ev in events:
        data = ev.get("data", {})
        if not isinstance(data, dict):
            continue
        if data.get("type") == "content_block_start":
            block = data.get("content_block", {})
            if block.get("type") == "tool_use":
                current_tc = {
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "input": {},
                    "partial_json": "",
                }
        elif data.get("type") == "content_block_delta":
            delta = data.get("delta", {})
            if delta.get("type") == "input_json_delta" and current_tc:
                current_tc["partial_json"] += delta.get("partial_json", "")
        elif data.get("type") == "content_block_stop":
            if current_tc:
                try:
                    current_tc["input"] = json.loads(current_tc["partial_json"])
                except (json.JSONDecodeError, ValueError):
                    pass
                del current_tc["partial_json"]
                tool_calls.append(current_tc)
                current_tc = None
    return tool_calls


def extract_text(events: list[dict]) -> str:
    parts = []
    for ev in events:
        data = ev.get("data", {})
        if not isinstance(data, dict):
            continue
        if data.get("type") == "content_block_delta":
            delta = data.get("delta", {})
            if delta.get("type") == "text_delta":
                parts.append(delta.get("text", ""))
    return "".join(parts)


def step1_send_prompt():
    print("=" * 60)
    print("STEP 1: Send prompt asking to read a file")
    print("=" * 60)
    
    resp = requests.post(
        f"{BASE_URL}/v1/messages",
        headers={
            "Content-Type": "application/json",
            "x-api-key": "test",
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": MODEL,
            "max_tokens": 1000,
            "stream": True,
            "messages": [
                {"role": "user", "content": "Read file test_puzzle/hello.txt. What is the magic number? Reply only with the number."}
            ],
            "tools": TOOLS,
        },
        stream=True,
    )
    
    raw = resp.text
    events = parse_sse_events(raw)
    
    tool_calls = extract_tool_calls(events)
    text = extract_text(events)
    
    stop_reason = None
    for ev in events:
        data = ev.get("data", {})
        if isinstance(data, dict) and data.get("type") == "message_delta":
            stop_reason = data.get("delta", {}).get("stop_reason")
    
    print(f"  Stop reason: {stop_reason}")
    print(f"  Text: {text[:200]}")
    print(f"  Tool calls: {len(tool_calls)}")
    for tc in tool_calls:
        print(f"    - {tc['name']}(id={tc['id']}) input={json.dumps(tc['input'])}")
    
    return tool_calls, events, stop_reason


def step2_execute_tool(tc: dict) -> str:
    print(f"\nSTEP 2: Execute tool {tc['name']} locally")
    name = tc["name"]
    inp = tc["input"]
    
    if name == "Read":
        file_path = inp.get("file_path", "")
        try:
            with open(file_path) as f:
                content = f.read()
            print(f"  Read {len(content)} chars from {file_path}")
            return content
        except Exception as e:
            return f"Error: {e}"
    elif name == "Bash":
        cmd = inp.get("command", "")
        result = os.popen(cmd).read()
        print(f"  Bash result: {result[:200]}")
        return result
    else:
        return f"Unknown tool: {name}"


def step3_send_tool_result(tool_calls, tool_results):
    print(f"\nSTEP 3: Send tool results back")
    
    messages = [
        {"role": "user", "content": "Read file test_puzzle/hello.txt. What is the magic number? Reply only with the number."},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]}
                for tc in tool_calls
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tc["id"], "content": result}
                for tc, result in zip(tool_calls, tool_results)
            ],
        },
    ]
    
    resp = requests.post(
        f"{BASE_URL}/v1/messages",
        headers={
            "Content-Type": "application/json",
            "x-api-key": "test",
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": MODEL,
            "max_tokens": 1000,
            "stream": True,
            "messages": messages,
            "tools": TOOLS,
        },
        stream=True,
    )
    
    raw = resp.text
    events = parse_sse_events(raw)
    
    text = extract_text(events)
    tool_calls_2 = extract_tool_calls(events)
    
    stop_reason = None
    for ev in events:
        data = ev.get("data", {})
        if isinstance(data, dict) and data.get("type") == "message_delta":
            stop_reason = data.get("delta", {}).get("stop_reason")
    
    print(f"  Stop reason: {stop_reason}")
    print(f"  Text: '{text}'")
    print(f"  More tool calls: {len(tool_calls_2)}")
    
    return text


def main():
    tool_calls, events, stop_reason = step1_send_prompt()
    
    if stop_reason == "tool_use" and tool_calls:
        tool_results = []
        for tc in tool_calls:
            result = step2_execute_tool(tc)
            tool_results.append(result)
        
        final_text = step3_send_tool_result(tool_calls, tool_results)
        
        print("\n" + "=" * 60)
        print(f"FINAL ANSWER: {final_text}")
        print("=" * 60)
    else:
        print(f"\nDirect answer (no tool calls): {extract_text(events)}")


if __name__ == "__main__":
    main()
