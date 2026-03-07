"""Dump the raw tool definitions from Claude Code's first request.
Handles both streaming and non-streaming."""
import json
import os

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import uvicorn

app = FastAPI()
DUMP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_raw_cc_request.json')

@app.post("/v1/messages")
async def capture(request: Request):
    body = await request.json()
    with open(DUMP_FILE, 'w') as f:
        json.dump(body, f, indent=2, ensure_ascii=False)
    
    model = body.get("model", "test")
    stream = body.get("stream", False)
    
    if stream:
        async def sse_gen():
            yield 'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_cap","type":"message","role":"assistant","model":"' + model + '","content":[],"stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":10,"output_tokens":1}}}\n\n'
            yield 'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
            yield 'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"OK"}}\n\n'
            yield 'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n'
            yield 'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"output_tokens":1}}\n\n'
            yield 'event: message_stop\ndata: {"type":"message_stop"}\n\n'
        return StreamingResponse(sse_gen(), media_type="text/event-stream")
    else:
        return {
            "id": "msg_test",
            "type": "message", 
            "role": "assistant",
            "model": model,
            "content": [{"type": "text", "text": "OK"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 1}
        }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3099)
