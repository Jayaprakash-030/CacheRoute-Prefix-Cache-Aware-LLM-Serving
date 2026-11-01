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
| `concurrent_conversations` | Users active at the same time | ~50–100 |
| `request_rate` | New requests per second. This is the value we sweep | set per run |
| `arrival` | How requests are spaced: `poisson` (random gaps, same average rate) | `poisson` |
| `seed` | Random seed so every router sees the identical workload | set per run |

By turn 8 a prompt is roughly 1,500 or more tokens, large enough that recomputing it is expensive and a cache hit saves real time.

## Design rules

- **Same workload for every router.** The seed fixes the conversations, the text, and the arrival times. Round-robin, EPP approximate, and EPP precise are each run with the same seed.
- **Bursty arrivals.** Poisson arrivals produce bursts, which is where routers differ most.
- **Profile-based.** Workload shape lives in a profile (a set of the settings above), so adding an `agent` profile later is a settings change, not a rewrite.
- **Streaming requests.** Each request asks for a streamed response so we can see when the first token arrives.

## Recorded per request

| Field | Use |
|---|---|
| `conversation_id`, `turn` | Which chat and which turn |
| `start_time` | When the request was sent |
| `first_token_time` | When the first token arrived. TTFT = this minus `start_time` |
| `last_token_time` | When the last token arrived |
| `prompt_tokens`, `output_tokens` | Sizes. TPOT = (`last_token_time` − `first_token_time`) / (`output_tokens` − 1) |
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
