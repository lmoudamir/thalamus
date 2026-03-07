"""Extract the Read tool's full schema from payload logs."""
import json
import os

log_base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')

for session in sorted(os.listdir(log_base), reverse=True):
    session_dir = os.path.join(log_base, session)
    for root, dirs, files in os.walk(session_dir):
        if 'payloads' in root:
            req_files = sorted([f for f in files if f.endswith('_request.json')])
            for fn in req_files:
                path = os.path.join(root, fn)
                with open(path) as f:
                    data = json.load(f)
                tools = data.get('tools', [])
                if not tools:
                    continue
                print(f"\n=== {session}/{fn} - {len(tools)} tools ===\n")
                for t in tools:
                    name = t.get('name', '?')
                    schema = t.get('input_schema') or {}
                    props = schema.get('properties', {})
                    required = schema.get('required', [])
                    if name in ('Read', 'Write', 'Edit', 'Bash', 'Glob', 'Grep', 'Agent', 'WebFetch'):
                        print(f"Tool: {name}")
                        print(f"  required: {required}")
                        print(f"  properties:")
                        for pname, pdef in props.items():
                            ptype = pdef.get('type', '?')
                            desc_preview = (pdef.get('description', ''))[:80]
                            print(f"    {pname}: {ptype} {'[REQUIRED]' if pname in required else ''} - {desc_preview}")
                        print()
                # Only look at first request with tools
                if tools:
                    break
        if 'payloads' in root:
            break
    break
