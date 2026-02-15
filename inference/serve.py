"""Serve RL-trained OpenReasoning-Nemotron-14B via vLLM on Modal.

OpenAI-compatible API at 128k context window.

Usage:
    # Deploy (persistent endpoint with auto-scaling)
    modal deploy inference/serve.py

    # Dev mode (auto-reload)
    modal serve inference/serve.py

The endpoint URL will be printed after deployment. Use it like any OpenAI API:
    curl <url>/v1/chat/completions \\
         -H "Content-Type: application/json" \\
         -d '{"model": "nemotron-14b-ctf", "messages": [{"role": "user", "content": "Analyze this code for vulnerabilities..."}]}'
"""

import modal

MINUTES = 60

# Volumes
hf_cache_vol = modal.Volume.from_name("re-zero-hf-cache", create_if_missing=True)
vllm_cache_vol = modal.Volume.from_name("re-zero-vllm-cache", create_if_missing=True)
checkpoints_vol = modal.Volume.from_name("re-zero-checkpoints", create_if_missing=True)

# RL-trained checkpoint — step_280 is the last STABLE weight export from v2 training.
# Set to None to use the base model (nvidia/OpenReasoning-Nemotron-14B) instead.
CHECKPOINT_STEP = 280

vllm_image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.8.0-devel-ubuntu22.04", add_python="3.12"
    )
    .entrypoint([])
    .pip_install("vllm", "huggingface-hub")
    .env({"HF_XET_HIGH_PERFORMANCE": "1"})
)

app = modal.App("re-zero-inference")


@app.function(
    image=vllm_image,
    gpu="H100",
    timeout=24 * 60 * MINUTES,
    container_idle_timeout=10 * MINUTES,
    allow_concurrent_inputs=100,
    volumes={
        "/root/.cache/huggingface": hf_cache_vol,
        "/root/.cache/vllm": vllm_cache_vol,
        "/root/checkpoints": checkpoints_vol,
    },
    secrets=[modal.Secret.from_name("huggingface")],
)
@modal.web_server(port=8000, startup_timeout=600)
def serve():
    import subprocess

    if CHECKPOINT_STEP is not None:
        model_path = f"/root/checkpoints/nemotron-all-envs-v2/weights/step_{CHECKPOINT_STEP}"
    else:
        model_path = "nvidia/OpenReasoning-Nemotron-14B"

    cmd = [
        "python", "-m", "vllm.entrypoints.openai.api_server",
        "--model", model_path,
        "--served-model-name", "nemotron-14b-ctf",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--max-model-len", "131072",
        "--gpu-memory-utilization", "0.95",
        "--dtype", "bfloat16",
        "--trust-remote-code",
        "--enable-auto-tool-choice",
        "--tool-call-parser", "hermes",
        "--enforce-eager",
        "--disable-log-requests",
    ]

    print(f"[re-zero] Starting vLLM server with model: {model_path}")
    print(f"[re-zero] Command: {' '.join(cmd)}")
    subprocess.Popen(cmd)
