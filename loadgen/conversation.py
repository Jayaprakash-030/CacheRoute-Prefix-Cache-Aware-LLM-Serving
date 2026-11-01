"""One simulated user having a multi-turn chat.

run_conversation() keeps the message history, sends it in full every turn,
appends each reply verbatim, and waits a think time between turns.
Run this file directly to play one conversation against a server.
"""

import argparse
import asyncio
import random
from dataclasses import dataclass

import httpx

from client import send_chat_request

# Stand-in vocabulary. One word is treated as roughly one token (see workload.md).
WORDS = (
    "time person year way day thing man world life hand part child eye woman place "
    "work week case point government company number group problem fact be have do "
    "say get make go know take see come think look want give use find tell ask "
    "seem feel try leave call good new first last long great little own other "
    "old right big high different small large next early young important few "
    "public bad same able"
).split()


@dataclass
class ChatProfile:
    # Ranges are (min, max), picked at random per conversation or per turn.
    system_prompt_tokens: int = 500
    user_tokens: tuple = (50, 100)
    output_tokens: int = 150
    turns: tuple = (6, 10)
    think_time_s: tuple = (1.0, 5.0)


def make_text(rng, n_words):
    return " ".join(rng.choices(WORDS, k=n_words))


def make_system_prompt(profile, seed):
    # Built once per run and shared by every conversation: the common prefix.
    return make_text(random.Random(f"{seed}-system"), profile.system_prompt_tokens)


async def run_conversation(client, url, conversation_id, profile, system_prompt, seed):
    # Each conversation has its own random generator, so its text and pauses do
    # not depend on how other conversations happen to be scheduled.
    rng = random.Random(f"{seed}-{conversation_id}")
    n_turns = rng.randint(*profile.turns)
    messages = [{"role": "system", "content": system_prompt}]
    results = []

    for turn in range(1, n_turns + 1):
        user_text = make_text(rng, rng.randint(*profile.user_tokens))
        messages.append({"role": "user", "content": user_text})

        result = await send_chat_request(client, url, messages, profile.output_tokens)
        result["conversation_id"] = conversation_id
        result["turn"] = turn
        results.append(result)

        if result["status"] != "ok":
            break  # no reply to add to the history, so the chat cannot go on

        messages.append({"role": "assistant", "content": result["reply"]})
        if turn < n_turns:
            await asyncio.sleep(rng.uniform(*profile.think_time_s))

    return results


async def main(args):
    profile = ChatProfile(
        system_prompt_tokens=args.system_tokens,
        output_tokens=args.output_tokens,
        turns=(args.turns, args.turns),
        think_time_s=(args.think_time, args.think_time),
    )
    system_prompt = make_system_prompt(profile, args.seed)
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        results = await run_conversation(client, args.url, 0, profile, system_prompt, args.seed)

    print(f"{'turn':>4} {'prompt_tokens':>13} {'ttft_s':>8} {'duration_s':>10}  pod  status")
    for r in results:
        if r["status"] == "ok":
            print(f"{r['turn']:>4} {r['prompt_tokens']:>13} {r['ttft_s']:>8.3f} {r['duration_s']:>10.3f}  {r['pod']}  ok")
        else:
            print(f"{r['turn']:>4} {'-':>13} {'-':>8} {'-':>10}  {r['pod']}  {r['error']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000/v1/chat/completions")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--turns", type=int, default=5)
    parser.add_argument("--think-time", type=float, default=0.5, help="seconds between turns")
    parser.add_argument("--system-tokens", type=int, default=500)
    parser.add_argument("--output-tokens", type=int, default=20)
    asyncio.run(main(parser.parse_args()))
