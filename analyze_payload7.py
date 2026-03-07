"""Extract the original tool schemas Claude Code sends in the first request."""
import json
import os

base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs/2026-03-03_16-03-20/2026-03-03/pipeline/payloads')

files = sorted(os.listdir(base))
for fn in files:
    if not fn.endswith('_request.json'):
        continue
    req_path = os.path.join(base, fn)
    with open(req_path) as f:
        req = json.load(f)
    msgs = req.get('messages', [])
    if len(msgs) <= 15:
        extra = req.get('extra', {})
        tools_count = extra.get('tools_count', 0)
        print(f'{fn}: msgs={len(msgs)} tools_count={tools_count}')
        
        original_tools = req.get('original_tools')
        if original_tools and isinstance(original_tools, list):
            for t in original_tools[:5]:
                tname = t.get('name', '?')
                schema = t.get('input_schema', {})
                props = list(schema.get('properties', {}).keys()) if schema else []
                req_params = schema.get('required', [])
                print(f'  Tool: {tname} props={props} required={req_params}')
        break
