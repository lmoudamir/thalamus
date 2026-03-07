"""Intercept a Claude Code request to capture the actual tool schemas."""
import json
import os
import subprocess
import sys

result = subprocess.run(
    ['claude', '-p', 'Say hello', '--dangerously-skip-permissions', '--output-format', 'json'],
    env={**os.environ, 'ANTHROPIC_BASE_URL': 'http://localhost:3013', 'ANTHROPIC_MODEL': 'gpt-5.3-codex-spark-preview-xhigh'},
    capture_output=True, text=True, timeout=30,
    cwd=os.path.dirname(os.path.abspath(__file__))
)

# Now check the latest payload log to find the tools
log_base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
sessions = sorted(os.listdir(log_base), reverse=True)
if not sessions:
    print("No log sessions found")
    sys.exit(1)

latest = sessions[0]
payloads = os.path.join(log_base, latest, '2026-03-03/pipeline/payloads')
if not os.path.exists(payloads):
    # try today
    import datetime
    today = datetime.date.today().isoformat()
    payloads = os.path.join(log_base, latest, today, 'pipeline/payloads')

if os.path.exists(payloads):
    files = sorted(os.listdir(payloads))
    for fn in files:
        if fn.endswith('_request.json'):
            with open(os.path.join(payloads, fn)) as f:
                data = json.load(f)
            msgs = data.get('messages', [])
            # Look at the MCP resource prompt to find tool names  
            for m in msgs:
                content = m.get('content', '')
                if isinstance(content, str) and 'MCP resources' in content and 'bash://run' in content:
                    # This is our injected tool prompt - extract what tools we mapped
                    print(f"Found tool prompt in {fn}, extracting...")
                    # Find lines like "Name: Bash" or "Resource: bash://run"
                    for line in content.split('\n'):
                        if line.strip().startswith('Name:'):
                            print(f'  {line.strip()}')
                    break
            break

# The real question: what tool names does Claude Code send in the tools array?
# Let's look at the pipeline code to find where tools are extracted
print("\n--- Claude Code stdout ---")
print(result.stdout[:500] if result.stdout else "(empty)")
print("\n--- Claude Code stderr ---")  
print(result.stderr[:500] if result.stderr else "(empty)")
