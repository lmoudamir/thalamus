"""Analyze the message structure Claude Code sends - especially tool results."""
import json
import os

base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs/2026-03-03_16-03-20/2026-03-03/pipeline/payloads')

# Look at the request that followed an error
target = 'cc_6de42fe0d19f_request.json'  # msgs=16, after Bash error
path = os.path.join(base, target)
with open(path) as f:
    data = json.load(f)

msgs = data.get('messages', [])
print(f'Total messages: {len(msgs)}')
for i, m in enumerate(msgs):
    role = m.get('role', '?')
    content = m.get('content', '')
    
    if isinstance(content, list):
        print(f'\nmsg[{i}] role={role} content=LIST ({len(content)} items):')
        for j, item in enumerate(content):
            if isinstance(item, dict):
                itype = item.get('type', '?')
                if itype == 'tool_result':
                    print(f'  [{j}] type=tool_result id={item.get("tool_use_id")} is_error={item.get("is_error")}')
                    icontent = item.get('content', '')
                    if isinstance(icontent, str):
                        print(f'       content: {icontent[:200]}')
                    elif isinstance(icontent, list):
                        for k, sub in enumerate(icontent):
                            print(f'       [{k}]: {json.dumps(sub, ensure_ascii=False)[:200]}')
                elif itype == 'tool_use':
                    print(f'  [{j}] type=tool_use id={item.get("id")} name={item.get("name")}')
                    print(f'       input: {json.dumps(item.get("input",{}), ensure_ascii=False)[:200]}')
                elif itype == 'text':
                    print(f'  [{j}] type=text: {item.get("text","")[:100]}')
                else:
                    print(f'  [{j}] type={itype}: {json.dumps(item, ensure_ascii=False)[:150]}')
    elif isinstance(content, str):
        preview = content[:150].replace('\n', '\\n')
        print(f'\nmsg[{i}] role={role} content=STR({len(content)}): {preview}')
