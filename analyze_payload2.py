"""Deep inspect failing request messages structure."""
import json
import os

base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs/2026-03-03_15-46-57/2026-03-03/pipeline/payloads')

fail_id = 'cc_0fe592c76594'
success_id = 'cc_844cc508a8e4'

for label, rid in [('LAST SUCCESS', success_id), ('FAILING', fail_id)]:
    req_path = os.path.join(base, f'{rid}_request.json')
    if not os.path.exists(req_path):
        print(f'{label}: NOT FOUND')
        continue
    with open(req_path) as f:
        data = json.load(f)
    
    msgs = data.get('messages', [])
    print(f'\n{"="*70}')
    print(f'{label} REQUEST {rid}')
    print(f'Total messages: {len(msgs)}')
    print(f'{"="*70}')
    
    for i, m in enumerate(msgs):
        role = m.get('role', '?')
        content = m.get('content', '')
        if isinstance(content, str):
            preview = content[:200].replace('\n', '\\n')
            clen = len(content)
        elif isinstance(content, list):
            preview = json.dumps(content[:1], ensure_ascii=False)[:200]
            clen = len(json.dumps(content))
        else:
            preview = str(content)[:200]
            clen = len(str(content))
        print(f'\n  msg[{i:2d}] role={role:10s} len={clen}')
        print(f'    preview: {preview}')
    
    res_path = os.path.join(base, f'{rid}_response.json')
    if os.path.exists(res_path):
        with open(res_path) as f:
            res = json.load(f)
        print(f'\n  --- RESPONSE ---')
        print(f'  text: {repr(res.get("text",""))[:200]}')
        tcs = res.get("tool_calls")
        if tcs:
            print(f'  tool_calls: {json.dumps(tcs, ensure_ascii=False)[:300]}')
        else:
            print(f'  tool_calls: {tcs}')
        print(f'  errors: {res.get("errors")}')
        print(f'  thinking: {repr(res.get("thinking",""))[:100]}')
