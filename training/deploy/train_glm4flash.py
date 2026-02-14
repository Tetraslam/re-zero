"""Run GLM-4.7-Flash training on Modal GPUs.

GLM-4.7-Flash (zai-org/GLM-4.7-Flash) is a 30B MoE (3B active) text-only
transformer with MLA (Multi-head Latent Attention). No mamba-ssm needed.
Requires transformers from main branch for Glm4MoeLiteForCausalLM support.
Uses 4x H100: GPU 0 = inference (vLLM), GPUs 1-3 = trainer (FSDP + LoRA).
"""

import modal

MINUTES = 60
PRIME_RL_DIR = "/opt/prime-rl"
PRIME_RL_VENV = f"{PRIME_RL_DIR}/.venv"

hf_cache_vol = modal.Volume.from_name("re-zero-hf-cache", create_if_missing=True)
vllm_cache_vol = modal.Volume.from_name("re-zero-vllm-cache", create_if_missing=True)
checkpoints_vol = modal.Volume.from_name("re-zero-checkpoints", create_if_missing=True)
mlflow_vol = modal.Volume.from_name("re-zero-mlflow", create_if_missing=True)

VOLUMES = {
    "/root/.cache/huggingface": hf_cache_vol,
    "/root/.cache/vllm": vllm_cache_vol,
    "/root/checkpoints": checkpoints_vol,
    "/root/mlflow": mlflow_vol,
}


def _install_glm4flash_patches():
    """Apply patches for GLM-4.7-Flash compatibility with prime-rl."""

    # 1. Fix get_max_tokens() API mismatch between prime-rl and vLLM v0.16.0.
    #    prime-rl calls: get_max_tokens(max_model_len=..., request=request, prompt=engine_prompt, ...)
    #    vLLM expects:   get_max_tokens(max_model_len, max_tokens, input_length, default_sampling_params)
    serving_file = f"{PRIME_RL_DIR}/src/prime_rl/inference/vllm/serving_chat_with_tokens.py"
    with open(serving_file) as f:
        content = f.read()

    old_call = """max_tokens = get_max_tokens(
                    max_model_len=self.max_model_len,
                    request=request,
                    prompt=engine_prompt,
                    default_sampling_params=self.default_sampling_params,
                )"""
    new_call = """_input_length = len(engine_prompt.get("prompt_token_ids", [])) if isinstance(engine_prompt, dict) else len(getattr(engine_prompt, "prompt_token_ids", []))
                max_tokens = get_max_tokens(
                    max_model_len=self.max_model_len,
                    max_tokens=request.max_tokens,
                    input_length=_input_length,
                    default_sampling_params=self.default_sampling_params,
                )"""

    if old_call in content:
        content = content.replace(old_call, new_call)
        with open(serving_file, "w") as f:
            f.write(content)
        print("OK: Patched get_max_tokens() call in serving_chat_with_tokens.py")
    else:
        print("WARNING: Could not find get_max_tokens() call to patch. Checking if already patched...")
        if "_input_length" in content:
            print("OK: get_max_tokens() already patched.")
        else:
            print("ERROR: get_max_tokens() call not found and not already patched!")

    print("GLM-4.7-Flash patches installed successfully (v2).")


glm4flash_image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.8.0-devel-ubuntu22.04", add_python="3.12"
    )
    .entrypoint([])
    .apt_install("git", "g++", "ninja-build")
    .pip_install("uv")
    .run_commands(
        f"git clone https://github.com/PrimeIntellect-ai/prime-rl.git {PRIME_RL_DIR}",
        f"cd {PRIME_RL_DIR} && uv sync --no-dev --extra flash-attn",
        # GLM-4.7-Flash (glm4_moe_lite) requires latest transformers
        f"VIRTUAL_ENV={PRIME_RL_VENV} uv pip install git+https://github.com/huggingface/transformers.git",
        f"VIRTUAL_ENV={PRIME_RL_VENV} uv pip install mlflow 'huggingface-hub[hf_xet]'",
    )
    .run_function(_install_glm4flash_patches)
    .run_commands("echo 'glm4flash-patch-v2: fixed get_max_tokens API mismatch'")
    .env({
        "HF_XET_HIGH_PERFORMANCE": "1",
        "PYTHONUNBUFFERED": "1",
    })
    .add_local_dir("configs", remote_path="/root/configs")
)

app = modal.App("re-zero-glm4flash")


@app.function(
    image=glm4flash_image,
    gpu="H100:4",
    timeout=120 * MINUTES,
    volumes=VOLUMES,
    secrets=[modal.Secret.from_name("huggingface")],
)
def train(config_path: str, resume: bool = False):
    """Train GLM-4.7-Flash."""
    import os
    import subprocess

    full_path = f"/root/configs/{config_path}"
    print(f"Starting GLM-4.7-Flash training with config: {full_path}")
    if resume:
        print("Resume mode: will resume from latest checkpoint")

    venv_bin = f"{PRIME_RL_VENV}/bin"
    env = {
        **os.environ,
        "VIRTUAL_ENV": PRIME_RL_VENV,
        "PATH": f"{venv_bin}:{os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}",
        "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
        "MLFLOW_TRACKING_URI": "file:///root/mlflow",
    }

    cmd = [f"{venv_bin}/rl", "@", full_path]
    if resume:
        cmd.extend(["--ckpt.resume-step", "-1"])

    result = subprocess.run(cmd, cwd="/root", check=True, env=env)
    return result.returncode


@app.local_entrypoint()
def main(config: str = "glm4flash-redteam.toml", resume: bool = False):
    """Launch GLM-4.7-Flash training.

    Examples:
        modal run deploy/train_glm4flash.py --config glm4flash-redteam.toml
        modal run deploy/train_glm4flash.py --config glm4flash-codevuln.toml --resume
    """
    print(f"[GLM-4.7-Flash] Launching: {config}")
    train.remote(config, resume)
