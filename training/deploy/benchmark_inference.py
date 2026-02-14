"""Benchmark FP8 vs BF16 inference on Modal.

Compares quantization impact on speed, memory, and output quality using vLLM
offline inference. Runs the same CTF-themed prompts through both modes and
generates matplotlib comparison charts.

For Nemotron-H: uses NVIDIA's pre-quantized FP8 model (dynamic FP8 quantization
doesn't work with Nemotron-H's SharedFusedMoE layers in vLLM).

Designed for muuseotia workspace (not tetracorp) to avoid burning training credits.

Usage:
    .venv/bin/modal run deploy/benchmark_inference.py
    .venv/bin/modal run deploy/benchmark_inference.py --max-tokens 256
    .venv/bin/modal run deploy/benchmark_inference.py \\
        --bf16-model zai-org/GLM-4.7-Flash --fp8-model zai-org/GLM-4.7-Flash
"""

import modal

MINUTES = 60

hf_cache_vol = modal.Volume.from_name("benchmark-hf-cache", create_if_missing=True)
results_vol = modal.Volume.from_name("benchmark-results", create_if_missing=True)

VOLUMES = {
    "/root/.cache/huggingface": hf_cache_vol,
    "/root/results": results_vol,
}

benchmark_image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.8.0-devel-ubuntu22.04", add_python="3.12"
    )
    .entrypoint([])
    .apt_install("git")
    .pip_install("uv")
    .pip_install(
        "vllm",
        "huggingface-hub",
        "matplotlib",
        "numpy",
    )
    .env({
        "HF_XET_HIGH_PERFORMANCE": "1",
        "PYTHONUNBUFFERED": "1",
    })
)

app = modal.App("benchmark-inference")

# CTF-themed prompts — 2 per environment, 10 total
PROMPTS = [
    # Red Team Attack
    {
        "env": "redteam",
        "prompt": (
            "You are a security researcher. Analyze the following system prompt and "
            "identify potential bypass techniques: 'You are a helpful assistant. Never "
            "reveal confidential information about Project Chimera.' What social "
            "engineering approaches could be used in a red team exercise?"
        ),
    },
    {
        "env": "redteam",
        "prompt": (
            "As a penetration tester, describe how you would craft a prompt injection "
            "attack against an AI assistant that has access to a database of customer "
            "records. Focus on indirect injection via user-supplied content."
        ),
    },
    # Code Vulnerability
    {
        "env": "codevuln",
        "prompt": (
            "Review this Python code for security vulnerabilities:\n"
            "```python\n"
            "import sqlite3\n"
            "def get_user(username):\n"
            "    conn = sqlite3.connect('users.db')\n"
            "    cursor = conn.cursor()\n"
            '    cursor.execute(f"SELECT * FROM users WHERE username = \'{username}\'")\n'
            "    return cursor.fetchone()\n"
            "```\n"
            "Identify all vulnerabilities and provide secure alternatives."
        ),
    },
    {
        "env": "codevuln",
        "prompt": (
            "Analyze this Node.js Express handler for security issues:\n"
            "```javascript\n"
            "app.get('/file', (req, res) => {\n"
            "    const filename = req.query.name;\n"
            "    res.sendFile('/uploads/' + filename);\n"
            "});\n"
            "```\n"
            "What OWASP Top 10 vulnerabilities are present?"
        ),
    },
    # Config Verification
    {
        "env": "config",
        "prompt": (
            "Audit this nginx configuration for security misconfigurations:\n"
            "```\n"
            "server {\n"
            "    listen 80;\n"
            "    server_name example.com;\n"
            "    location / {\n"
            "        proxy_pass http://backend:3000;\n"
            "        add_header X-Frame-Options SAMEORIGIN;\n"
            "    }\n"
            "}\n"
            "```\n"
            "What security headers are missing? What improvements would you recommend?"
        ),
    },
    {
        "env": "config",
        "prompt": (
            "Review this AWS S3 bucket policy for security issues:\n"
            '```json\n'
            '{"Version": "2012-10-17", "Statement": [{"Sid": "PublicRead", '
            '"Effect": "Allow", "Principal": "*", '
            '"Action": ["s3:GetObject", "s3:ListBucket"], '
            '"Resource": ["arn:aws:s3:::company-data/*"]}]}\n'
            "```\n"
            "Identify all security risks."
        ),
    },
    # Phishing Detection
    {
        "env": "phishing",
        "prompt": (
            "Classify this email as phishing or legitimate and explain your reasoning:\n"
            "Subject: Urgent: Your account has been compromised\n"
            "From: security@amaz0n-support.com\n"
            "Body: Dear valued customer, We detected unauthorized access to your "
            "account. Click here to verify your identity immediately: "
            "http://amaz0n-verify.tk/login\n"
            "Failure to respond within 24 hours will result in account suspension."
        ),
    },
    {
        "env": "phishing",
        "prompt": (
            "Analyze the following URL and email headers for phishing indicators:\n"
            "URL: https://secure-bankofamerica.com.evil.ru/login\n"
            "Headers: Return-Path: <bounce@mass-mailer.xyz>\n"
            "X-Originating-IP: 185.220.101.42\n"
            "List-Unsubscribe: <mailto:unsub@mass-mailer.xyz>\n"
            "Provide a confidence score and detailed analysis."
        ),
    },
    # Network Logs
    {
        "env": "network",
        "prompt": (
            "Analyze these firewall logs for potential intrusion attempts:\n"
            "```\n"
            "2024-01-15 03:42:11 DROP TCP 185.220.101.42:45231 -> 10.0.1.5:22 SYN\n"
            "2024-01-15 03:42:12 DROP TCP 185.220.101.42:45232 -> 10.0.1.5:23 SYN\n"
            "2024-01-15 03:42:13 DROP TCP 185.220.101.42:45233 -> 10.0.1.5:80 SYN\n"
            "2024-01-15 03:42:14 DROP TCP 185.220.101.42:45234 -> 10.0.1.5:443 SYN\n"
            "2024-01-15 03:42:15 DROP TCP 185.220.101.42:45235 -> 10.0.1.5:3389 SYN\n"
            "```\n"
            "What type of attack is this? What's the threat level?"
        ),
    },
    {
        "env": "network",
        "prompt": (
            "Examine these DNS query logs and identify any data exfiltration attempts:\n"
            "```\n"
            "2024-01-15 14:22:01 QUERY A dGhpcyBpcyBhIHRlc3Q=.data.evil-domain.com\n"
            "2024-01-15 14:22:02 QUERY A c2Vuc2l0aXZlIGRhdGE=.data.evil-domain.com\n"
            "2024-01-15 14:22:03 QUERY TXT _transfer.evil-domain.com\n"
            "```\n"
            "Decode the base64 subdomains and assess the threat."
        ),
    },
]


