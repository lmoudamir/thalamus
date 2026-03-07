"""Check what Claude Code received back from Read tool calls."""
import json
import os

base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs/2026-03-03_16-03-20/2026-03-03/pipeline/payloads')

files = sorted(os.listdir(base))
for fn in files:
    if not fn.endswith('_request.json'):
        continue
    rid = fn.replace('_request.json', '')
    req_path = os.path.join(base, fn)
    res_path = os.path.join(base, f'{rid}_response.json')
    
    with open(req_path) as f:
        req = json.load(f)
    msgs = req.get('messages', [])
    
    tcs = None
    text = ''
    if os.path.exists(res_path):
        with open(res_path) as f:
            res = json.load(f)
        tcs = res.get('tool_calls')
        text = res.get('response_text', '')
    
    tc_summary = ''
    if tcs:
        for tc in tcs:
            fn_info = tc.get('function', {})
            tc_summary = f'{fn_info.get("name","?")} args={fn_info.get("arguments","?")[:80]}'
    elif text:
        tc_summary = f'TEXT: {text[:100]}'
    else:
        tc_summary = 'EMPTY'
    
    last_user = ''
    for m in reversed(msgs):
        if m.get('role') == 'user':
            c = m.get('content', '')
            if isinstance(c, str):
                last_user = c[:120].replace('\n', '\\n')
            break
    
    print(f'{rid}: msgs={len(msgs):2d} => {tc_summary}')
    if 'error' in last_user.lower() or 'missing' in last_user.lower():
        print(f'  LAST_USER_MSG: {last_user}')
