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
        "seaborn",
        "rouge-score",
    )
    .run_commands("python -c \"import nltk; nltk.download('punkt_tab')\"")
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
    extra_engine_kwargs: dict | None = None,
) -> dict:
    """Run vLLM offline inference and collect timing/quality metrics.

    Args:
        model: HuggingFace model ID (can be base BF16 or pre-quantized FP8).
        label: Display label for this run (e.g. "bf16", "fp8").
        prompts: List of {"env": ..., "prompt": ...} dicts.
        max_tokens: Max generation tokens per prompt.
        extra_engine_kwargs: Additional vLLM engine kwargs to override defaults.
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
    if extra_engine_kwargs:
        engine_kwargs.update(extra_engine_kwargs)

    import subprocess as sp

    def _gpu_mem_used_mib() -> float:
        """Query nvidia-smi for current GPU memory used (MiB)."""
        try:
            smi = sp.run(
                ["nvidia-smi", "--query-gpu=memory.used",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            return float(smi.stdout.strip())
        except Exception:
            return 0.0

    # Measure baseline GPU memory before vLLM init
    baseline_mib = _gpu_mem_used_mib()

    t0 = time.time()
    llm = LLM(**engine_kwargs)
    load_time = time.time() - t0

    # Measure after init — includes model weights + KV cache + overhead.
    # vLLM runs the model in a subprocess, so torch.cuda.memory_allocated()
    # returns 0 in the parent. nvidia-smi sees all GPU processes.
    after_mib = _gpu_mem_used_mib()
    gpu_mem_used_gib = round((after_mib - baseline_mib) / 1024, 2)

    print(f"Model loaded in {load_time:.1f}s")
    print(f"GPU memory — baseline: {baseline_mib/1024:.1f} GiB, after init: {after_mib/1024:.1f} GiB, vLLM total: {gpu_mem_used_gib:.2f} GiB")

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
        "gpu_memory_used_gib": gpu_mem_used_gib,
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


def normalized_edit_distance(ref: str, hyp: str) -> float:
    """0 = identical, 1 = completely different."""
    import difflib
    return 1.0 - difflib.SequenceMatcher(None, ref, hyp).ratio()


def ngram_overlap(text_a: str, text_b: str, n: int) -> float:
    """Jaccard similarity of word n-grams between two texts."""
    words_a = text_a.lower().split()
    words_b = text_b.lower().split()
    if len(words_a) < n or len(words_b) < n:
        return 0.0
    ngrams_a = set(tuple(words_a[i:i + n]) for i in range(len(words_a) - n + 1))
    ngrams_b = set(tuple(words_b[i:i + n]) for i in range(len(words_b) - n + 1))
    union = ngrams_a | ngrams_b
    if not union:
        return 0.0
    return len(ngrams_a & ngrams_b) / len(union)


@app.function(
    image=benchmark_image,
    timeout=5 * MINUTES,
    volumes={"/root/results": results_vol},
)
def generate_report(bf16_data: dict, fp8_data: dict) -> str:
    """Build seaborn comparison charts and an expanded text summary."""
    import json
    import os
    from collections import defaultdict

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import seaborn as sns
    from rouge_score import rouge_scorer

    sns.set_theme(style="whitegrid", palette="muted", font_scale=1.0)
    palette = {"BF16": "#4C72B0", "FP8": "#DD8452"}

    # ── Model name for titles / filenames ──
    bf16_name = bf16_data["model"].split("/")[-1]
    fp8_name = fp8_data["model"].split("/")[-1]
    model_short = bf16_name
    for suffix in ("-BF16", "-FP8", "-bf16", "-fp8"):
        model_short = model_short.replace(suffix, "")
    os.makedirs("/root/results", exist_ok=True)

    # ── Compute quality metrics ──
    scorer = rouge_scorer.RougeScorer(
        ["rouge1", "rouge2", "rougeL"], use_stemmer=True
    )
    quality_metrics = []
    for bf16_r, fp8_r in zip(bf16_data["results"], fp8_data["results"]):
        bt, ft = bf16_r["text"], fp8_r["text"]
        scores = scorer.score(bt, ft)
        quality_metrics.append({
            "env": bf16_r["env"],
            "rouge1": round(scores["rouge1"].fmeasure, 4),
            "rouge2": round(scores["rouge2"].fmeasure, 4),
            "rougeL": round(scores["rougeL"].fmeasure, 4),
            "edit_distance": round(normalized_edit_distance(bt, ft), 4),
            "jaccard_unigram": round(ngram_overlap(bt, ft, 1), 4),
            "jaccard_bigram": round(ngram_overlap(bt, ft, 2), 4),
            "jaccard_trigram": round(ngram_overlap(bt, ft, 3), 4),
            "length_ratio": round(
                fp8_r["output_tokens"] / max(bf16_r["output_tokens"], 1), 4
            ),
        })

    # Per-environment averages
    env_agg = defaultdict(lambda: defaultdict(list))
    for qm in quality_metrics:
        for key in ["rouge1", "rouge2", "rougeL", "edit_distance",
                     "jaccard_unigram", "jaccard_bigram", "jaccard_trigram",
                     "length_ratio"]:
            env_agg[qm["env"]][key].append(qm[key])
    env_means = {
        env: {k: round(sum(v) / len(v), 4) for k, v in metrics.items()}
        for env, metrics in env_agg.items()
    }

    # Overall quality averages
    avg_rouge1 = np.mean([q["rouge1"] for q in quality_metrics])
    avg_rouge2 = np.mean([q["rouge2"] for q in quality_metrics])
    avg_rougeL = np.mean([q["rougeL"] for q in quality_metrics])
    avg_edit = np.mean([q["edit_distance"] for q in quality_metrics])
    avg_jac_uni = np.mean([q["jaccard_unigram"] for q in quality_metrics])
    avg_jac_bi = np.mean([q["jaccard_bigram"] for q in quality_metrics])
    avg_jac_tri = np.mean([q["jaccard_trigram"] for q in quality_metrics])
    avg_len_ratio = np.mean([q["length_ratio"] for q in quality_metrics])

    # ── Derived performance metrics ──
    bf16_tput_eff = bf16_data["throughput_tok_s"] / max(bf16_data["gpu_memory_used_gib"], 0.01)
    fp8_tput_eff = fp8_data["throughput_tok_s"] / max(fp8_data["gpu_memory_used_gib"], 0.01)
    throughput_ratio = fp8_data["throughput_tok_s"] / max(bf16_data["throughput_tok_s"], 0.1)
    lat_reduction_pct = (1 - fp8_data["avg_latency_s"] / max(bf16_data["avg_latency_s"], 0.001)) * 100
    mem_reduction_pct = (1 - fp8_data["gpu_memory_used_gib"] / max(bf16_data["gpu_memory_used_gib"], 0.01)) * 100
    load_speedup = bf16_data["load_time_s"] / max(fp8_data["load_time_s"], 0.01)

    bf16_lats = np.array(bf16_data["latencies"])
    fp8_lats = np.array(fp8_data["latencies"])
    bf16_lat_std = float(np.std(bf16_lats))
    fp8_lat_std = float(np.std(fp8_lats))
    bf16_lat_iqr = float(np.percentile(bf16_lats, 75) - np.percentile(bf16_lats, 25))
    fp8_lat_iqr = float(np.percentile(fp8_lats, 75) - np.percentile(fp8_lats, 25))

    envs = [r["env"] for r in bf16_data["results"]]

    # ── Build 3x2 chart ──
    fig, axes = plt.subplots(3, 2, figsize=(18, 16))
    title = f"FP8 vs BF16 Inference — {model_short}"
    if bf16_name != fp8_name:
        title += f"\nBF16: {bf16_name}  |  FP8: {fp8_name}"
    fig.suptitle(title, fontsize=16, fontweight="bold", y=0.98)

    # ── Panel 1: Per-prompt latency ──
    ax = axes[0, 0]
    lat_records = []
    for i, (bl, fl) in enumerate(zip(bf16_data["latencies"], fp8_data["latencies"])):
        lab = f"P{i} ({envs[i]})"
        lat_records.append({"Prompt": lab, "Mode": "BF16", "Latency (s)": bl})
        lat_records.append({"Prompt": lab, "Mode": "FP8", "Latency (s)": fl})
    df_lat = pd.DataFrame(lat_records)
    sns.barplot(data=df_lat, x="Prompt", y="Latency (s)", hue="Mode",
                palette=palette, ax=ax, edgecolor="white", linewidth=0.5)
    ax.set_title("Per-Prompt Latency", fontweight="bold")
    ax.tick_params(axis="x", rotation=45)
    for label in ax.get_xticklabels():
        label.set_fontsize(7)
        label.set_ha("right")
    ax.legend(title="")

    # ── Panel 2: Latency distribution (box + strip) ──
    ax = axes[0, 1]
    dist_records = (
        [{"Mode": "BF16", "Latency (s)": l} for l in bf16_data["latencies"]]
        + [{"Mode": "FP8", "Latency (s)": l} for l in fp8_data["latencies"]]
    )
    df_dist = pd.DataFrame(dist_records)
    sns.boxplot(data=df_dist, x="Mode", y="Latency (s)", palette=palette,
                ax=ax, width=0.4, linewidth=1.5, fliersize=4)
    sns.stripplot(data=df_dist, x="Mode", y="Latency (s)", palette=palette,
                  ax=ax, size=6, alpha=0.6, jitter=True,
                  edgecolor="gray", linewidth=0.5)
    for i, (mode, data) in enumerate([("BF16", bf16_data), ("FP8", fp8_data)]):
        ax.text(i, data["p90_latency_s"], f'p90={data["p90_latency_s"]:.1f}',
                ha="center", va="bottom", fontsize=8, color="gray")
    ax.set_title("Latency Distribution", fontweight="bold")

    # ── Panel 3: Performance summary (horizontal bars) ──
    ax = axes[1, 0]
    perf_labels = [
        "Throughput (tok/s)", "Memory (GiB)", "Load Time (s)",
        "Efficiency (tok/s/GiB)",
    ]
    bf_perf = [
        bf16_data["throughput_tok_s"], bf16_data["gpu_memory_used_gib"],
        bf16_data["load_time_s"], round(bf16_tput_eff, 1),
    ]
    fp_perf = [
        fp8_data["throughput_tok_s"], fp8_data["gpu_memory_used_gib"],
        fp8_data["load_time_s"], round(fp8_tput_eff, 1),
    ]
    perf_records = []
    for lab, bv, fv in zip(perf_labels, bf_perf, fp_perf):
        perf_records.append({"Metric": lab, "Mode": "BF16", "Value": bv})
        perf_records.append({"Metric": lab, "Mode": "FP8", "Value": fv})
    df_perf = pd.DataFrame(perf_records)
    sns.barplot(data=df_perf, y="Metric", x="Value", hue="Mode",
                palette=palette, ax=ax, orient="h", edgecolor="white")
    for container in ax.containers:
        ax.bar_label(container, fmt="%.1f", fontsize=8, padding=3)
    ax.set_title("Performance Comparison", fontweight="bold")
    ax.set_xlabel("")
    ax.legend(title="")

    # ── Panel 4: Quality heatmap ──
    ax = axes[1, 1]
    metric_cols = ["ROUGE-1", "ROUGE-2", "ROUGE-L", "1-EditDist",
                   "Bigram Ovlp.", "Len. Ratio"]
    heatmap_rows = []
    prompt_labels = []
    for qm in quality_metrics:
        heatmap_rows.append([
            qm["rouge1"], qm["rouge2"], qm["rougeL"],
            1.0 - qm["edit_distance"],
            qm["jaccard_bigram"],
            min(qm["length_ratio"], 1.5),  # cap for color scale
        ])
        prompt_labels.append(qm["env"])
    df_heat = pd.DataFrame(heatmap_rows, columns=metric_cols, index=prompt_labels)
    sns.heatmap(df_heat, annot=True, fmt=".2f", cmap="RdYlGn",
                vmin=0, vmax=1, ax=ax, linewidths=0.5,
                cbar_kws={"shrink": 0.8, "label": "Score"})
    ax.set_title("FP8 vs BF16 Quality (per prompt)", fontweight="bold")
    ax.set_ylabel("Environment")
    ax.tick_params(axis="x", rotation=30)

    # ── Panel 5: Per-env quality bars ──
    ax = axes[2, 0]
    envs_ordered = ["redteam", "codevuln", "config", "phishing", "network"]
    env_records = []
    for env in envs_ordered:
        if env in env_means:
            m = env_means[env]
            env_records.append({"Env": env, "Metric": "ROUGE-L", "Score": m["rougeL"]})
            env_records.append({"Env": env, "Metric": "Bigram Ovlp.", "Score": m["jaccard_bigram"]})
            env_records.append({"Env": env, "Metric": "1-EditDist", "Score": 1.0 - m["edit_distance"]})
    df_env = pd.DataFrame(env_records)
    sns.barplot(data=df_env, x="Env", y="Score", hue="Metric",
                palette="Set2", ax=ax, edgecolor="white")
    ax.set_title("Quality by Environment", fontweight="bold")
    ax.set_ylim(0, 1.05)
    ax.axhline(y=0.5, color="gray", linestyle="--", alpha=0.4)
    ax.legend(title="", loc="lower right", fontsize=8)

    # ── Panel 6: Accuracy-efficiency tradeoff scatter ──
    ax = axes[2, 1]
    tradeoff_records = []
    for i, qm in enumerate(quality_metrics):
        bl = bf16_data["latencies"][i]
        fl = fp8_data["latencies"][i]
        lat_red = (1 - fl / max(bl, 0.001)) * 100
        tradeoff_records.append({
            "Latency Reduction (%)": lat_red,
            "ROUGE-L": qm["rougeL"],
            "Environment": qm["env"],
        })
    df_trade = pd.DataFrame(tradeoff_records)
    sns.scatterplot(data=df_trade, x="Latency Reduction (%)", y="ROUGE-L",
                    hue="Environment", style="Environment", s=120, ax=ax,
                    palette="deep", edgecolor="white", linewidth=0.5)
    ax.set_title("Accuracy-Efficiency Tradeoff", fontweight="bold")
    ax.set_ylim(0, 1.05)
    ax.axhline(y=0.5, color="gray", linestyle="--", alpha=0.3)
    ax.axvline(x=0, color="gray", linestyle="--", alpha=0.3)
    ax.legend(title="Env", bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=8)

    plt.tight_layout(rect=[0, 0, 0.95, 0.96])
    plot_path = f"/root/results/{model_short}_benchmark.png"
    plt.savefig(plot_path, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"Plot saved to {plot_path}")

    # ── Build per-env quality table ──
    env_table_lines = []
    for env in envs_ordered:
        if env in env_means:
            m = env_means[env]
            env_table_lines.append(
                f"    {env:<12s}  ROUGE-L={m['rougeL']:.3f}  "
                f"Bigram={m['jaccard_bigram']:.3f}  "
                f"EditDist={m['edit_distance']:.3f}  "
                f"LenRatio={m['length_ratio']:.3f}"
            )
    env_quality_table = "\n".join(env_table_lines)

    # Verdict
    if avg_rougeL >= 0.7 and throughput_ratio >= 1.0:
        verdict = "FP8 recommended: high quality preservation with performance gains."
    elif avg_rougeL >= 0.5 and throughput_ratio >= 1.0:
        verdict = "FP8 viable: moderate quality loss but meaningful performance gains."
    elif avg_rougeL < 0.5:
        verdict = "FP8 shows significant quality degradation. Use with caution."
    else:
        verdict = "Mixed results. FP8 quality is acceptable but no significant speedup."

    # ── Text report ──
    report = f"""
{'=' * 64}
  FP8 vs BF16 INFERENCE BENCHMARK
  Model: {model_short}
  GPU:   {bf16_data['gpu']}
{'=' * 64}