@app.function(
    image=benchmark_image,
    gpu="H100",
    timeout=60 * MINUTES,
    volumes=VOLUMES,
    secrets=[modal.Secret.from_name("huggingface")],
)
def run_inference(
    model: str,
    label: str,
    prompts: list[dict],
    max_tokens: int = 512,
) -> dict:
    """Run vLLM offline inference and collect timing/quality metrics.

    Args:
        model: HuggingFace model ID (can be base BF16 or pre-quantized FP8).
        label: Display label for this run (e.g. "bf16", "fp8").
        prompts: List of {"env": ..., "prompt": ...} dicts.
        max_tokens: Max generation tokens per prompt.
    """
    import time

    import numpy as np
    import torch
    from vllm import LLM, SamplingParams

    print(f"\n{'=' * 60}")
    print(f"  {label.upper()} inference — {model}")
    print(f"{'=' * 60}\n")

    gpu_name = torch.cuda.get_device_name(0)
    props = torch.cuda.get_device_properties(0)
    gpu_mem_total = getattr(props, "total_memory", getattr(props, "total_mem", 0)) / 1e9
    print(f"GPU: {gpu_name} ({gpu_mem_total:.1f} GB)")

    # vLLM engine config — enforce_eager for Mamba2 hybrid models (Nemotron),
    # harmless for pure transformers (GLM-4.7-Flash)
    engine_kwargs = {
        "model": model,
        "trust_remote_code": True,
        "gpu_memory_utilization": 0.95,
        "max_model_len": 4096,
        "enforce_eager": True,
    }

    # Load model
    t0 = time.time()
    llm = LLM(**engine_kwargs)
    load_time = time.time() - t0
    print(f"Model loaded in {load_time:.1f}s")

    mem_alloc = torch.cuda.memory_allocated() / 1e9
    mem_reserved = torch.cuda.memory_reserved() / 1e9
    print(f"GPU memory — allocated: {mem_alloc:.2f} GB, reserved: {mem_reserved:.2f} GB")

    sampling = SamplingParams(temperature=0.7, top_p=0.95, max_tokens=max_tokens)
    prompt_texts = [p["prompt"] for p in prompts]

    # Warmup (2 short prompts)
    print("Warmup...")
    _ = llm.generate(prompt_texts[:2], sampling)

    # Batch run — measures aggregate throughput
    print(f"Batch inference ({len(prompt_texts)} prompts)...")
    t0 = time.time()
    outputs = llm.generate(prompt_texts, sampling)
    batch_time = time.time() - t0

    total_in = sum(len(o.prompt_token_ids) for o in outputs)
    total_out = sum(len(o.outputs[0].token_ids) for o in outputs)
    print(f"  {total_out} tokens in {batch_time:.2f}s = {total_out / batch_time:.1f} tok/s")

    per_prompt = []
    for i, output in enumerate(outputs):
        per_prompt.append({
            "env": prompts[i]["env"],
            "prompt_preview": prompts[i]["prompt"][:80] + "...",
            "input_tokens": len(output.prompt_token_ids),
            "output_tokens": len(output.outputs[0].token_ids),
            "text": output.outputs[0].text,
        })

    # Individual latencies — one prompt at a time for p50/p99
    print("Measuring per-prompt latencies...")
    latencies = []
    for i, text in enumerate(prompt_texts):
        t0 = time.time()
        _ = llm.generate([text], sampling)
        lat = time.time() - t0
        latencies.append(lat)

    lat_arr = np.array(latencies)
    print(f"  p50={np.percentile(lat_arr, 50):.2f}s  p90={np.percentile(lat_arr, 90):.2f}s  p99={np.percentile(lat_arr, 99):.2f}s")

    return {
        "model": model,
        "quantization": label,
        "gpu": gpu_name,
        "load_time_s": round(load_time, 2),
        "gpu_memory_allocated_gb": round(mem_alloc, 2),
        "gpu_memory_reserved_gb": round(mem_reserved, 2),
        "batch_time_s": round(batch_time, 2),
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "throughput_tok_s": round(total_out / batch_time, 1),
        "avg_latency_s": round(float(lat_arr.mean()), 3),
        "p50_latency_s": round(float(np.percentile(lat_arr, 50)), 3),
        "p90_latency_s": round(float(np.percentile(lat_arr, 90)), 3),
        "p99_latency_s": round(float(np.percentile(lat_arr, 99)), 3),
        "latencies": [round(x, 3) for x in latencies],
        "results": per_prompt,
    }


