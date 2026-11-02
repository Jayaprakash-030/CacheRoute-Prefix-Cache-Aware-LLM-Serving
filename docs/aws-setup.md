# AWS machine setup (from a brand new instance)

Follow this top to bottom whenever you launch a new machine. The project now uses the `g5.12xlarge` (4 GPUs); the steps were first confirmed on a 1-GPU `g5.2xlarge` on 2026-10-31 and are identical except for the GPU count. Expect 30–45 minutes, and the instance bills the whole time, so don't wander off.

**Stop vs Terminate.** *Stop* keeps the disk (k3s, plugin, downloaded models all survive; you pay only for the disk, about $16/month at 200 GB). *Terminate* deletes everything, and you come back to this file. Either is fine; terminating costs you the setup time next session, stopping costs the disk fee.

## Before you launch

- AWS region: **us-east-2 (Ohio)**.
- vCPU quota ("Running On-Demand G and VT instances"): `g5.12xlarge` needs 48. The quota was raised to 48 on 2026-11-02, so it can be launched (and only one at a time fits).
- A key pair (`.pem` file). Keep it **outside the repo**, and run `chmod 400 <file>.pem` once.

## 1. Launch the instance (EC2 console)

1. Check the region (top right) says us-east-2. EC2 → **Launch instance**.
2. **AMI:** search "Deep Learning OSS Nvidia Driver AMI GPU PyTorch", choose the **Ubuntu 22.04** one. An AMI is a prebuilt machine image; this one already has the NVIDIA driver and the NVIDIA container toolkit installed.
3. **Instance type:** `g5.12xlarge` (4 GPUs).
4. **Key pair:** select your existing one.
5. **Network:** allow SSH (port 22) from **My IP** only.
6. **Storage:** root volume about **200 GB gp3**. Model weights and container images are big.
7. Launch, wait until it shows "Running" and passes status checks, and copy the **public IP**. The public IP changes every time you stop and start the instance.

## 2. Connect and check the GPU

On your laptop:

```
ssh -i <file>.pem ubuntu@<public-ip>
```

On the instance:

```
nvidia-smi
nvidia-ctk --version
which nvidia-container-runtime
```

- `nvidia-smi` should list your GPU(s): one NVIDIA A10G (about 23 GB) on the small machine, four on the big one.
- `nvidia-ctk` and `which nvidia-container-runtime` must both print something. If either says "command not found", **stop here** and do not install k3s yet (k3s only looks for the toolkit when it starts).

## 3. Install k3s

k3s is a lightweight Kubernetes. Traefik (its built-in web router) is turned off because the llm-d router in Standalone Mode doesn't need it.

```
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable traefik" sh -
```

Check (the node should say `Ready` after a short wait):

```
sudo k3s kubectl get nodes
sudo grep -i nvidia /var/lib/rancher/k3s/agent/etc/containerd/config.toml
```

The second command should print lines mentioning an `nvidia` runtime. That means k3s found the toolkit.

## 4. Install the NVIDIA device plugin

The device plugin is a small program inside the cluster that tells Kubernetes how many GPUs the node has. Run these one at a time, each as a single line:

```
sudo k3s kubectl create -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.20.1/deployments/static/nvidia-device-plugin.yml
```

```
sudo k3s kubectl -n kube-system patch daemonset nvidia-device-plugin-daemonset --type merge -p '{"spec":{"template":{"spec":{"runtimeClassName":"nvidia"}}}}'
```

The second command makes the plugin run with the NVIDIA runtime, without which it can't see the GPU. You don't need to create a RuntimeClass: k3s creates one named `nvidia` by itself.

v0.20.1 was the latest release on 2026-10-31. Before reusing this, check [the releases page](https://github.com/NVIDIA/k8s-device-plugin/releases) for a newer version and swap it into the URL if you want.

## 5. Confirm Kubernetes sees the GPU

Wait about 30 seconds, then:

```
sudo k3s kubectl -n kube-system get pods | grep nvidia
sudo k3s kubectl describe node | grep -i nvidia.com/gpu
```

Success: the plugin pod is `Running` (1/1), and `nvidia.com/gpu: 1` shows twice (Capacity and Allocatable). On the big machine it should say **4**.

## 6. Create the Hugging Face token Secret

Llama 3.1 is gated, so the vLLM pod needs your Hugging Face token to download it. A Kubernetes Secret stores the token inside the cluster, and the Deployment reads it as `HF_TOKEN`. Skip this step if you are only checking the GPU.

1. Get a read-only token from huggingface.co → Settings → Access Tokens. Your account already has Llama access. Keep the token in a password manager.
2. Type `read -s HFT` and paste the token. Nothing shows on screen, and the token stays out of your shell history. Press Enter.
3. Create the `cacheroute` namespace (the folder all project objects live in; secrets belong to a namespace, so it must exist first), then the Secret inside it:

```
sudo k3s kubectl create namespace cacheroute
sudo k3s kubectl -n cacheroute create secret generic hf-token --from-literal=token="$HFT"
```

4. Check it exists (this prints the name, not the value): `sudo k3s kubectl -n cacheroute get secret hf-token`

The name `hf-token` and key `token` must match `k8s/vllm-deployment.yaml`. A *stopped* instance keeps the Secret; a *terminated* one loses it, so repeat this step on a new instance. Never put the token in the repo or in chat. If it leaks, revoke it on Hugging Face right away.

## 7. When you are done

EC2 console → select the instance → Instance state → **Stop instance** (keeps the disk) or **Terminate instance** (deletes it). Check the state reads Stopped or Terminated before you close the browser.

## Restarting a *stopped* instance

1. Instance state → **Start instance**, then copy the **new** public IP.
2. `ssh -i <file>.pem ubuntu@<new-ip>`
3. k3s starts on its own at boot. Run the checks from step 5 (plus `sudo k3s kubectl get nodes`) to confirm everything came back.

## Troubleshooting

- **Shell stuck at a `>` prompt** after pasting a multi-line block: the indentation broke the closing `EOF` of a heredoc. Press Ctrl+C and use single-line commands.
- **GPU line missing in step 5:** read the plugin's log with `sudo k3s kubectl -n kube-system logs daemonset/nvidia-device-plugin-daemonset`.
- **No `nvidia` runtime in the containerd file (step 3):** the toolkit wasn't present when k3s started. Run `sudo systemctl restart k3s` and check again.
- **SSH times out:** your home IP may have changed, so update the security group's SSH rule to your current IP, or check you copied the new public IP.
