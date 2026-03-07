"""Look at the response tool_calls to see what URI was parsed."""
import json
import os

base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs/2026-03-03_15-46-57/2026-03-03/pipeline/payloads')

success_ids = ['cc_c74b84609cc6', 'cc_3640d67a94d5', 'cc_d006c87c6c3a', 'cc_f241ad61d453',
               'cc_1505070092a6', 'cc_62aabf148bce', 'cc_e985c0ab094e', 'cc_0bca2a8e6b1c',
               'cc_16fe9a5de1bf', 'cc_e26551f036c4', 'cc_280ab03b8e57', 'cc_37f60fec4e9a',
               'cc_4d4e304cba72', 'cc_33fe5b24f6a4', 'cc_844cc508a8e4']

for rid in success_ids:
    res_path = os.path.join(base, f'{rid}_response.json')
    if not os.path.exists(res_path):
        continue
    with open(res_path) as f:
        res = json.load(f)
    tcs = res.get('tool_calls')
    text = res.get('text', '')
    if tcs:
        for tc in tcs:
            fn = tc.get('function', {})
            name = fn.get('name', '?')
            args = fn.get('arguments', '{}')
            print(f'{rid}: tool={name}  args={args[:200]}')
    elif text:
        print(f'{rid}: TEXT={text[:150]}')
    else:
        print(f'{rid}: EMPTY RESPONSE')
