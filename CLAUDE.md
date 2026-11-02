# CLAUDE.md — Project 2: Prefix-Cache-Aware Routing for Multi-Replica vLLM

Read this file first. It is the single source of truth for project context, so you should not need to scan the whole repo. Open other files only when the task needs them. Keep this file current (see "Keeping this file updated").

## How to work with me

- Explain things in plain, simple language. Define any new technical term the first time it comes up.
- Check `plan.md` for the current phase and its checklist before suggesting next steps.
- Before reading a file, check the Repo map below to see whether it exists yet and what it holds.
- I don't want to implement everything at once, we have to go slowly so I can understand whats changes are happening in the code and I understand and follow the code development changes.

## What this project is

Run 4 copies of an LLM (one per GPU) with vLLM on a single-machine Kubernetes cluster, put a router in front of them, and prove with benchmarks that routing each request to the GPU that already has its prompt prefix cached beats plain round-robin.

- **Baseline:** round-robin (spread requests evenly, ignoring cache), via a plain Kubernetes Service.
- **Prefix-aware:** llm-d's EPP, which scores each pod on cache match and current load. Compared in two modes: approximate (guesses cache contents from past routing) and precise (vLLM reports its cache blocks via KV-events).
- **Workload:** many simulated users having multi-turn chats; every turn resends the full history.
- **Expected result:** much better TTFT and cache hit rate under load; TPOT roughly unchanged.

Project 2 of my LLM inference learning track (Notion: "LLM Inference & llm-d — Learning Track"). Project 1 was a tiny inference engine built from scratch.

## Hardware and environment

| Item | Value |
|---|---|
| Machine (4 replicas, benchmarks) | AWS `g5.12xlarge`, us-east-2: 4 × NVIDIA A10G, 24 GB each (96 GB total), 48 vCPUs, ~$5.67/hr |
| AWS quota | "Running On-Demand G and VT instances" raised to 48 vCPUs (approved 2026-11-02); enough for the g5.12xlarge. The g5.2xlarge phase is finished and no longer used. |
| Cost rule | Stop the instance at the end of every session. Budget alerts: $150/month, $25/day. |
| Cluster | k3s (lightweight Kubernetes), single node. No EKS. |
| Final layout | 1 node, 4 vLLM pods, each pod gets exactly 1 GPU |

## Stack

**Decided**
- Serving engine: vLLM (official Docker image), prefix caching enabled, one replica per GPU
- Orchestration: k3s
- GPU access in k3s: NVIDIA drivers + container toolkit + NVIDIA device plugin
- Baseline router: round-robin, using a plain Kubernetes Service
- Prefix-aware router: llm-d Router (EPP) in Standalone Mode with the Envoy sidecar (no separate gateway), 4 pods grouped in an InferencePool. Installed with Helm.
- Metrics: Prometheus scraping each vLLM pod's metrics endpoint (Grafana optional)
- Autoscaling: Kubernetes HPA, 1 to 4 replicas

**Open decisions** (move to Decision log once settled)
- Load generator: my own script vs vLLM's built-in benchmark tool
- HPA scaling signal: which metric (e.g. waiting requests per pod), and Prometheus Adapter vs KEDA to feed it to the HPA

## Repo map

Planned layout. Mark each entry as created when it exists, and add a one-line description of what's inside.

| Path | Purpose | Status |
|---|---|---|
| `CLAUDE.md` | This file: project context for AI assistants | created |
| `plan.md` | Phased plan with checklists | created |
| `README.md` | Public project overview and results | not created |
| `k8s/` | Kubernetes manifests: vLLM deployment, Service, router (Standalone), InferencePool, EPP config, Prometheus, HPA | in progress (`vllm-deployment.yaml`, `vllm-service.yaml` done) |
| `loadgen/` | Multi-turn load generator and fake vLLM test server (`fake_server.py`, `client.py`, `conversation.py`, `run_load.py`, `requirements.txt`, local `.venv`) | done (smoke-tested on a real pod) |
| `bench/results/` | Raw benchmark output, one folder per run | created (empty) |
| `bench/analysis/` | Notebooks or scripts that turn results into charts | created (empty) |
| `docs/` | Design notes and final benchmark report | created (`workload.md`, `aws-setup.md`, `epp-design.md`) |

## Key terms

