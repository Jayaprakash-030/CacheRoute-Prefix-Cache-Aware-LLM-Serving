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
| Small machine (setup, model testing, single pod) | AWS `g5.2xlarge`, us-east-2: 1 × NVIDIA A10G (24 GB), 8 vCPUs, 32 GB RAM, ~$1.21/hr |
| Big machine (4 replicas, benchmarks) | AWS `g5.12xlarge`, us-east-2: 4 × NVIDIA A10G, 24 GB each (96 GB total), 48 vCPUs, ~$5.67/hr |
| AWS quota | "Running On-Demand G and VT instances" is 8 vCPUs; big machine needs 48 |
| Cost rule | Stop the instance at the end of every session. Budget alerts: $150/month, $25/day. |
| Cluster | k3s (lightweight Kubernetes), single node. No EKS. |
| Final layout | 1 node, 4 vLLM pods, each pod gets exactly 1 GPU |

## Stack

**Decided**
- Serving engine: vLLM (official Docker image), prefix caching enabled, one replica per GPU
- Orchestration: k3s
- GPU access in k3s: NVIDIA drivers + container toolkit + NVIDIA device plugin
- Baseline router: round-robin, using a plain Kubernetes Service
- Prefix-aware router: llm-d's Endpoint Picker (EPP), behind a gateway, with the 4 pods grouped in an InferencePool
- Metrics: Prometheus scraping each vLLM pod's metrics endpoint (Grafana optional)
- Autoscaling: Kubernetes HPA, 1 to 4 replicas

**Open decisions** (move to Decision log once settled)
- Gateway implementation to use with EPP (one of those supported by llm-d)
- Model: Llama-3-8B (matches my notes, but tight on 24 GB and gated on Hugging Face) vs a smaller ungated model such as a Qwen 1.5B–3B
- Load generator: my own script vs vLLM's built-in benchmark tool
- HPA scaling signal: which metric (e.g. waiting requests per pod), and Prometheus Adapter vs KEDA to feed it to the HPA

## Repo map

Planned layout. Mark each entry as created when it exists, and add a one-line description of what's inside.

| Path | Purpose | Status |
|---|---|---|
| `CLAUDE.md` | This file: project context for AI assistants | created |
| `plan.md` | Phased plan with checklists | created |
| `README.md` | Public project overview and results | not created |
| `k8s/` | Kubernetes manifests: vLLM deployment, Service, gateway, InferencePool, EPP config, Prometheus, HPA | created (empty) |
| `loadgen/` | Multi-turn load generator | created (empty) |
| `bench/results/` | Raw benchmark output, one folder per run | created (empty) |
| `bench/analysis/` | Notebooks or scripts that turn results into charts | created (empty) |
| `docs/` | Design notes and final benchmark report | created (empty) |

## Key terms

- **Prefix caching:** vLLM reuses already-computed KV cache blocks when a new prompt starts with the same text as an earlier one. Only works from the start of the prompt, in 16-token blocks.
- **Replica / pod:** one running copy of vLLM. Each has its own separate KV cache.
- **TTFT:** time to first token (queue wait + prefill). Main metric prefix routing improves.
- **TPOT:** time per output token after the first (decode speed). Should barely change.
- **Cache hit rate:** share of prompt tokens found already cached. vLLM reports it.
- **P50 / P99:** typical request / slowest 1 in 100. Report percentiles, never averages alone.
- **Gateway:** the single entry point that receives all traffic and asks EPP which pod to send each request to.
- **InferencePool:** a Kubernetes object grouping the pods that serve the same model, so EPP knows which pods to choose from.
- **EPP (Endpoint Picker):** llm-d's routing engine; scores pods on cache affinity, KV cache usage, and queue length.
- **KV-events:** messages vLLM sends as cache blocks are created and removed; precise mode uses them.
- **Hot-spotting:** too many requests piling onto one pod because it holds a popular prefix. The router must weigh load as well as cache match to avoid it.

## Benchmark rules

- Same model, same workload, same request rates for both routers.
- Sweep request rate from light to past saturation; the interesting results are where the two routers separate.
- Record per run: router mode, request rate, TTFT P50/P99, TPOT P50/P99, cache hit rate, requests per pod.
- Each run saved under `bench/results/` with a short note on its settings.

## Current status

- **Phase:** 0 (setup), not started
- **Last session:** none yet
- **Next step:** submit the quota increase from 8 to 48 vCPUs, set budget alerts, then start setup on the g5.2xlarge

## Decision log

Newest first. One line each: date, decision, one-phrase reason.

- 2026-10-31: Setup, model testing, and single-pod work start on a g5.2xlarge while the quota increase for the g5.12xlarge is pending.
- 2026-10-31: Prefix-aware routing uses llm-d's EPP; round-robin baseline is a plain Kubernetes Service.
- 2026-10-31: Project started. Hardware, k3s, vLLM, round-robin baseline, Prometheus, HPA fixed by the original plan.

## Gotchas and known issues

Add problems hit and how they were fixed, so they aren't debugged twice.

- (none yet)

## Runbook

Commands confirmed to work go here (start/stop instance, deploy, run a benchmark).

- (none yet)

## Keeping this file updated

At the end of each session, update: Current status, Repo map statuses, Decision log, Gotchas, and Runbook. Keep entries short. Remove anything no longer true.
