"""Save the first request's tools array to a JSON file for inspection.
We intercept by adding temp logging in the pipeline."""
import json
import os
import subprocess
import time
import threading

# Add a one-shot endpoint to the running server to dump tools
# Actually simpler: modify the pipeline to save tools to a file

TOOLS_DUMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_cc_tools_dump.json')

# Remove old dump
if os.path.exists(TOOLS_DUMP):
    os.remove(TOOLS_DUMP)

# We'll do a direct approach: send a request with --max-turns 0 and capture from logs
# But actually let me just read the payload log request which has the messages
# and extract the tool names from the MCP resource prompt we injected

# From previous analysis, the tool prompt is in msg[8] of the first request
# Let me search all payload logs for the first request and extract the user message 
# that contains MCP resource descriptions

log_base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
for session in sorted(os.listdir(log_base), reverse=True):
    payloads_dir = os.path.join(log_base, session)
    # walk to find payloads
    for root, dirs, files in os.walk(payloads_dir):
        if 'payloads' in root:
            req_files = sorted([f for f in files if f.endswith('_request.json')])
            if req_files:
                path = os.path.join(root, req_files[0])
                with open(path) as f:
                    data = json.load(f)
                msgs = data.get('messages', [])
                # Find the MCP resource prompt
                for m in msgs:
                    content = m.get('content', '')
                    if isinstance(content, str) and 'MCP resources' in content:
                        print(f"Found MCP resource prompt in {session}/{req_files[0]}")
                        print(f"Length: {len(content)}")
                        # extract tool names and their params from the prompt
                        import re
                        resources = re.findall(r'Resource: (\S+)\n\s+Name: (\S+)', content)
                        for uri, name in resources:
                            print(f"  {name} -> {uri}")
                        break
                break
    break