- **Prefix caching:** vLLM reuses already-computed KV cache blocks when a new prompt starts with the same text as an earlier one. Only works from the start of the prompt, in 16-token blocks.
- **Replica / pod:** one running copy of vLLM. Each has its own separate KV cache.
- **TTFT:** time to first token (queue wait + prefill). Main metric prefix routing improves.
- **TPOT:** time per output token after the first (decode speed). Should barely change.
- **Cache hit rate:** share of prompt tokens found already cached. vLLM reports it.
- **P50 / P99:** typical request / slowest 1 in 100. Report percentiles, never averages alone.
- **Gateway:** an optional single front door that receives all traffic and asks EPP which pod to send each request to. We don't use one: the router bundles its own proxy (see Standalone Mode).
- **Standalone Mode:** the llm-d router deployed with its own Envoy sidecar proxy, with no separate gateway.
- **Envoy sidecar:** a small proxy running next to the router that forwards each request to the pod the router picked.
- **InferencePool:** a Kubernetes object grouping the pods that serve the same model, so EPP knows which pods to choose from.
- **EPP (Endpoint Picker):** llm-d's routing engine; scores pods on cache affinity, KV cache usage, and queue length.
- **KV-events:** messages vLLM sends as cache blocks are created and removed; precise mode uses them.
- **Hot-spotting:** too many requests piling onto one pod because it holds a popular prefix. The router must weigh load as well as cache match to avoid it.

## Future idea: agent workload (stretch, after Phase 4)

Chat is the core result. Once it is done, add a second workload profile that mimics AI agents. Agents suit prefix routing well: each step resends a growing history plus a long block of tool definitions, many agents share the same system prompt and tools, and pauses for tool calls may let a pod evict a conversation's cache before the next step. Keep the load generator configurable by workload profile so this is a settings change, not a rewrite. Details in `plan.md` under "Stretch: agent workload".

## Benchmark rules

- Same model, same workload, same request rates for both routers.
- Sweep request rate from light to past saturation; the interesting results are where the two routers separate.
- Record per run: router mode, request rate, TTFT P50/P99, TPOT P50/P99, cache hit rate, requests per pod.
- Each run saved under `bench/results/` with a short note on its settings.

## Current status

- **Phase:** 0 complete; Phase 1a complete (one vLLM pod serving Llama-3.1-8B on the g5.2xlarge, cache hits confirmed); Phase 2 complete (smoke test passed on the real pod)
- **Last session:** 2026-10-31: folder layout and `.gitignore` files created, repo pushed to GitHub, gateway decision made (Standalone Mode), `docs/workload.md` written, load generator built (`fake_server.py`, `client.py`, `conversation.py`, `run_load.py`) and tested against the fake server. g5.2xlarge launched (since terminated); k3s, NVIDIA toolkit and device plugin working, Kubernetes reports 1 GPU. Quota increase requested (pending), budget alerts set, Hugging Face access granted.
- **Session 2026-11-01:** Wrote `k8s/vllm-deployment.yaml` and `k8s/vllm-service.yaml`; pod served Llama-3.1-8B through the Service. KV cache 3.2 GiB = 26,176 tokens (1636 blocks of 16). Repeated 2,002-token prompt: cold 0.63 s vs warm 0.18 s, 2,000 of 2,002 tokens hit the cache. Fixed two crashes (see Gotchas). Added `/health` readiness probe. Load generator smoke test (11 requests, 3 conversations, run on the node against the ClusterIP): 0 errors, TTFT P50 0.098 s / P99 0.190 s, TPOT P50 35 ms, cache hit rate 85% (8,832 of 10,389 tokens); added `--model` to `run_load.py`. Clean startup with cached weights: ~103 s to Ready (first start ~3 min incl. 129 s download); needed for autoscaling.
- **Quota:** 48-vCPU quota approved 2026-11-02; small-machine plan dropped from `plan.md`.
- **Next step:** Phase 1b: launch the g5.12xlarge and get 4 replicas running (follow `docs/aws-setup.md`). On the laptop, the Phase 3 design note in `docs/` can be written alongside. Block size 64 now in the Deployment; real vLLM sends no `x-served-by` header, so requests-per-pod comes from each pod's `/metrics` counters. The g5.12xlarge launch hit "insufficient capacity" in us-east-2a/b/c on 2026-11-02; retry (default VPC now exists). Phase 3 design note done: `docs/epp-design.md`.