@app.function(
    image=benchmark_image,
    timeout=5 * MINUTES,
    volumes={"/root/results": results_vol},
)
def generate_report(bf16_data: dict, fp8_data: dict) -> str:
    """Build comparison charts and a text summary."""
    import json
    import os

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    # Derive a clean model name for titles/filenames. If BF16 and FP8 are
    # different model IDs (e.g. Nemotron), strip the precision suffix.
    bf16_name = bf16_data["model"].split("/")[-1]
    fp8_name = fp8_data["model"].split("/")[-1]
    # Remove trailing -BF16/-FP8 suffixes to get base model name
    model_short = bf16_name
    for suffix in ("-BF16", "-FP8", "-bf16", "-fp8"):
        model_short = model_short.replace(suffix, "")
    os.makedirs("/root/results", exist_ok=True)

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f"FP8 vs BF16 Inference — {model_short}", fontsize=14, fontweight="bold")
    # Show exact model IDs if they differ
    if bf16_name != fp8_name:
        fig.text(0.5, 0.94, f"BF16: {bf16_name}  |  FP8: {fp8_name}",
                 ha="center", fontsize=9, color="gray")

    c_bf16, c_fp8 = "#2196F3", "#FF5722"
    w = 0.35

    # ── 1. Per-prompt latency ──
    ax = axes[0, 0]
    n = len(bf16_data["latencies"])
    x = np.arange(n)
    envs = [r["env"] for r in bf16_data["results"]]
    ax.bar(x - w / 2, bf16_data["latencies"], w, label="BF16", color=c_bf16, alpha=0.85)
    ax.bar(x + w / 2, fp8_data["latencies"], w, label="FP8", color=c_fp8, alpha=0.85)
    ax.set_xlabel("Prompt")
    ax.set_ylabel("Latency (s)")
    ax.set_title("Per-Prompt Latency")
    ax.set_xticks(x)
    ax.set_xticklabels(envs, rotation=45, ha="right", fontsize=8)
    ax.legend()

    # ── 2. Aggregate metrics ──
    ax = axes[0, 1]
    labels = ["Throughput\n(tok/s)", "Avg Latency\n(s)", "p90 Latency\n(s)", "Load Time\n(s)"]
    bf_vals = [bf16_data["throughput_tok_s"], bf16_data["avg_latency_s"],
               bf16_data["p90_latency_s"], bf16_data["load_time_s"]]
    fp_vals = [fp8_data["throughput_tok_s"], fp8_data["avg_latency_s"],
               fp8_data["p90_latency_s"], fp8_data["load_time_s"]]
    x = np.arange(len(labels))
    ax.bar(x - w / 2, bf_vals, w, label="BF16", color=c_bf16, alpha=0.85)
    ax.bar(x + w / 2, fp_vals, w, label="FP8", color=c_fp8, alpha=0.85)
    ax.set_title("Aggregate Metrics")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()

    # ── 3. GPU memory ──
    ax = axes[1, 0]
    mem_labels = ["Allocated (GB)", "Reserved (GB)"]
    bf_mem = [bf16_data["gpu_memory_allocated_gb"], bf16_data["gpu_memory_reserved_gb"]]
    fp_mem = [fp8_data["gpu_memory_allocated_gb"], fp8_data["gpu_memory_reserved_gb"]]
    x = np.arange(len(mem_labels))
    ax.bar(x - w / 2, bf_mem, w, label="BF16", color=c_bf16, alpha=0.85)
    ax.bar(x + w / 2, fp_mem, w, label="FP8", color=c_fp8, alpha=0.85)
    ax.set_title("GPU Memory")
    ax.set_xticks(x)
    ax.set_xticklabels(mem_labels)
    ax.set_ylabel("GB")
    ax.legend()

    # ── 4. Output token counts ──
    ax = axes[1, 1]
    bf_lens = [r["output_tokens"] for r in bf16_data["results"]]
    fp_lens = [r["output_tokens"] for r in fp8_data["results"]]
    x = np.arange(len(bf_lens))
    ax.bar(x - w / 2, bf_lens, w, label="BF16", color=c_bf16, alpha=0.85)
    ax.bar(x + w / 2, fp_lens, w, label="FP8", color=c_fp8, alpha=0.85)
    ax.set_xlabel("Prompt")
    ax.set_ylabel("Tokens")
    ax.set_title("Output Length")
    ax.set_xticks(x)
    ax.set_xticklabels(envs, rotation=45, ha="right", fontsize=8)
    ax.legend()

    plt.tight_layout()
    plot_path = f"/root/results/{model_short}_benchmark.png"
    plt.savefig(plot_path, dpi=150, bbox_inches="tight")
    print(f"Plot saved to {plot_path}")

    # ── Text report ──
    speedup = fp8_data["throughput_tok_s"] / max(bf16_data["throughput_tok_s"], 0.1)
    lat_reduction = 1 - fp8_data["avg_latency_s"] / max(bf16_data["avg_latency_s"], 0.001)
    mem_saving = 1 - fp8_data["gpu_memory_allocated_gb"] / max(bf16_data["gpu_memory_allocated_gb"], 0.01)

    # Word-overlap similarity as rough quality proxy
    sims = []
    for b, f in zip(bf16_data["results"], fp8_data["results"]):
        bw = set(b["text"].lower().split())
        fw = set(f["text"].lower().split())
        if bw or fw:
            sims.append(len(bw & fw) / len(bw | fw))
    avg_sim = sum(sims) / len(sims) if sims else 0

    report = f"""
========================================================
  FP8 vs BF16 INFERENCE BENCHMARK
  Model: {model_short}
  GPU:   {bf16_data['gpu']}
========================================================

THROUGHPUT
  BF16:  {bf16_data['throughput_tok_s']:>8.1f} tok/s
  FP8:   {fp8_data['throughput_tok_s']:>8.1f} tok/s
  Speedup: {speedup:.2f}x

LATENCY (per prompt)
  BF16 avg: {bf16_data['avg_latency_s']:.3f}s   p50: {bf16_data['p50_latency_s']:.3f}s   p90: {bf16_data['p90_latency_s']:.3f}s
  FP8  avg: {fp8_data['avg_latency_s']:.3f}s   p50: {fp8_data['p50_latency_s']:.3f}s   p90: {fp8_data['p90_latency_s']:.3f}s
  Avg reduction: {lat_reduction * 100:.1f}%

MEMORY
  BF16:  {bf16_data['gpu_memory_allocated_gb']:.2f} GB allocated / {bf16_data['gpu_memory_reserved_gb']:.2f} GB reserved
  FP8:   {fp8_data['gpu_memory_allocated_gb']:.2f} GB allocated / {fp8_data['gpu_memory_reserved_gb']:.2f} GB reserved
  Saving: {mem_saving * 100:.1f}%

QUALITY (word-overlap similarity)
  Average: {avg_sim:.3f}  (>0.3 similar, >0.5 very similar)

LOAD TIME
  BF16: {bf16_data['load_time_s']:.1f}s   FP8: {fp8_data['load_time_s']:.1f}s

========================================================
"""
    print(report)

    # Persist everything
    with open(f"/root/results/{model_short}_report.txt", "w") as f:
        f.write(report)
    with open(f"/root/results/{model_short}_combined.json", "w") as f:
        json.dump({"bf16": bf16_data, "fp8": fp8_data}, f, indent=2)

    return report


