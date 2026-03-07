#!/usr/bin/env python3
"""TLM integration tests — uses claude -p for real end-to-end testing."""
import asyncio
import json
import time
import glob
import os
import subprocess

CLAUDE = "/Users/ruicheng.gu/.nvm/versions/node/v22.22.0/bin/claude"
LOG_BASE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
ENV = {
    **os.environ,
    "PATH": "/Users/ruicheng.gu/.nvm/versions/node/v22.22.0/bin:" + os.environ.get("PATH", ""),
    "ANTHROPIC_BASE_URL": "http://localhost:3013",
    "ANTHROPIC_API_KEY": "thalamus-proxy",
}


def latest_log_dir():
    dirs = sorted(glob.glob(os.path.join(LOG_BASE, "20*")))
    return dirs[-1] if dirs else None


def find_latest_payloads(layer, n=2):
    d = latest_log_dir()
    if not d:
        return []
    today = time.strftime("%Y-%m-%d")
    base = os.path.join(d, today, layer, "payloads")
    files = sorted(glob.glob(os.path.join(base, "*.json")))
    return files[-n:] if files else []


def print_payload_summary(path, max_chars=200):
    try:
        with open(path) as f:
            data = json.load(f)
        payload = data.get("payload", data)
        if isinstance(payload, dict):
            keys = list(payload.keys())
            print(f"    keys={keys}")
            for k in ("model", "response_text", "error", "tool_calls"):
                if k in payload:
                    v = str(payload[k])[:max_chars]
                    print(f"    {k}={v}")
        elif isinstance(payload, list):
            print(f"    events={len(payload)}")
    except Exception as e:
        print(f"    read error: {e}")


def run_claude_p(prompt, model="grok-code-fast-1", max_turns=3, timeout=45):
    """Run claude -p and return (stdout, stderr, elapsed_ms, returncode)."""
    cmd = [
        CLAUDE, "-p",
        "--model", model,
        "--max-turns", str(max_turns),
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--verbose",
        prompt,
    ]
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            cmd, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=timeout, env=ENV,
        )
        elapsed = int((time.monotonic() - t0) * 1000)
        return result.stdout, result.stderr, elapsed, result.returncode
    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - t0) * 1000)
        return "", f"TIMEOUT after {timeout}s", elapsed, -1


def test_identity():
    print("\n" + "=" * 60)
    print("TEST 1: Identity (claude -p)")
    print("=" * 60)
    stdout, stderr, ms, rc = run_claude_p("你是谁？一句话回答", timeout=60)
    print(f"  elapsed: {ms}ms | rc: {rc}")
    print(f"  stdout: {stdout.strip()[:300]}")
    if stderr.strip():
        print(f"  stderr: {stderr.strip()[:200]}")
    text = stdout.lower()
    has_cc = "claude" in text or "thalamus" in text
    only_cursor = "cursor" in text and "claude" not in text
    ok = has_cc and not only_cursor and rc == 0
    print(f"  RESULT: {'PASS' if ok else 'FAIL'} (claude/thalamus={has_cc})")
    return ok


def test_tool_call():
    print("\n" + "=" * 60)
    print("TEST 2: Tool Calling — Write (claude -p)")
    print("=" * 60)
    os.makedirs("/tmp/tlm-test", exist_ok=True)
    for f in ["/tmp/tlm-test/hello.txt"]:
        if os.path.exists(f):
            os.remove(f)

    stdout, stderr, ms, rc = run_claude_p(
        "用 Write tool 在 /tmp/tlm-test/ 创建 hello.txt，内容是 Hello World。只创建文件，不要做其他事。",
        max_turns=3, timeout=60,
    )
    print(f"  elapsed: {ms}ms | rc: {rc}")
    print(f"  stdout: {stdout.strip()[:300]}")
    if stderr.strip():
        print(f"  stderr: {stderr.strip()[:200]}")

    file_exists = os.path.exists("/tmp/tlm-test/hello.txt")
    if file_exists:
        with open("/tmp/tlm-test/hello.txt") as f:
            content = f.read()
        print(f"  file content: {repr(content[:100])}")
    else:
        content = ""
        print("  file NOT created")

    ok = file_exists and "Hello" in content
    print(f"  RESULT: {'PASS' if ok else 'FAIL'} (file_exists={file_exists})")
    return ok


def test_thinking():
    print("\n" + "=" * 60)
    print("TEST 3: Thinking visible (claude -p, composer-1.5)")
    print("=" * 60)
    stdout, stderr, ms, rc = run_claude_p("2+3=?", timeout=60)
    print(f"  elapsed: {ms}ms | rc: {rc}")
    print(f"  stdout: {stdout.strip()[:300]}")
    has_thinking = "thinking:" in stdout.lower() or "thinking" in stdout[:50].lower()
    has_answer = "5" in stdout
    ok = has_answer and rc == 0
    print(f"  RESULT: {'PASS' if ok else 'FAIL'} (has_thinking={has_thinking}, has_answer={has_answer})")
    return ok


def print_logs():
    print("\n" + "=" * 60)
    print("LOG INSPECTION")
    print("=" * 60)
    for layer in ["thalamus-api", "pipeline"]:
        files = find_latest_payloads(layer, n=4)
        print(f"\n  --- {layer} ({len(files)} recent) ---")
        for f in files:
            print(f"  {os.path.basename(f)}:")
            print_payload_summary(f)


def main():
    print("TLM Integration Tests (claude -p)")
    print(f"Claude: {CLAUDE}")
    print(f"Log dir: {latest_log_dir()}")

    results = {}
    for name, fn, retries in [
        ("identity", test_identity, 1),
        ("tool_call", test_tool_call, 2),
        ("thinking", test_thinking, 1),
    ]:
        for attempt in range(retries):
            ok = fn()
            results[name] = ok
            if ok:
                break
            if attempt < retries - 1:
                print(f"  RETRY ({attempt+2}/{retries})...")

    print_logs()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    all_pass = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  {name}: {status}")
    print(f"\n  Overall: {'ALL PASS' if all_pass else 'HAS FAILURES'}")


if __name__ == "__main__":
    main()