THROUGHPUT
  BF16:  {bf16_data['throughput_tok_s']:>8.1f} tok/s
  FP8:   {fp8_data['throughput_tok_s']:>8.1f} tok/s
  Speedup: {throughput_ratio:.2f}x

THROUGHPUT EFFICIENCY (tok/s per GiB)
  BF16:  {bf16_tput_eff:>8.1f} tok/s/GiB
  FP8:   {fp8_tput_eff:>8.1f} tok/s/GiB

LATENCY (per prompt)
  BF16 avg: {bf16_data['avg_latency_s']:.3f}s   p50: {bf16_data['p50_latency_s']:.3f}s   p90: {bf16_data['p90_latency_s']:.3f}s   p99: {bf16_data['p99_latency_s']:.3f}s
  FP8  avg: {fp8_data['avg_latency_s']:.3f}s   p50: {fp8_data['p50_latency_s']:.3f}s   p90: {fp8_data['p90_latency_s']:.3f}s   p99: {fp8_data['p99_latency_s']:.3f}s
  Avg reduction: {lat_reduction_pct:.1f}%
  BF16 std: {bf16_lat_std:.3f}s   IQR: {bf16_lat_iqr:.3f}s
  FP8  std: {fp8_lat_std:.3f}s   IQR: {fp8_lat_iqr:.3f}s

