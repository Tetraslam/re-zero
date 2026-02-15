"""Test generate_report logic locally using existing benchmark data.

Loads the saved combined.json from the previous benchmark run, adapts old
field names to the current schema, then runs the report generation code
(chart + text) without Modal. Validates that all expected outputs are produced.

Usage:
    cd training && .venv/bin/python deploy/test_benchmark_report.py
"""

import difflib
import json
import os
import sys
import tempfile


# ---------------------------------------------------------------------------
# Helpers (copied from benchmark_inference.py to test independently of Modal)
# ---------------------------------------------------------------------------

def normalized_edit_distance(ref: str, hyp: str) -> float:
    """0 = identical, 1 = completely different."""
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


def generate_report_local(bf16_data: dict, fp8_data: dict, output_dir: str) -> str:
    """Local version of generate_report (no Modal decorator)."""
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

    bf16_name = bf16_data["model"].split("/")[-1]
    fp8_name = fp8_data["model"].split("/")[-1]
    model_short = bf16_name
    for suffix in ("-BF16", "-FP8", "-bf16", "-fp8"):
        model_short = model_short.replace(suffix, "")

    # Compute quality metrics
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

    avg_rouge1 = np.mean([q["rouge1"] for q in quality_metrics])
    avg_rouge2 = np.mean([q["rouge2"] for q in quality_metrics])
    avg_rougeL = np.mean([q["rougeL"] for q in quality_metrics])
    avg_edit = np.mean([q["edit_distance"] for q in quality_metrics])
    avg_jac_uni = np.mean([q["jaccard_unigram"] for q in quality_metrics])
    avg_jac_bi = np.mean([q["jaccard_bigram"] for q in quality_metrics])
    avg_jac_tri = np.mean([q["jaccard_trigram"] for q in quality_metrics])
    avg_len_ratio = np.mean([q["length_ratio"] for q in quality_metrics])

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

    # Build 3x2 chart
    fig, axes = plt.subplots(3, 2, figsize=(18, 16))
    title = f"FP8 vs BF16 Inference — {model_short}"
    if bf16_name != fp8_name:
        title += f"\nBF16: {bf16_name}  |  FP8: {fp8_name}"
    fig.suptitle(title, fontsize=16, fontweight="bold", y=0.98)

    # Panel 1: Per-prompt latency
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

    # Panel 2: Latency distribution
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

    # Panel 3: Performance summary
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

    # Panel 4: Quality heatmap
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
            min(qm["length_ratio"], 1.5),
        ])
        prompt_labels.append(qm["env"])
    df_heat = pd.DataFrame(heatmap_rows, columns=metric_cols, index=prompt_labels)
    sns.heatmap(df_heat, annot=True, fmt=".2f", cmap="RdYlGn",
                vmin=0, vmax=1, ax=ax, linewidths=0.5,
                cbar_kws={"shrink": 0.8, "label": "Score"})
    ax.set_title("FP8 vs BF16 Quality (per prompt)", fontweight="bold")
    ax.set_ylabel("Environment")
    ax.tick_params(axis="x", rotation=30)

    # Panel 5: Per-env quality bars
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

    # Panel 6: Accuracy-efficiency tradeoff
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
    plot_path = os.path.join(output_dir, f"{model_short}_benchmark.png")
    plt.savefig(plot_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Plot saved to {plot_path}")

    # Build per-env quality table
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

    if avg_rougeL >= 0.7 and throughput_ratio >= 1.0:
        verdict = "FP8 recommended: high quality preservation with performance gains."
    elif avg_rougeL >= 0.5 and throughput_ratio >= 1.0:
        verdict = "FP8 viable: moderate quality loss but meaningful performance gains."
    elif avg_rougeL < 0.5:
        verdict = "FP8 shows significant quality degradation. Use with caution."
    else:
        verdict = "Mixed results. FP8 quality is acceptable but no significant speedup."

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

    report_path = os.path.join(output_dir, f"{model_short}_report.txt")
    with open(report_path, "w") as f:
        f.write(report)

    combined = {
        "bf16": bf16_data,
        "fp8": fp8_data,
        "quality_metrics": quality_metrics,
        "env_means": env_means,
    }
    json_path = os.path.join(output_dir, f"{model_short}_combined.json")
    with open(json_path, "w") as f:
        json.dump(combined, f, indent=2)

    return report


def adapt_old_data(data: dict) -> dict:
    """Adapt old JSON schema to new schema (add gpu_memory_used_gib)."""
    # Old schema had gpu_memory_allocated_gb / gpu_memory_reserved_gb (both 0)
    # New schema has gpu_memory_used_gib from nvidia-smi.
    # Use realistic values from vLLM logs: BF16=76.90 GiB, FP8=30.52 GiB
    if "gpu_memory_used_gib" not in data:
        if data.get("quantization") == "bf16":
            data["gpu_memory_used_gib"] = 76.90
        else:
            data["gpu_memory_used_gib"] = 30.52
    # Remove old fields if present
    data.pop("gpu_memory_allocated_gb", None)
    data.pop("gpu_memory_reserved_gb", None)
    return data


def run_tests():
    """Run all tests."""
    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            print(f"  PASS: {name}")
            passed += 1
        else:
            print(f"  FAIL: {name} {detail}")
            failed += 1

    # ── Test 1: Helper functions ──
    print("\n--- Test 1: Helper functions ---")

    check("edit_distance identical",
          normalized_edit_distance("hello world", "hello world") == 0.0)
    check("edit_distance different > 0",
          normalized_edit_distance("hello", "xyz") > 0.5)
    check("edit_distance range [0,1]",
          0.0 <= normalized_edit_distance("abc", "abd") <= 1.0)

    check("ngram_overlap identical",
          ngram_overlap("hello world foo", "hello world foo", 1) == 1.0)
    check("ngram_overlap disjoint",
          ngram_overlap("hello world", "foo bar", 1) == 0.0)
    check("ngram_overlap bigram partial",
          0.0 < ngram_overlap("the quick brown fox", "the quick red fox", 2) < 1.0)
    check("ngram_overlap short text",
          ngram_overlap("hi", "hi", 3) == 0.0,
          "text shorter than n-gram should return 0")

    # ── Test 2: Load and adapt existing data ──
    print("\n--- Test 2: Load existing benchmark data ---")

    json_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "NVIDIA-Nemotron-3-Nano-30B-A3B_combined.json",
    )
    if not os.path.exists(json_path):
        # Try from current working directory
        json_path = "NVIDIA-Nemotron-3-Nano-30B-A3B_combined.json"

    check("combined.json exists", os.path.exists(json_path), f"at {json_path}")

    if not os.path.exists(json_path):
        print("SKIP: Cannot run report tests without combined.json")
        return passed, failed

    with open(json_path) as f:
        raw = json.load(f)

    bf16_data = adapt_old_data(raw["bf16"])
    fp8_data = adapt_old_data(raw["fp8"])

    check("bf16 has gpu_memory_used_gib", "gpu_memory_used_gib" in bf16_data)
    check("fp8 has gpu_memory_used_gib", "gpu_memory_used_gib" in fp8_data)
    check("bf16 has 10 results", len(bf16_data["results"]) == 10)
    check("fp8 has 10 results", len(fp8_data["results"]) == 10)
    check("bf16 has 10 latencies", len(bf16_data["latencies"]) == 10)
    check("fp8 has 10 latencies", len(fp8_data["latencies"]) == 10)

    # ── Test 3: Generate report ──
    print("\n--- Test 3: Generate report with seaborn ---")

    with tempfile.TemporaryDirectory() as tmpdir:
        report = generate_report_local(bf16_data, fp8_data, tmpdir)

        check("report is non-empty string", isinstance(report, str) and len(report) > 100)
        check("report contains THROUGHPUT", "THROUGHPUT" in report)
        check("report contains ROUGE-1", "ROUGE-1" in report)
        check("report contains ROUGE-L", "ROUGE-L" in report)
        check("report contains VERDICT", "VERDICT" in report)
        check("report contains MEMORY", "MEMORY" in report)
        check("report contains EFFICIENCY", "EFFICIENCY" in report)
        check("report contains latency std", "std:" in report)
        check("report contains latency IQR", "IQR:" in report)
        check("report contains Per-Environment", "Per-Environment" in report)

        # Check files were created
        model_short = "NVIDIA-Nemotron-3-Nano-30B-A3B"
        png_path = os.path.join(tmpdir, f"{model_short}_benchmark.png")
        txt_path = os.path.join(tmpdir, f"{model_short}_report.txt")
        json_out_path = os.path.join(tmpdir, f"{model_short}_combined.json")

        check("PNG chart created", os.path.exists(png_path))
        check("PNG > 10KB", os.path.getsize(png_path) > 10_000,
              f"actual: {os.path.getsize(png_path) if os.path.exists(png_path) else 0}")
        check("report.txt created", os.path.exists(txt_path))
        check("combined.json created", os.path.exists(json_out_path))

        # Check JSON output has quality_metrics
        with open(json_out_path) as f:
            out_json = json.load(f)

        check("JSON has quality_metrics", "quality_metrics" in out_json)
        check("JSON has env_means", "env_means" in out_json)
        check("quality_metrics has 10 entries",
              len(out_json.get("quality_metrics", [])) == 10)

        qm0 = out_json["quality_metrics"][0]
        check("quality metric has rouge1", "rouge1" in qm0)
        check("quality metric has rougeL", "rougeL" in qm0)
        check("quality metric has edit_distance", "edit_distance" in qm0)
        check("quality metric has jaccard_bigram", "jaccard_bigram" in qm0)
        check("quality metric has length_ratio", "length_ratio" in qm0)
        check("rouge1 in [0,1]", 0.0 <= qm0["rouge1"] <= 1.0)
        check("edit_distance in [0,1]", 0.0 <= qm0["edit_distance"] <= 1.0)

        # Check env_means has expected environments
        env_means = out_json["env_means"]
        for env in ["redteam", "codevuln", "config", "phishing", "network"]:
            check(f"env_means has {env}", env in env_means)

        print(f"\n  Chart saved to: {png_path}")
        print(f"  Report preview (first 500 chars):\n{report[:500]}")

    return passed, failed


if __name__ == "__main__":
    print("=" * 60)
    print("  Benchmark Report Test Suite")
    print("=" * 60)

    passed, failed = run_tests()

    print(f"\n{'=' * 60}")
    print(f"  Results: {passed} passed, {failed} failed")
    print(f"{'=' * 60}")

    sys.exit(1 if failed > 0 else 0)
