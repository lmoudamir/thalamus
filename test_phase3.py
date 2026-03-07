"""Phase 3 verification: Send a Claude Code request through thalamus-py proxy."""
import json
import httpx
import sys

payload = {
    "model": "claude-4.5-sonnet",
    "max_tokens": 4096,
    "stream": True,
    "tools": [
        {
            "name": "Bash",
            "description": "Execute shell commands",
            "input_schema": {
                "type": "object",
                "properties": {"command": {"type": "string"}, "description": {"type": "string"}},
                "required": ["command"],
                "additionalProperties": False,
            },
        },
        {
            "name": "Read",
            "description": "Read a file from the filesystem",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "offset": {"type": "number"}, "limit": {"type": "number"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "Write",
            "description": "Create or overwrite a file",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "contents": {"type": "string"}},
                "required": ["path", "contents"],
                "additionalProperties": False,
            },
        },
        {
            "name": "Glob",
            "description": "Search for files matching a glob pattern",
            "input_schema": {
                "type": "object",
                "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}},
                "required": ["pattern"],
                "additionalProperties": False,
            },
        },
        {
            "name": "TodoWrite",
            "description": "Create and manage task lists",
            "input_schema": {
                "type": "object",
                "properties": {"todos": {"type": "array"}},
                "required": ["todos"],
                "additionalProperties": False,
            },
        },
    ],
    "messages": [
        {"role": "user", "content": "List all Python files in the current directory."},
    ],
}

print("Sending request to thalamus-py proxy (streaming)...")
print()

tool_use_events = []
text_events = []
thinking_events = []
all_events = []

with httpx.Client(timeout=30) as client:
    with client.stream(
        "POST",
        "http://localhost:3013/v1/messages",
        json=payload,
        headers={"x-api-key": "dummy-key", "content-type": "application/json"},
    ) as response:
        print(f"HTTP status: {response.status_code}")
        if response.status_code != 200:
            print(f"Error: {response.read().decode()}")
            sys.exit(1)

        for line in response.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            data_str = line[6:]
            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")
            all_events.append(event)

            if event_type == "content_block_start":
                block = event.get("content_block", {})
                if block.get("type") == "tool_use":
                    tool_use_events.append({
                        "index": event.get("index"),
                        "id": block.get("id"),
                        "name": block.get("name"),
                        "input_parts": [],
                    })
                    print(f"TOOL_USE START: name={block.get('name')} id={block.get('id')}")

            elif event_type == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    text_events.append(delta.get("text", ""))
                elif delta.get("type") == "thinking_delta":
                    thinking_events.append(delta.get("thinking", ""))
                elif delta.get("type") == "input_json_delta":
                    pj = delta.get("partial_json", "")
                    if tool_use_events:
                        tool_use_events[-1]["input_parts"].append(pj)
                    print(f"TOOL_USE INPUT: {pj[:200]}")

            elif event_type == "message_delta":
                stop = event.get("delta", {}).get("stop_reason")
                print(f"STOP_REASON: {stop}")

print()
print(f"=== Summary ===")
print(f"Total SSE events: {len(all_events)}")
print(f"Text deltas: {len(text_events)}")
print(f"Thinking deltas: {len(thinking_events)}")
print(f"Tool use blocks: {len(tool_use_events)}")

if tool_use_events:
    for tu in tool_use_events:
        full_input = "".join(tu["input_parts"])
        try:
            parsed = json.loads(full_input)
        except:
            parsed = full_input
        print(f"  Tool: {tu['name']} id={tu['id']}")
        print(f"  Input: {json.dumps(parsed, indent=2)[:300]}")
    print()
    print("SUCCESS: thalamus-py proxy returned structured tool_use events!")
else:
    full_text = "".join(text_events)
    print(f"Text output: {full_text[:500]}")
    if full_text:
        print("NOTE: No tool calls - text-only response")
    else:
        print("WARNING: No output at all")
