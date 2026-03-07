"""Compare raw_args between successful and failing tool calls.
Look at proto_tool_calls details from the server logs."""
import json
import os

base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs/2026-03-03_15-46-57/2026-03-03/pipeline/payloads')

# Successful (has command arg)
good_ids = ['cc_1505070092a6', 'cc_0bca2a8e6b1c', 'cc_16fe9a5de1bf', 'cc_844cc508a8e4']
# Failed (empty args)
bad_ids = ['cc_c74b84609cc6', 'cc_3640d67a94d5', 'cc_62aabf148bce']

for label, ids in [('GOOD (has args)', good_ids), ('BAD (empty args)', bad_ids)]:
    print(f'\n{"="*60}')
    print(f'{label}')
    print(f'{"="*60}')
    for rid in ids:
        res_path = os.path.join(base, f'{rid}_response.json')
        if not os.path.exists(res_path):
            print(f'{rid}: NOT FOUND')
            continue
        with open(res_path) as f:
            res = json.load(f)
        tcs = res.get('tool_calls', [])
        if tcs:
            for tc in tcs:
                fn = tc.get('function', {})
                print(f'\n{rid}:')
                print(f'  id:   {tc.get("id")}')
                print(f'  name: {fn.get("name")}')
                print(f'  args: {fn.get("arguments")}')