## Decision log

Newest first. One line each: date, decision, one-phrase reason.

- 2026-11-02: vLLM `--block-size=64` in all three runs (round-robin, approximate, precise), so only routing differs. Pin llm-d `v1.0.0` (GAIE v1.6.2, router chart and EPP v1.0.0); see `docs/epp-design.md`.
- 2026-11-02: Dropped the small-machine (g5.2xlarge) plan; all remaining GPU work on the g5.12xlarge. Quota for 48 vCPUs approved.
- 2026-11-01: Model is Llama-3.1-8B-Instruct (gated; needs `hf-token` secret). Matches my notes; ~16 GB weights leaves little KV cache on 24 GB, so keep `--max-model-len` modest.
- 2026-10-31: llm-d Router in Standalone Mode (Envoy sidecar), no separate gateway. Default tested path, simplest on single-node k3s. Revisit agentgateway only if time allows.
- 2026-10-31: Setup, model testing, and single-pod work start on a g5.2xlarge while the quota increase for the g5.12xlarge is pending.
- 2026-10-31: Prefix-aware routing uses llm-d's EPP; round-robin baseline is a plain Kubernetes Service.
- 2026-10-31: Project started. Hardware, k3s, vLLM, round-robin baseline, Prometheus, HPA fixed by the original plan.

## Gotchas and known issues

Add problems hit and how they were fixed, so they aren't debugged twice.

- A Service named `vllm` makes Kubernetes inject `VLLM_PORT=tcp://...` into pods, and vLLM crashes at the end of startup (`VLLM_PORT ... appears to be a URI`). Fix: `enableServiceLinks: false` in the pod spec. The "Unknown vLLM environment variable" startup warnings are the early sign.
- With one GPU, the default rolling update leaves the new pod `Pending` (the old pod holds the GPU). Fix: `strategy: Recreate`. Same on the big machine. Changing the strategy on an existing Deployment may need `kubectl patch ... rollingUpdate:null` first.
- Without a readiness probe, `1/1 Running` only means the container started, not that the model is loaded. Check the log for `Application startup complete`.
- `run_load.py` must be given `--model <served model name>`; real vLLM rejects the default `fake-model`. Run the load generator on the node (ClusterIP is not reachable from outside).
- Pasted long one-line commands wrap in the terminal and break; define shell variables and keep lines short.
- k3s already creates a `nvidia` RuntimeClass on its own when it finds the toolkit, so no manual RuntimeClass step is needed. The device plugin pod still needs `runtimeClassName: nvidia` patched in, or it can't see the GPU.
- When pasting multi-line shell blocks (heredocs) from chat, indentation can break the closing `EOF` and leave the shell stuck at a `>` prompt. Press Ctrl+C and use a single-line command instead.
- llm-d precise mode: vLLM `--block-size` must be 64 and match the router's `blockSizeTokens`. We use 64 in all runs.
- llm-d precise mode: the router's `modelName` must exactly match the served model, or render requests are rejected.
- `peakPrefillThroughput` in the router values was measured on H100s; re-measure on A10G with the guide's calibration step.
- The router runs as a single replica (its load accounting is per-process).
- Render endpoints (`/v1/*/render`) need a recent vLLM (the guide uses 0.30); check the image tag.

## Runbook

Commands confirmed to work go here (start/stop instance, deploy, run a benchmark).

Full step-by-step machine setup (launch, GPU check, k3s, device plugin, verify, stop/restart, troubleshooting): `docs/aws-setup.md`. Confirmed on the g5.2xlarge, 2026-10-31. Repeat it for every new instance and for the g5.12xlarge.

vLLM on the instance (from `k8s/`): create the `hf-token` secret (aws-setup.md step 6), then `sudo k3s kubectl apply -f vllm-deployment.yaml -f vllm-service.yaml`. Watch with `sudo k3s kubectl logs -f deploy/vllm` until `Application startup complete`. Test: `curl http://<CLUSTER-IP>:8000/v1/models` (IP from `kubectl get svc vllm`). Cache counters: `curl -s http://<CLUSTER-IP>:8000/metrics | grep -E "^vllm:prefix_cache_(queries|hits)_total"`.

## Keeping this file updated

At the end of each session, update: Current status, Repo map statuses, Decision log, Gotchas, and Runbook. Keep entries short. Remove anything no longer true.
