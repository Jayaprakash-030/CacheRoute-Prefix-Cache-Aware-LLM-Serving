"""Single-request streaming client.

send_chat_request() sends one chat request, reads the streamed reply, and
returns a dict with the timings and token counts we record per request.
Run this file directly to try one request against a server.
"""

import argparse
import asyncio
import json
import time

import httpx


async def send_chat_request(client, url, messages, max_tokens, model="fake-model"):
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
        # Asks real vLLM to include token counts in the last chunk.
        "stream_options": {"include_usage": True},
    }
    result = {"start_time": time.time(), "status": "error", "pod": None}
    t0 = time.perf_counter()  # monotonic clock: only differences are meaningful
    t_first = None
    t_last = None
    reply_parts = []
    usage = {}

    try:
        async with client.stream("POST", url, json=payload) as resp:
            result["pod"] = resp.headers.get("x-served-by")
            if resp.status_code != 200:
                await resp.aread()
                result["error"] = f"HTTP {resp.status_code}: {resp.text[:200]}"
                return result

            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[len("data: "):]
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if choices:
                    piece = choices[0]["delta"].get("content")
                    if piece:
                        t_last = time.perf_counter()
                        if t_first is None:
                            t_first = t_last
                        reply_parts.append(piece)
    except httpx.HTTPError as e:
        result["error"] = repr(e)
        return result

    if t_first is None:
        result["error"] = "stream ended without any tokens"
        return result

    completion_tokens = usage.get("completion_tokens")
    result.update({
        "status": "ok",
        "ttft_s": t_first - t0,
        "duration_s": t_last - t0,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": completion_tokens,
        "tpot_s": (t_last - t_first) / (completion_tokens - 1)
        if completion_tokens and completion_tokens > 1 else None,
        "reply": "".join(reply_parts),
    })
    return result


async def main(args):
    messages = [{"role": "user", "content": " ".join(["word"] * args.prompt_words)}]
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        result = await send_chat_request(client, args.url, messages, args.max_tokens)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000/v1/chat/completions")
    parser.add_argument("--prompt-words", type=int, default=100)
    parser.add_argument("--max-tokens", type=int, default=10)
    asyncio.run(main(parser.parse_args()))
