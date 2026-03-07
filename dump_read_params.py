"""Dump Read, Write, Edit full description blocks."""
import json
import os

log_base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
for session in sorted(os.listdir(log_base), reverse=True):
    payloads_dir = os.path.join(log_base, session)
    for root, dirs, files in os.walk(payloads_dir):
        if 'payloads' in root:
            req_files = sorted([f for f in files if f.endswith('_request.json')])
            if req_files:
                path = os.path.join(root, req_files[0])
                with open(path) as f:
                    data = json.load(f)
                msgs = data.get('messages', [])
                for m in msgs:
                    content = m.get('content', '')
                    if isinstance(content, str) and 'MCP resources' in content:
                        lines = content.split('\n')
                        for target in ['Read', 'Write', 'Edit']:
                            found = False
                            for i, line in enumerate(lines):
                                if f'  Name: {target}' in line:
                                    found = True
                                    start = max(0, i-1)
                                if found:
                                    print(lines[i])
                                    if i > start + 20 or (i > start + 3 and lines[i].strip() == ''):
                                        break
                            if found:
                                print(f'--- end {target} ---\n')
                        break
                break
    break