MEMORY (model + KV cache via nvidia-smi)
  BF16:  {bf16_data['gpu_memory_used_gib']:.2f} GiB
  FP8:   {fp8_data['gpu_memory_used_gib']:.2f} GiB
  Reduction: {mem_reduction_pct:.1f}%

LOAD TIME
  BF16: {bf16_data['load_time_s']:.1f}s   FP8: {fp8_data['load_time_s']:.1f}s
  FP8 load speedup: {load_speedup:.2f}x

QUALITY (FP8 vs BF16 output similarity)
  Overall Averages:
    ROUGE-1:         {avg_rouge1:.3f}
    ROUGE-2:         {avg_rouge2:.3f}
    ROUGE-L:         {avg_rougeL:.3f}
    Jaccard unigram: {avg_jac_uni:.3f}
    Jaccard bigram:  {avg_jac_bi:.3f}
    Jaccard trigram: {avg_jac_tri:.3f}
    Edit distance:   {avg_edit:.3f}  (0=identical, 1=completely different)
    Length ratio:    {avg_len_ratio:.3f}  (1.0=same length)

  Per-Environment:
{env_quality_table}

VERDICT
  {verdict}

{'=' * 64}
"""
    print(report)

    # Persist everything
    with open(f"/root/results/{model_short}_report.txt", "w") as f:
        f.write(report)
    combined = {
        "bf16": bf16_data,
        "fp8": fp8_data,
        "quality_metrics": quality_metrics,
        "env_means": env_means,
    }
    with open(f"/root/results/{model_short}_combined.json", "w") as f:
        json.dump(combined, f, indent=2)

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
    # For FP8: override kv_cache_dtype to "bfloat16" because the Nemotron-H FP8
    # checkpoint defaults to fp8_e4m3 KV cache, which causes vLLM engine init to
    # hang for 30+ min (massive eager-mode KV allocation). "auto" resolves to
    # fp8_e4m3 for ModelOpt checkpoints, so we must explicitly force bfloat16.
    # FP8 weights still provide memory + throughput benefits.
    print("Spawning BF16 and FP8 runs in parallel...")
    bf16_handle = run_inference.spawn(bf16_model, "bf16", PROMPTS, max_tokens)
    fp8_handle = run_inference.spawn(
        fp8_model, "fp8", PROMPTS, max_tokens,
        extra_engine_kwargs={
            "kv_cache_dtype": "bfloat16",
            # Cap utilization — FP8 model is ~30 GiB (vs 59 for BF16), so 0.95
            # leaves ~45 GiB for KV cache. Allocating that much in eager mode
            # causes engine init to hang. 0.60 gives ~17 GiB for KV, matching BF16.
            "gpu_memory_utilization": 0.60,
        },
    )

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
    print(f"  GPU memory: {data['gpu_memory_used_gib']} GiB")
    print(f"  Load time:  {data['load_time_s']}s")
