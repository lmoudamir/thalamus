"""Extract the actual tool names Claude Code sends in its requests."""
import json
import os

# Check the latest session logs for tool names
log_dirs = [
    'logs/2026-03-03_16-03-20',
    'logs/2026-03-03_15-46-57',
]

base_dir = os.path.dirname(os.path.abspath(__file__))

for log_dir in log_dirs:
    log_path = os.path.join(base_dir, log_dir, '2026-03-03/pipeline/claude-code.log')
    if not os.path.exists(log_path):
        continue
    print(f'\n=== {log_dir} ===')
    with open(log_path) as f:
        for line in f:
            if 'tools=' in line:
                print(line.strip()[:200])
                break

# More directly: look at the raw HTTP request to see tools array
# The pipeline receives tools in run_claude_messages_pipeline
# Let's check what tool names are in the system prompt from CC
for log_dir in log_dirs:
    payloads_dir = os.path.join(base_dir, log_dir, '2026-03-03/pipeline/payloads')
    if not os.path.exists(payloads_dir):
        continue
    for fn in sorted(os.listdir(payloads_dir)):
        if not fn.endswith('_request.json'):
            continue
        path = os.path.join(payloads_dir, fn)
        with open(path) as f:
            data = json.load(f)
        msgs = data.get('messages', [])
        if len(msgs) <= 15:
            # First request - check system messages for tool names
            for m in msgs:
                if m.get('role') == 'system':
                    content = m.get('content', '')
                    if isinstance(content, str) and 'tool' in content.lower() and len(content) > 5000:
                        # Find tool definitions
                        import re
                        tool_names = re.findall(r'"name":\s*"([^"]+)"', content)
                        if tool_names:
                            print(f'\nTool names from CC system prompt ({fn}):')
                            for tn in tool_names:
                                print(f'  - {tn}')
                            break
            break
