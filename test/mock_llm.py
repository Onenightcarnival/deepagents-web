"""Minimal OpenAI-compatible mock LLM for end-to-end testing without a real
API key. Scripted behavior:
  - If the last message is not a tool result: call `execute` with an echo.
  - If a tool result is present: stream a short final text answer.
Run: uv run python test/mock_llm.py  (listens on :8901)
"""
import asyncio
import json
import os
import time
import uuid

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

PORT = int(os.environ.get("MOCK_PORT") or 8901)
# per-word delay when streaming the final answer; raise it (e.g. 0.8) to
# keep a run in-flight long enough to exercise detach/reattach flows
DELAY = float(os.environ.get("MOCK_DELAY_MS") or 30) / 1000

app = FastAPI()

USAGE = {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}


def sse(obj) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def make_chunk_factory():
    cid = "chatcmpl-" + uuid.uuid4().hex[:12]

    def chunk(delta, finish=None):
        return {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "mock-model",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }

    return chunk


@app.post("/{path:path}")
async def completions(path: str, request: Request):
    if not path.endswith("chat/completions"):
        return JSONResponse({"error": "not found"}, status_code=404)
    body = await request.json()
    messages = body.get("messages") or []
    has_tool_result = any(m.get("role") == "tool" for m in messages)

    if body.get("stream") is False:
        if has_tool_result:
            message = {"role": "assistant", "content": "命令已执行，见工具结果。"}
        else:
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_mock_1",
                    "type": "function",
                    "function": {
                        "name": "execute",
                        "arguments": json.dumps({"command": "echo hello-from-mock-agent"}),
                    },
                }],
            }
        return {
            "id": "chatcmpl-" + uuid.uuid4().hex[:12],
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "mock-model",
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": "stop" if has_tool_result else "tool_calls",
            }],
            "usage": USAGE,
        }

    async def gen():
        chunk = make_chunk_factory()
        if not has_tool_result:
            # stream a tool call to `execute`
            yield sse(chunk({"role": "assistant", "content": ""}))
            yield sse(chunk({"tool_calls": [{
                "index": 0, "id": "call_mock_1", "type": "function",
                "function": {"name": "execute", "arguments": ""},
            }]}))
            args = json.dumps({"command": "echo hello-from-mock-agent"})
            for piece in (args[:12], args[12:]):
                yield sse(chunk({"tool_calls": [{"index": 0, "function": {"arguments": piece}}]}))
            yield sse(chunk({}, "tool_calls"))
        else:
            yield sse(chunk({"role": "assistant", "content": ""}))
            for word in ["命令", "已执行", "，输出", "见上方", "工具结果。"]:
                yield sse(chunk({"content": word}))
                await asyncio.sleep(DELAY)
            yield sse(chunk({}, "stop"))
        # usage chunk (as sent by OpenAI with stream_options.include_usage)
        yield sse({
            "id": "chatcmpl-" + uuid.uuid4().hex[:12],
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "mock-model",
            "choices": [],
            "usage": USAGE,
        })
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