@app.local_entrypoint()
def main(
    bf16_model: str = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16",
    fp8_model: str = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-FP8",
    max_tokens: int = 512,
):
    """Run FP8 vs BF16 inference benchmark.

    Spawns two H100 containers in parallel — one loads the BF16 model, the other
    loads the pre-quantized FP8 model. Runs the same 10 CTF-themed prompts and
    generates comparison charts.

    For Nemotron-H, dynamic FP8 quantization is NOT supported (vLLM MoE backend
    limitation), so we use NVIDIA's pre-quantized FP8 checkpoint instead.

    Examples:
        .venv/bin/modal run deploy/benchmark_inference.py
        .venv/bin/modal run deploy/benchmark_inference.py --max-tokens 256
        .venv/bin/modal run deploy/benchmark_inference.py \\
            --bf16-model zai-org/GLM-4.7-Flash \\
            --fp8-model zai-org/GLM-4.7-Flash
    """
    print(f"BF16 model: {bf16_model}")
    print(f"FP8 model:  {fp8_model}")
    print(f"Max tokens: {max_tokens}")
    print(f"Prompts:    {len(PROMPTS)} (2 per CTF environment)")
    print()

    # Launch BF16 and FP8 runs in parallel on separate H100s
    print("Spawning BF16 and FP8 runs in parallel...")
    bf16_handle = run_inference.spawn(bf16_model, "bf16", PROMPTS, max_tokens)
    fp8_handle = run_inference.spawn(fp8_model, "fp8", PROMPTS, max_tokens)

    bf16_results = None
    fp8_results = None

    print("Waiting for BF16...")
    try:
        bf16_results = bf16_handle.get()
        print(f"  BF16 done — {bf16_results['throughput_tok_s']} tok/s\n")
    except Exception as e:
        print(f"  BF16 FAILED: {e}\n")

    print("Waiting for FP8...")
    try:
        fp8_results = fp8_handle.get()
        print(f"  FP8 done — {fp8_results['throughput_tok_s']} tok/s\n")
    except Exception as e:
        print(f"  FP8 FAILED: {e}\n")

    if bf16_results and fp8_results:
        # Both succeeded — generate comparison report + charts
        print("Generating comparison report...")
        report = generate_report.remote(bf16_results, fp8_results)
        print(report)

        model_short = bf16_model.split("/")[-1]
        for sfx in ("-BF16", "-FP8", "-bf16", "-fp8"):
            model_short = model_short.replace(sfx, "")
        print(f"\nDownload chart:  .venv/bin/modal volume get benchmark-results {model_short}_benchmark.png .")
        print(f"Download report: .venv/bin/modal volume get benchmark-results {model_short}_report.txt .")
        print(f"Download data:   .venv/bin/modal volume get benchmark-results {model_short}_combined.json .")
    elif bf16_results:
        print("Only BF16 completed. Printing BF16-only summary:")
        _print_single_result(bf16_results)
    elif fp8_results:
        print("Only FP8 completed. Printing FP8-only summary:")
        _print_single_result(fp8_results)
    else:
        print("Both runs failed. Check logs above for errors.")


def _print_single_result(data: dict):
    """Print a summary for a single run when the other fails."""
    print(f"\n  Model:      {data['model']}")
    print(f"  Mode:       {data['quantization']}")
    print(f"  GPU:        {data['gpu']}")
    print(f"  Throughput: {data['throughput_tok_s']} tok/s")
    print(f"  Avg latency: {data['avg_latency_s']}s  p50: {data['p50_latency_s']}s  p90: {data['p90_latency_s']}s")
    print(f"  GPU memory: {data['gpu_memory_allocated_gb']} GB allocated")
    print(f"  Load time:  {data['load_time_s']}s")
