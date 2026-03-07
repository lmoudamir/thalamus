"""Look at the RAW Cursor response to find the URI that was parsed."""
import json
import os

base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs/2026-03-03_15-46-57/2026-03-03/pipeline/payloads')

empty_args_ids = ['cc_c74b84609cc6', 'cc_3640d67a94d5', 'cc_d006c87c6c3a', 'cc_f241ad61d453',
                  'cc_62aabf148bce', 'cc_e985c0ab094e', 'cc_e26551f036c4', 'cc_280ab03b8e57',
                  'cc_37f60fec4e9a', 'cc_4d4e304cba72']

for rid in empty_args_ids:
    req_path = os.path.join(base, f'{rid}_request.json')
    res_path = os.path.join(base, f'{rid}_response.json')
    
    if os.path.exists(req_path):
        with open(req_path) as f:
            req = json.load(f)
        msgs = req.get('messages', [])
        print(f'\n{rid}: msgs={len(msgs)}')
    
    if os.path.exists(res_path):
        with open(res_path) as f:
            res = json.load(f)
        
        raw_tc = res.get('raw_tool_calls') or res.get('proto_tool_calls')
        if raw_tc:
            print(f'  raw_tool_calls: {json.dumps(raw_tc, ensure_ascii=False)[:500]}')
        
        extra = res.get('extra')
        if extra:
            print(f'  extra: {json.dumps(extra, ensure_ascii=False)[:500]}')
        
        # Print ALL keys in response
        print(f'  response keys: {list(res.keys())}')
        
        # Dump full response (excluding large fields)
        compact = {k: v for k, v in res.items() if k != 'messages'}
        print(f'  full response: {json.dumps(compact, ensure_ascii=False)[:600]}')
