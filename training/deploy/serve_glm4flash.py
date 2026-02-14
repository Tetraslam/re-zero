"""Modal deployment for GLM-4.7-Flash via vLLM.

Serves either the base HF model or an RL-trained checkpoint from the checkpoints volume.
Set CHECKPOINT to a path like "glm4flash-redteam/step-50" to serve a trained model.

30B MoE (3B active) in FP8 ≈ 30GB — fits on 1x H100 with room for KV cache.
Optimizations: FP8 quantization, CUDA graphs, prefix caching, chunked prefill.
"""

import os
import subprocess

import modal

from .common import (
    CACHE_VOLUMES,
    CHECKPOINTS_PATH,
    CHECKPOINTS_VOLUME,
    MINUTES,
    create_vllm_image,
)

# Set to None for base HF model, or a subfolder name for a trained checkpoint
# e.g. "glm4flash-redteam/step-50"
CHECKPOINT = None

BASE_MODEL = "zai-org/GLM-4.7-Flash"
SERVED_NAME = "glm-4.7-flash"
N_GPU = 1
VLLM_PORT = 8000

# glm4_moe_lite requires latest transformers (>= 5.0.0rc0)
vllm_image = create_vllm_image(
    extra_packages=["git+https://github.com/huggingface/transformers.git"]
)
app = modal.App("re-zero-glm4flash")


@app.function(
    image=vllm_image,
    gpu=f"H100:{N_GPU}",
    scaledown_window=15 * MINUTES,
    timeout=10 * MINUTES,
    volumes={**CACHE_VOLUMES, **CHECKPOINTS_VOLUME},
    secrets=[modal.Secret.from_name("huggingface")],
)
@modal.concurrent(max_inputs=32)
@modal.web_server(port=VLLM_PORT, startup_timeout=10 * MINUTES)
def serve():
    model_path = (
        os.path.join(CHECKPOINTS_PATH, CHECKPOINT) if CHECKPOINT else BASE_MODEL
    )
    cmd = [
        "vllm",
        "serve",
        model_path,
        "--served-model-name",
        SERVED_NAME,
        "--host",
        "0.0.0.0",
        "--port",
        str(VLLM_PORT),
        "--tensor-parallel-size",
        str(N_GPU),
        "--trust-remote-code",
        # -- quantization: FP8 on H100 (native tensor core support, ~2x throughput vs BF16)
        "--quantization",
        "fp8",
        # -- CUDA graphs: pre-compiled execution paths, 10-20% throughput gain
        # (no --enforce-eager)
        # -- prefix caching: reuse KV states for shared system prompts across requests
        "--enable-prefix-caching",
        # -- chunked prefill: overlap prefill + decode for better throughput under load
        "--enable-chunked-prefill",
        # -- tool calling
        "--enable-auto-tool-choice",
        "--tool-call-parser",
        "hermes",
        # -- concurrency: MoE only activates 3B of 30B params per token, can handle more seqs
        "--max-num-seqs",
        "512",
        # -- memory
        "--max-model-len",
        "32768",
        "--gpu-memory-utilization",
        "0.95",
    ]
    subprocess.Popen(cmd)
