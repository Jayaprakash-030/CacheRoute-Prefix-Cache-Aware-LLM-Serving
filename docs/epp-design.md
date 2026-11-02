# How the EPP picks a pod (Phase 3 design note)

Sources: llm-d docs (v0.7/v0.8 pages) and, more reliably, the guide config files in the `llm-d/llm-d` GitHub repo, release **v1.0.0** (`guides/optimized-baseline/` and `guides/precise-prefix-cache-routing/`), read 2026-11-02. Plugin names and defaults change between versions, so re-check against the version we deploy.

## The job

Four vLLM pods each have their own KV cache. For every incoming request, the EPP (Endpoint Picker) chooses which pod should handle it. A good choice is a pod that already has the start of the prompt cached (skips prefill work) and is not overloaded.

## Plugins: the EPP is built from small named parts

The EPP is one program. Inside it are many small building blocks called **plugins**, each doing one job (estimate cache contents, filter pods, score pods, pick the winner). All of them already ship inside the EPP, so we do not install any. A config file (an `EndpointPickerConfig`) lists which plugins to turn on, with their settings, and which ones run in which order. Changing the routing behavior means changing that file, not the code.

Kinds of plugin that appear in our configs:

| Kind | Job | Example |
|---|---|---|
| **Producer** | works out information about each pod for later plugins | `approx-prefix-cache-producer`, `precise-prefix-cache-producer`, `inflight-load-producer` |
| **Filter** | removes pods from consideration | `prefix-cache-affinity-filter` |
| **Scorer** | gives each pod a score from 0.0 to 1.0 | `token-load-scorer`, `kv-cache-utilization-scorer`, `queue-depth-scorer` |
| **Picker** | chooses the final pod (default: highest score) | `max-score-picker` |

## The pipeline: filter, score, pick

1. **Filter:** drop pods that must not get this request.
2. **Score:** each scorer rates the remaining pods. Each scorer has a weight, and the final score is the sum of score × weight (e.g. 0.8 at weight 2.0 plus 0.5 at weight 1.0 = 2.1).
3. **Pick:** the highest total wins.

## What llm-d's current guides actually configure (v1.0.0)

Both guides use the same pipeline. Only the producer differs.

```
producer (cache knowledge) ─► prefix-cache-affinity-filter ─► token-load-scorer ─► picker
```

- **`prefix-cache-affinity-filter`:** keeps only pods that already hold a good chunk of this prompt's prefix ("sticky" pods). It has a built-in load gate: if those pods are much slower than the rest (measured against `peakPrefillThroughput`), it lets other pods through. This is the main hot-spot protection.
- **`token-load-scorer`:** among the pods left, prefers the one with the least token load (input + output tokens being processed).
- **`inflight-load-producer`:** tracks that in-flight load. It lives inside one EPP process, which is why the router runs as a single replica.

So the guides do **not** use a weighted sum of "prefix match + KV cache usage + queue length", which is what I first wrote from older doc pages. Those scorers (`kv-cache-utilization-scorer`, `queue-depth-scorer`) exist, and we can add them later as an experiment.

## Approximate vs precise: how the router knows what a pod has cached

Only the producer plugin changes between the two guide configs.

| | Approximate | Precise |
|---|---|---|
| Producer | `approx-prefix-cache-producer` | `precise-prefix-cache-producer` (+ `token-producer`, `endpoint-notification-source`) |
| How it knows | Guesses. After each routing decision, assumes the chosen pod now holds that prompt | Pods report it: vLLM sends **KV-events** (a message whenever a cache block is created or evicted) |
| Prompt handling | Hashes blocks of the text, with characters standing in for tokens | Gets exact token IDs by asking the vLLM pods' own `/v1/*/render` endpoints (no separate tokenizer service in this version) |
| Remembers in | An in-memory table of recent prefixes per pod | An in-memory index fed by KV-events over ZeroMQ |
| Weakness | Drifts from reality when a pod evicts blocks | More setup: vLLM must publish events, `blockSizeTokens: 64` must match vLLM's `--block-size 64`, `modelName` must match exactly |

Precise mode also adds short-lived "speculative" entries right after a routing decision (`speculativeIndexing: true`), covering the gap before the real event arrives.

## What this means for our three runs

- **Round-robin baseline:** no EPP. A plain Kubernetes Service spreads requests evenly.
- **Approximate run:** the `optimized-baseline` guide config (4 plugins, shown above).
- **Precise run:** the `precise-prefix-cache-routing` guide config, plus vLLM changes (KV-events, block size 64, render endpoints on vLLM 0.30).
- **Our workload helps the test:** all conversations share one 500-word system prompt, so some prefix matches exist on every pod. The gain comes from the per-conversation history after it.
- **Changes needed from the guides:** `modelName` (guide uses Qwen3-32B; ours is Llama-3.1-8B-Instruct), `peakPrefillThroughput` (15926 was measured on H100s; re-measure on A10G), `matchLabels` (must match our pod labels), and the Hugging Face token secret.

## What has to be installed (from the v1.0.0 guide)

Install order in the guide, with what each step does:

