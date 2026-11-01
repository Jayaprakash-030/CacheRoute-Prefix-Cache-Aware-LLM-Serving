# Workload design

What the load generator simulates, and the settings that define a run. These are starting values; revise them after the first smoke test and record any change in the CLAUDE.md Decision log.

## Idea

Many simulated users chat at once. Every turn resends the whole conversation so far, so each prompt starts with the previous turns word for word. That shared start is what prefix caching reuses, and what prefix-aware routing tries to send to the pod that already holds it.

## Settings

| Setting | Meaning | Starting value |
|---|---|---|
| `profile` | Workload type. `chat` now; `agent` is a later stretch (see plan.md) | `chat` |
| `system_prompt_tokens` | Length of the system prompt shared by all conversations | ~500 |
| `user_tokens_per_turn` | New text the user adds each turn | ~50–100 |
| `output_tokens` | Tokens the model generates per reply (`max_tokens`) | ~150 |
| `turns_per_conversation` | How many turns a chat lasts | 6–10 |
| `think_time_s` | Pause between a simulated user receiving a reply and sending their next message. Random within a range (seconds) | 1–5 |
| `conversation_rate` | New conversations started per second (average). This is the value we sweep | set per run |
| `duration_s` | Seconds during which new conversations start; running ones then finish | 30–60 |
| `arrival` | How conversation starts are spaced: `poisson` (random gaps, same average rate) | `poisson` |
| `seed` | Random seed so every router sees the identical workload | set per run |

By turn 8 a prompt is roughly 1,500 or more tokens, large enough that recomputing it is expensive and a cache hit saves real time.

## Design rules

- **Same workload for every router.** The seed fixes the conversations, the text, and the arrival times. Round-robin, EPP approximate, and EPP precise are each run with the same seed.
- **We set conversation arrivals; request rate and concurrency follow.** A conversation sends one request per turn, each after the previous reply and a think time, so the request rate is roughly `conversation_rate` × average turns, and the number of simultaneous users depends on how long conversations last. Arrivals ignore how busy the server is (an "open loop"), so a slow router shows up as growing latency, not as fewer requests.
- **Bursty arrivals.** Poisson arrivals produce bursts, which is where routers differ most.
- **The client keeps the history.** The chat API is stateless: the server remembers nothing between requests. The generator holds each conversation's message list in memory and resends all of it every turn.
- **Replies are stored verbatim.** The assistant's reply is appended to the history exactly as received. Any change would alter the prefix and cause cache misses that are our fault, not the router's.
- **Turns within a conversation are sequential.** Turn N+1 contains reply N, so it can't be sent until reply N has fully arrived (plus `think_time_s`). Concurrency comes from many conversations running at once.
- **Profile-based.** Workload shape lives in a profile (a set of the settings above), so adding an `agent` profile later is a settings change, not a rewrite.
- **Streaming requests.** Each request asks for a streamed response so we can see when the first token arrives.

## Recorded per request

| Field | Use |
|---|---|
| `conversation_id`, `turn` | Which chat and which turn |
| `start_time` | Wall-clock time the request was sent (for timeline charts) |
| `ttft_s` | Seconds from sending the request to the first token arriving (measured on a monotonic clock) |
| `duration_s` | Seconds from sending the request to the last token arriving |
| `prompt_tokens`, `completion_tokens` | Sizes, as reported by the server |
| `tpot_s` | (`duration_s` − `ttft_s`) / (`completion_tokens` − 1) |
| `pod` | Which pod served it (for requests-per-pod and hot-spotting) |
| `status` | Success or error |

Results are saved as one file per run under `bench/results/<run>/`, next to a short note of the settings used.

## Build order

1. This design note.
2. A fake streaming server on the laptop (no GPU).
3. The generator: one conversation, then many, then a request rate.
4. Per-request result recording.
5. Smoke test against the real single pod on the g5.2xlarge.

## Open questions

- Token counts here are approximate. The real counts depend on the chosen model's tokenizer, so we may measure and adjust after the model decision.
- How the generator learns which pod served a request (a response header set by the router, or the pod's own logs) is decided when we reach the router setup in Phase 3.
