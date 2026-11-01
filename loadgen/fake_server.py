"""Fake vLLM server for testing the load generator without a GPU.

Speaks a small part of the OpenAI chat API: POST /v1/chat/completions with
"stream": true. It waits a "prefill" delay that grows with prompt length (this
becomes TTFT), then streams reply tokens with a fixed gap (this becomes TPOT).
The pod name comes back in the x-served-by response header.
"""

import argparse
import asyncio
import json
import time

import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    # Field names follow the OpenAI chat API, which vLLM also uses.
    # This server always streams, so "stream" is accepted but not acted on.
    model: str = "fake-model"
    messages: list[Message]
    max_tokens: int = 16
    stream: bool = True


def count_tokens(messages):
    # Rough stand-in for a tokenizer: one word = one token.
    return sum(len(m.content.split()) for m in messages)


def sse(payload):
    # Server-sent events: each message is "data: <json>" followed by a blank line.
    return f"data: {json.dumps(payload)}\n\n"


def create_app(name, prefill_ms_per_token, token_ms):
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok", "pod": name}

    @app.post("/v1/chat/completions")
    async def chat_completions(body: ChatRequest):
        max_tokens = body.max_tokens
        prompt_tokens = count_tokens(body.messages)

        async def stream():
            # Prefill: the model "reads" the prompt before it can answer.
            await asyncio.sleep(prefill_ms_per_token * prompt_tokens / 1000)
            for i in range(max_tokens):
                yield sse({
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": body.model,
                    "choices": [{"index": 0, "delta": {"content": f"tok{i} "}, "finish_reason": None}],
                })
                await asyncio.sleep(token_ms / 1000)
            # Last chunk: finish reason plus token counts, like vLLM's usage report.
            yield sse({
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": body.model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": max_tokens,
                    "total_tokens": prompt_tokens + max_tokens,
                },
            })
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"x-served-by": name},
        )

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="fake-pod-0", help="pod name returned in x-served-by")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--prefill-ms-per-token", type=float, default=0.5)
    parser.add_argument("--token-ms", type=float, default=20)
    args = parser.parse_args()

    uvicorn.run(create_app(args.name, args.prefill_ms_per_token, args.token_ms), port=args.port)