1. **Gateway API Inference Extension (GAIE) manifests** (`kubectl apply -f .../v1-manifests.yaml`): adds new Kubernetes object types, including **InferencePool**, to the cluster. Without this, Kubernetes does not know what an InferencePool is.
2. **Namespace and Hugging Face secret:** a namespace is a named folder inside the cluster that groups related objects. The router can only see pods in its own namespace.
3. **Router via Helm** (`helm install` of `oci://ghcr.io/llm-d/charts/llm-d-router-standalone`, chart version `v0`): Helm is a package manager for Kubernetes. This one command creates the EPP, its Envoy sidecar, the InferencePool, and a Service. It takes two values files: a shared base file and the guide's file (the plugin configs above).
4. **Model servers:** the vLLM pods. The router finds them with `modelServers.matchLabels` (a label on the pods) and `targetPorts` (8000).

Clients then send requests to the router's Service (`<name>-epp`, port 80, forwarded to the Envoy sidecar on 8081) instead of a pod.

## vLLM changes the precise guide makes

Compared with our `vllm-deployment.yaml`:

| Change | Why |
|---|---|
| `--block-size=64` (ours: default 16) | cache blocks must match the router's `blockSizeTokens: 64` |
| `--enable-scale-out` | turns on the `/v1/*/render` endpoints the router uses to tokenize prompts |
| `--kv-events-config '{...zmq...}'` | makes vLLM publish a message whenever a cache block is added or removed |
| ports 5556 (events) and 5559 (replay) | where the router connects to receive and replay those events |
| env `POD_IP`, `POD_PORT`, `KV_EVENTS_ENDPOINT`, `KV_EVENTS_REPLAY_ENDPOINT` | fill in the `--kv-events-config` template; the topic also contains the model name |
| pod label `llm-d.ai/guide: ...` | matched by the router (we can instead set `matchLabels` to our own `app: vllm`) |

The approximate guide's model-server files were not read yet; I expect it to need only the label.

## Versions to pin

The guide's own defaults float, but its `v1.0.0` release tag fixes them (read from `guides/env.sh` at that tag). We use these exact versions and name them in the report:

| Piece | Version |
|---|---|
| llm-d repo / guides | `v1.0.0` (use this tag, not `main`) |
| GAIE manifests (InferencePool CRDs) | `v1.6.2` |
| Router Helm chart (`llm-d-router-standalone`) | `v1.0.0` |
| EPP image (`ghcr.io/llm-d/llm-d-router-endpoint-picker`) | `v1.0.0` |
| vLLM image | `vllm/vllm-openai:v0.30.0` (already running; guide needs 0.30 for render endpoints) |

## Decisions

- **2026-11-02: `--block-size=64` in all three runs** (round-robin, approximate, precise). Block size changes how much of a prompt can be cached, so only routing may differ between runs.
- **Namespace (open):** our vLLM runs in `default`; the router must share its namespace. Probably one namespace (e.g. `cacheroute`) for everything.

## Approximate guide's vLLM settings

Nothing special: its model server needs no KV-events, no render endpoints and no block-size flag. Only the pod label (or our own `matchLabels`) matters. So the same vLLM Deployment (with `--block-size=64`) serves all three runs; precise mode adds the KV-events flags, ports and env vars on top.

## Calibrating `peakPrefillThroughput` on the A10G

- The guide's value (15928) is for Qwen3-32B on H100s, so it is wrong for us. `peakPrefillThroughput` is prompt tokens per second a pod can prefill, and the filter uses it to turn a pod's in-flight tokens into a predicted TTFT.
- **How:** `guides/recipes/router/calibration/calibrate.sh` runs a short Kubernetes Job that sends 5 warmup + 20 measured requests of `CHUNK_SIZE` random tokens (random, so the cache misses and true prefill is measured). The result is `CHUNK_SIZE / median(TTFT)`. It only prints the number; we put it in the router values file, run `helm upgrade`, and restart the EPP.
- **Needs** the stack running (router + a pod), and `CHUNK_SIZE` must equal vLLM `--max-num-batched-tokens`.
- **Risk to check on the machine:** the default chunk is 8192, but our `--max-model-len` is 8192, so a request of 8192 tokens plus output may be rejected. We may set `--max-num-batched-tokens` (and chunk) to something like 4096 and re-measure. The value depends on the chunk size, so use the same settings for the benchmark.
- Runs on the machine, so it is in Phase 3 machine work.

## Requests per pod

Real vLLM sends no `x-served-by` header, so the load generator can't see which pod answered. The guide itself reads the counters from each pod instead: `vllm:request_success_total` and `vllm:prefix_cache_hits_total` / `queries_total` on each pod's `/metrics` (via Prometheus in Phase 4, or the `pod_metrics` check in the guide). We compare these counters before and after each run.

## Still to verify (needs the machine)

- [x] Exact plugin names and `EndpointPickerConfig` YAML.
- [x] Install order, chart, and vLLM flags for precise mode.
- [x] Approximate guide's model-server settings.
- [x] Versions to pin.
- [x] How to calibrate `peakPrefillThroughput` (procedure known; the run itself needs the machine).
- [x] Requests-per-pod source (pod metrics).
- [ ] Run the render check and the guide's shared-prefix test on our pods.
- [ ] Choose the namespace and rewrite our manifests for it.
