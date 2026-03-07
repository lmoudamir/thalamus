"""End-to-end puzzle analysis test: multi-turn tool calling flow.

Simulates Claude Code behavior:
1. Ask LLM to analyze 3 puzzle files
2. LLM calls Read for each file
3. We execute Read locally and return results
4. LLM calls Write to create analysis.md
5. We execute Write locally
6. Verify the analysis is correct
"""
import json
import os
import subprocess
import sys

BASE_URL = "http://localhost:3013"
MODEL = "gpt-5.3-codex-spark-preview-xhigh"
PUZZLE_DIR = os.path.join(os.path.dirname(__file__), "test_puzzle")

TOOLS = [
    {"name": "Read", "description": "Read a file from disk",
     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string", "description": "Path to file"}}, "required": ["file_path"]}},
    {"name": "Write", "description": "Write content to a file",
     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string", "description": "Path to file"}, "content": {"type": "string", "description": "Content to write"}}, "required": ["file_path", "content"]}},
    {"name": "Bash", "description": "Execute a shell command",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string", "description": "Shell command"}}, "required": ["command"]}},
    {"name": "Glob", "description": "Find files by pattern",
     "input_schema": {"type": "object", "properties": {"pattern": {"type": "string", "description": "Glob pattern"}}, "required": ["pattern"]}},
]

PROMPT = """Read these 3 files one at a time using the Read tool with RELATIVE paths:
- test_puzzle/alpha.py
- test_puzzle/beta.js  
- test_puzzle/gamma.sh

After reading ALL three files, write a brief analysis to test_puzzle/analysis.md using Write.
For each file state: filename, what code does, expected output.
Use ONLY relative paths. Do NOT use pwd or absolute paths."""


def curl_sse(payload):
    body = json.dumps(payload)
    result = subprocess.run(
        ["curl", "-s", "-N", f"{BASE_URL}/v1/messages",
         "-H", "Content-Type: application/json",
         "-H", "x-api-key: test",
         "-H", "anthropic-version: 2023-06-01",
         "-d", body],
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout


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


def extract_from_events(events):
    text_parts, tcs, cur_tc = [], [], None
    stop_reason = None
    for ev in events:
        d = ev.get("data", {})
        if not isinstance(d, dict): continue
        if d.get("type") == "content_block_start":
            b = d.get("content_block", {})
            if b.get("type") == "tool_use":
                cur_tc = {"id": b["id"], "name": b["name"], "pj": ""}
        elif d.get("type") == "content_block_delta":
            delta = d.get("delta", {})
            if delta.get("type") == "text_delta":
                text_parts.append(delta.get("text", ""))
            elif delta.get("type") == "input_json_delta" and cur_tc:
                cur_tc["pj"] += delta.get("partial_json", "")
        elif d.get("type") == "content_block_stop":
            if cur_tc:
                try: cur_tc["input"] = json.loads(cur_tc["pj"])
                except: cur_tc["input"] = {}
                del cur_tc["pj"]
                tcs.append(cur_tc); cur_tc = None
        elif d.get("type") == "message_delta":
            stop_reason = d.get("delta", {}).get("stop_reason")
    return "".join(text_parts), tcs, stop_reason


def execute_tool(tc):
    name, inp = tc["name"], tc["input"]
    if name == "Read":
        fp = inp.get("file_path", "")
        try:
            with open(fp) as f: return f.read()
        except Exception as e: return f"Error reading {fp}: {e}"
    elif name == "Write":
        fp = inp.get("file_path", "")
        content = inp.get("content", "")
        try:
            os.makedirs(os.path.dirname(fp) or ".", exist_ok=True)
            with open(fp, "w") as f: f.write(content)
            return f"Successfully wrote {len(content)} chars to {fp}"
        except Exception as e: return f"Error writing {fp}: {e}"
    elif name == "Bash":
        cmd = inp.get("command", "")
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            return r.stdout + r.stderr
        except Exception as e: return f"Error: {e}"
    elif name == "Glob":
        import glob
        pattern = inp.get("pattern", "")
        path = inp.get("path", ".")
        full = os.path.join(path, pattern) if path else pattern
        return "\n".join(glob.glob(full, recursive=True))
    return f"Unknown tool: {name}"


def main():
    messages = [{"role": "user", "content": PROMPT}]
    
    for turn in range(10):
        print(f"\n{'='*60}")
        print(f"TURN {turn + 1}")
        print(f"{'='*60}")
        
        try:
            raw = curl_sse({"model": MODEL, "max_tokens": 16000, "stream": True,
                           "messages": messages, "tools": TOOLS})
        except subprocess.TimeoutExpired:
            print("  TIMEOUT!")
            break
        
        text, tcs, stop_reason = extract_from_events(parse_sse(raw))
        
        if text:
            print(f"  Text ({len(text)} chars): {text[:200]}...")
        print(f"  Tool calls: {len(tcs)}")
        for tc in tcs:
            print(f"    - {tc['name']}({json.dumps(tc['input'], ensure_ascii=False)[:100]})")
        print(f"  Stop reason: {stop_reason}")
        
        if stop_reason == "end_turn" and not tcs:
            print("\n  DONE - LLM finished.")
            break
        
        if tcs:
            assistant_content = []
            if text:
                assistant_content.append({"type": "text", "text": text})
            for tc in tcs:
                assistant_content.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]})
            messages.append({"role": "assistant", "content": assistant_content})
            
            tool_results = []
            for tc in tcs:
                result = execute_tool(tc)
                print(f"    [Executed {tc['name']}] Result: {result[:100]}...")
                tool_results.append({"type": "tool_result", "tool_use_id": tc["id"], "content": result})
            messages.append({"role": "user", "content": tool_results})
        else:
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": "Continue. Use the tools to read the files and write the analysis."})
    
    analysis_path = os.path.join(PUZZLE_DIR, "analysis.md")
    if os.path.exists(analysis_path):
        print(f"\n{'='*60}")
        print("ANALYSIS.MD CONTENTS:")
        print(f"{'='*60}")
        with open(analysis_path) as f:
            print(f.read())
    else:
        print(f"\n  WARNING: {analysis_path} was not created!")


if __name__ == "__main__":
    main()
