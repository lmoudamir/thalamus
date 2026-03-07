"""Analyze failing and successful payload sizes."""
import json
import os
import sys

base = os.path.join(os.path.dirname(__file__), 'logs/2026-03-03_15-46-57/2026-03-03/pipeline/payloads')

fail_id = 'cc_0fe592c76594'
success_id = 'cc_844cc508a8e4'

for label, rid in [('FAILING', fail_id), ('LAST SUCCESS', success_id)]:
    req_path = os.path.join(base, f'{rid}_request.json')
    if not os.path.exists(req_path):
        print(f'{label}: {req_path} NOT FOUND')
        continue
    with open(req_path) as f:
        data = json.load(f)
    
    msgs = data.get('messages', [])
    total_chars = sum(len(json.dumps(m)) for m in msgs)
    print(f'=== {label} REQUEST {rid} ===')
    print(f'  Total messages: {len(msgs)}')
    print(f'  Total message chars: {total_chars}')
    print(f'  Approx tokens: ~{total_chars // 4}')
    print()
    for i, m in enumerate(msgs):
        role = m.get('role', '?')
        content = m.get('content', '')
        clen = len(json.dumps(content)) if isinstance(content, str) else len(json.dumps(content))
        print(f'  msg[{i:2d}] role={role:10s} len={clen:6d}')
    print()

    res_path = os.path.join(base, f'{rid}_response.json')
    if os.path.exists(res_path):
        with open(res_path) as f:
            res = json.load(f)
        print(f'  Response text len: {len(res.get("text",""))}')
        print(f'  Response tool_calls: {len(res.get("tool_calls",[]))}')
        if res.get("errors"):
            print(f'  Response errors: {res["errors"]}')
    print()
