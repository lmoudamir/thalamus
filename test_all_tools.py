"""Test all key tools through the proxy: Read, Bash, Write, Glob, Grep."""
import json
import os
import subprocess

BASE_URL = "http://localhost:3013"
MODEL = "gpt-5.3-codex-spark-preview-xhigh"

ALL_TOOLS = [
    {"name": "Read", "description": "Read a file", "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}},
    {"name": "Write", "description": "Write a file", "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["file_path", "content"]}},
    {"name": "Edit", "description": "Edit a file", "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}}, "required": ["file_path", "old_string", "new_string"]}},
    {"name": "Bash", "description": "Execute command", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "Glob", "description": "Find files", "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}}, "required": ["pattern"]}},
    {"name": "Grep", "description": "Search content", "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}}, "required": ["pattern"]}},
]


def parse_sse(text):
    events = []
    cur = {}
    for line in text.split("\n"):
        if line.startswith("event: "): cur["event"] = line[7:]
        elif line.startswith("data: "):
            try: cur["data"] = json.loads(line[6:])
            except: cur["data"] = line[6:]
        elif line == "":
            if cur: events.append(cur); cur = {}
    if cur: events.append(cur)
    return events

def extract_tool_calls(events):
    tcs, cur = [], None
    for ev in events:
        d = ev.get("data", {})
        if not isinstance(d, dict): continue
        if d.get("type") == "content_block_start":
            b = d.get("content_block", {})
            if b.get("type") == "tool_use":
                cur = {"id": b["id"], "name": b["name"], "pj": ""}
        elif d.get("type") == "content_block_delta":
            delta = d.get("delta", {})
            if delta.get("type") == "input_json_delta" and cur:
                cur["pj"] += delta.get("partial_json", "")
        elif d.get("type") == "content_block_stop":
            if cur:
                try: cur["input"] = json.loads(cur["pj"])
                except: cur["input"] = {}
                del cur["pj"]
                tcs.append(cur); cur = None
    return tcs


def curl_post(payload):
    body = json.dumps(payload)
    result = subprocess.run(
        ["curl", "-s", "-N", f"{BASE_URL}/v1/messages",
         "-H", "Content-Type: application/json",
         "-H", "x-api-key: test",
         "-H", "anthropic-version: 2023-06-01",
         "-d", body],
        capture_output=True, text=True, timeout=20,
    )
    return result.stdout


def test_tool(prompt, expected_tool, expected_params):
    print(f"\n{'='*50}")
    print(f"TEST: {expected_tool} | Prompt: {prompt[:60]}...")
    print(f"Expected params: {expected_params}")
    
    try:
        raw = curl_post({"model": MODEL, "max_tokens": 1000, "stream": True,
            "messages": [{"role": "user", "content": prompt}], "tools": ALL_TOOLS})
    except subprocess.TimeoutExpired:
        print("  FAIL: Request timed out after 20s")
        return False
    
    events = parse_sse(raw)
    tcs = extract_tool_calls(events)
    
    if not tcs:
        text = ""
        for ev in events:
            d = ev.get("data", {})
            if isinstance(d, dict) and d.get("type") == "content_block_delta":
                delta = d.get("delta", {})
                if delta.get("type") == "text_delta":
                    text += delta.get("text", "")
        print(f"  FAIL: No tool calls! Text: {text[:200]}")
        return False
    
    tc = tcs[0]
    print(f"  Tool: {tc['name']}")
    print(f"  Input: {json.dumps(tc['input'], ensure_ascii=False)}")
    
    ok = True
    if tc["name"] != expected_tool:
        print(f"  FAIL: Expected tool {expected_tool}, got {tc['name']}")
        ok = False
    
    for param in expected_params:
        if param not in tc["input"]:
            print(f"  FAIL: Missing expected param '{param}'")
            ok = False
        else:
            print(f"  OK: param '{param}' = {json.dumps(tc['input'][param], ensure_ascii=False)[:100]}")
    
    if ok: print("  PASS!")
    return ok


results = {}
results["Read"] = test_tool(
    "Read the file test_puzzle/hello.txt and tell me the content.",
    "Read", ["file_path"]
)
results["Bash"] = test_tool(
    "Run the command 'echo hello world' and show me the output.",
    "Bash", ["command"]
)
results["Write"] = test_tool(
    "Write 'test content 123' to the file /tmp/thalamus_test_output.txt",
    "Write", ["file_path", "content"]
)
results["Glob"] = test_tool(
    "Find all .py files in the test_puzzle directory.",
    "Glob", ["pattern"]
)
results["Grep"] = test_tool(
    "Search for the word 'magic' in the test_puzzle directory.",
    "Grep", ["pattern"]
)

print(f"\n{'='*50}")
print("SUMMARY:")
for tool, passed in results.items():
    print(f"  {tool}: {'PASS' if passed else 'FAIL'}")
print(f"{'='*50}")
