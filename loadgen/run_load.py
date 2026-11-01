"""Load generator: starts new simulated conversations at a chosen rate.

New conversations arrive at random times (a Poisson process) with the given
average rate, regardless of how busy the server is. Each conversation then runs
its turns with run_conversation(). At the end it prints a summary and, with
--out, saves settings.json and requests.jsonl for the run.
"""

import argparse
import asyncio
import dataclasses
import datetime
import json
import random
import time
from collections import Counter
from pathlib import Path

import httpx

from conversation import ChatProfile, make_system_prompt, run_conversation


def percentile(values, p):
    # Linear interpolation between the two nearest sorted values.
    ordered = sorted(values)
    k = (len(ordered) - 1) * p / 100
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


async def run_load(url, profile, seed, conversation_rate, duration_s):
    arrivals = random.Random(f"{seed}-arrivals")
    system_prompt = make_system_prompt(profile, seed)
    # No cap on connections: a cap would make requests wait inside the client,
    # and that wait would be counted as server latency.
    limits = httpx.Limits(max_connections=None, max_keepalive_connections=None)

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0), limits=limits) as client:
        tasks = []
        start = time.monotonic()
        next_arrival = 0.0
        while True:
            # Gaps between Poisson arrivals are exponentially distributed.
            next_arrival += arrivals.expovariate(conversation_rate)
            if next_arrival > duration_s:
                break
            delay = start + next_arrival - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            conversation_id = len(tasks)
            tasks.append(asyncio.create_task(
                run_conversation(client, url, conversation_id, profile, system_prompt, seed)
            ))
        # No new conversations after duration_s; let the running ones finish.
        per_conversation = await asyncio.gather(*tasks)

    return [r for conversation in per_conversation for r in conversation]


def summarize(results, n_conversations, elapsed_s):
    ok = [r for r in results if r["status"] == "ok"]
    print(f"conversations started: {n_conversations}")
    print(f"requests: {len(results)} ({len(ok)} ok, {len(results) - len(ok)} errors)")
    print(f"elapsed: {elapsed_s:.1f}s  (average {len(results) / elapsed_s:.2f} requests/s over the run)")
    if not ok:
        return
    ttft = [r["ttft_s"] for r in ok]
    tpot = [r["tpot_s"] for r in ok if r["tpot_s"] is not None]
    print(f"TTFT  P50 {percentile(ttft, 50):.3f}s   P99 {percentile(ttft, 99):.3f}s")
    if tpot:
        print(f"TPOT  P50 {percentile(tpot, 50):.4f}s  P99 {percentile(tpot, 99):.4f}s")
    print("requests per pod:", dict(Counter(r["pod"] for r in ok)))


def save(out_dir, settings, results):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "settings.json").write_text(json.dumps(settings, indent=2))
    with open(out_dir / "requests.jsonl", "w") as f:
        for r in results:
            f.write(json.dumps({k: v for k, v in r.items() if k != "reply"}) + "\n")
    print(f"saved to {out_dir}")


async def main(args):
    profile = ChatProfile(
        system_prompt_tokens=args.system_tokens,
        user_tokens=tuple(args.user_tokens),
        output_tokens=args.output_tokens,
        turns=tuple(args.turns),
        think_time_s=tuple(args.think_time),
    )
    started_at = datetime.datetime.now().isoformat(timespec="seconds")
    t0 = time.monotonic()
    results = await run_load(args.url, profile, args.seed, args.conversation_rate, args.duration)
    elapsed_s = time.monotonic() - t0

    n_conversations = len({r["conversation_id"] for r in results})
    summarize(results, n_conversations, elapsed_s)
    if args.out:
        settings = {
            "note": args.note,
            "started_at": started_at,
            "url": args.url,
            "seed": args.seed,
            "conversation_rate": args.conversation_rate,
            "duration_s": args.duration,
            "elapsed_s": round(elapsed_s, 1),
            "profile": dataclasses.asdict(profile),
        }
        save(args.out, settings, results)


if __name__ == "__main__":
    d = ChatProfile()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000/v1/chat/completions")
    parser.add_argument("--conversation-rate", type=float, required=True,
                        help="new conversations per second (average)")
    parser.add_argument("--duration", type=float, default=30,
                        help="seconds during which new conversations start")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--system-tokens", type=int, default=d.system_prompt_tokens)
    parser.add_argument("--user-tokens", type=int, nargs=2, metavar=("MIN", "MAX"), default=d.user_tokens)
    parser.add_argument("--output-tokens", type=int, default=d.output_tokens)
    parser.add_argument("--turns", type=int, nargs=2, metavar=("MIN", "MAX"), default=d.turns)
    parser.add_argument("--think-time", type=float, nargs=2, metavar=("MIN", "MAX"), default=d.think_time_s)
    parser.add_argument("--out", help="folder to save settings.json and requests.jsonl into")
    parser.add_argument("--note", default="", help="short note stored in settings.json")
    asyncio.run(main(parser.parse_args()))
