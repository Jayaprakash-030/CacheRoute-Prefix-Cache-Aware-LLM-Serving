# plan.md — Project 2: Prefix-Cache-Aware Routing for Multi-Replica vLLM

**Goal:** show, with measured numbers, that prefix-cache-aware routing (llm-d's EPP, approximate and precise modes) beats round-robin on TTFT and cache hit rate for multi-turn chat traffic across 4 vLLM replicas.

**Deliverables:** GitHub repo, benchmark report comparing routing strategies, resume bullet built from measured results.

**Estimated effort:** 30–45 hours, about 2–3 weeks at 2–3 hours a day.

**GPU budget:** aim for 15–25 hours on the big machine (~$85–140) plus 5–10 hours on the small one (~$6–12).

**Markers:** 💻 = laptop, no machine running. 🟢S = small machine, `g5.2xlarge` (1 A10G GPU, 8 vCPUs, ~$1.21/hr), fits the current 8-vCPU quota. 🟢B = big machine, `g5.12xlarge` (4 A10G GPUs, 48 vCPUs, ~$5.67/hr), needs the quota raised to 48.

Setup, model testing, and single-pod work happen on the small machine first, so problems get debugged at $1.21/hr instead of $5.67/hr.

---

## Phase 0 — Setup and decisions (3–5 hrs) 💻 + 🟢S

- [x] Request AWS quota increase: "Running On-Demand G and VT instances" from 8 to 48 vCPUs, with a short use case (can take hours to days, so do this first) -  Requested
- [x] Set up AWS budget alerts: monthly $150, daily $25 - Done
- [x] If Llama-3.1-8B is a model candidate, request access on Hugging Face now - access is already granted
- [x] Read llm-d's docs for its prefix-cache-aware "well-lit path" and pick a supported gateway - Standalone Mode, no gateway
- [x] Create the repo with the folder layout from CLAUDE.md - Done, pushed to GitHub
- [x] 🟢S Launch a g5.2xlarge using an AMI with NVIDIA drivers preinstalled (e.g. AWS Deep Learning AMI), in us-east-2
- [x] 🟢S Confirm the GPU is visible on the machine
- [x] 🟢S Install k3s, NVIDIA container toolkit, and the NVIDIA device plugin
- [x] 🟢S Confirm Kubernetes reports 1 GPU available on the node
- [x] Stop the instance; record every working setup command in the CLAUDE.md Runbook (you'll repeat them on the big machine)

**Done when:** k3s sees the GPU on the small machine, the quota request is submitted, and the router deployment choice is in the Decision log.

## Phase 1 — vLLM on k3s (4–8 hrs)

### 1a. One replica on the small machine 🟢S

- [x] Write a Deployment for vLLM: 1 replica, 1 GPU, prefix caching on
- [x] Store model weights on the instance's disk so pods don't re-download them on every start
- [x] Add a Kubernetes Service in front of the pod
- [x] Send a test request through the Service
- [x] Try each candidate model; note how much KV cache space vLLM reports at startup and how many tokens that holds (model chosen up front: Llama-3.1-8B, 3.2 GiB = 26,176 tokens)
- [x] Decide the model and add it to the Decision log
- [x] Confirm the pod exposes its metrics endpoint and that cache hit numbers change after repeated prompts
- [ ] Note how long the pod takes to start (first start ~3 min incl. 129 s download; clean cached restart still to time) and load the model (needed later for autoscaling)

**Done when:** one healthy pod serving the chosen model, with metrics visible.

### 1b. Four replicas on the big machine 🟢B (once the quota is approved)

- [ ] Launch a g5.12xlarge with the same AMI
- [ ] Repeat the setup using the Runbook commands
- [ ] Confirm Kubernetes reports 4 GPUs available on the node
- [ ] Scale the Deployment to 4 replicas and confirm each pod lands on its own GPU
- [ ] Send a test request to each pod individually and through the Service

**Done when:** 4 healthy pods, each answering requests on its own GPU.

If the quota is still pending after 1a, continue with Phase 2 and the laptop parts of Phase 3 on the small machine.

## Phase 2 — Load generator (4–6 hrs) 💻 then 🟢

- [x] Design the workload: number of users, turns per conversation, shared system prompt length, new text per turn, output length
- [x] Build the load generator: simulated users having multi-turn chats, each turn resending the full history, requests arriving at a set rate
- [x] Record per request: start time, time of first token, time of last token, token counts, which pod served it
- [x] Test it on the laptop against a simple stand-in server so no GPU time is spent
- [ ] 🟢S Run a smoke test against the single pod at a low rate

**Done when:** one command runs a multi-turn workload at a chosen rate and saves per-request results.

## Phase 3 — Routing with EPP (8–12 hrs) 💻 then 🟢S / 🟢B

- [ ] Write a short design note in `docs/`: how EPP scores pods (prefix match, KV cache usage, queue length), how the scores are combined, and how approximate and precise prefix modes differ
- [ ] Prepare the manifests on the laptop: router (Standalone Mode), InferencePool for the 4 vLLM pods, EPP with approximate prefix scoring
- [ ] 🟢S Optional: deploy router, InferencePool, and EPP with the single pod to check the pieces connect before moving to the big machine
- [ ] 🟢B Deploy the router (Standalone), InferencePool, and EPP on k3s
- [ ] 🟢B Confirm follow-up turns of one conversation land on the same pod (check EPP logs)
- [ ] 🟢B Confirm the round-robin baseline still works by sending traffic straight to the Kubernetes Service
- [ ] 🟢B Switch EPP to precise mode (vLLM sending KV-events) and confirm it routes correctly
- [ ] 🟢B Calibrate `peakPrefillThroughput` for the A10G (llm-d calibration step; the default was measured on H100s)
- [ ] Record how to switch between the three setups in the CLAUDE.md Runbook

**Done when:** round-robin, EPP approximate, and EPP precise can each be selected for a benchmark run, and routing decisions are visible in logs.

## Phase 4 — Metrics and benchmarks (5–8 hrs) 🟢B

- [ ] Deploy Prometheus to scrape all 4 vLLM pods (Grafana optional)
- [ ] Pick the list of request rates, from light load to past saturation
- [ ] Run the full sweep for round-robin
- [ ] Run the full sweep for EPP approximate mode
- [ ] Run the full sweep for EPP precise mode
- [ ] Repeat key rates at least twice to check results are stable
- [ ] Save every run under `bench/results/` with its settings
- [ ] Stop the instance; build charts on the laptop: TTFT P50/P99 vs rate, cache hit rate vs rate, requests per pod

**Done when:** charts show where the two routers separate, and whether prefix-aware ever hot-spots one pod.

## Phase 5 — Autoscaling (3–5 hrs) 🟢B

- [ ] Choose the scaling signal and how to feed it to the HPA
- [ ] Configure HPA for 1 to 4 replicas
- [ ] Run a load that ramps up then down; record replica count, TTFT, and cache hit rate over time
- [ ] Note what happens to cache hits when a new pod joins (it starts with an empty cache) and how long scale-up takes

**Done when:** a timeline chart shows scaling behavior under both routers.

## Phase 6 — Write-up (3–5 hrs) 💻

- [ ] Benchmark report in `docs/`: setup, workload, results, charts, what was surprising, limitations
- [ ] README: one-paragraph summary, architecture diagram, headline numbers, how to reproduce
- [ ] Resume bullet from measured numbers (XYZ format, max 2 lines)
- [ ] Tick off Project 2 in the Notion learning track
- [ ] Confirm the instance is stopped or terminated and no extra volumes are left running

**Done when:** someone could read the README and understand the result in under two minutes.

## Stretch: agent workload (only after Phase 4, if time and GPU budget allow)

Why: agents are a strong fit for prefix-aware routing. Each step resends a growing history plus a long tool-definition block, many agents share one system prompt, and tool-call pauses can let a pod evict a conversation's cache before the next step.

- [ ] In Phase 2, keep the load generator configurable by workload profile (chat is the default) so adding agents is a settings change
- [ ] Design the agent profile: long fixed prefix (system prompt + tool definitions), 5–10 steps per task, short tool-result text added per step, pause between steps
- [ ] Run a reduced sweep (round-robin vs the better EPP mode) on the agent profile
- [ ] Add an "agents" section to the report: does the gap widen, and does the pause between steps hurt cache hits?
- [ ] Optional reading: llm-d's experimental Agentic API and turn-priority fairness guides

Not part of the core deliverable. Do not let it delay Phases 3–6.

---

## Rough weekly targets

| Week | Phases |
|---|---|
| 1 | Phase 0, Phase 1a, Phase 2 (small machine) |
| 2 | Phase 1b, Phase 3, Phase 4 (big machine, if quota approved) |
| 3 | Phase 5, Phase 6 |

If the quota approval is slow, week 2 slides back; the small-machine work keeps progress going meanwhile.

## Every GPU session

1. Start the instance and check all pods are healthy
2. Do only the 🟢 tasks planned for that session, on the right machine
3. Save results and logs off the machine
4. Stop the instance
5. Update CLAUDE.md (status, decisions, gotchas, runbook)
