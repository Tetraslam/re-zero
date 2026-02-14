"""Run GLM-4.7V training on Modal GPUs.

Separate from Nemotron to avoid the mamba-ssm build dependency.
GLM is a pure transformer — no mamba-ssm needed.
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

glm_image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.8.0-devel-ubuntu22.04", add_python="3.12"
    )
    .entrypoint([])
    .apt_install("git", "g++", "ninja-build")
    .pip_install("uv")
    .run_commands(
        f"git clone https://github.com/PrimeIntellect-ai/prime-rl.git {PRIME_RL_DIR}",
        f"cd {PRIME_RL_DIR} && uv sync --no-dev --extra flash-attn",
        f"VIRTUAL_ENV={PRIME_RL_VENV} uv pip install mlflow 'huggingface-hub[hf_xet]'",
    )
    .env({
        "HF_XET_HIGH_PERFORMANCE": "1",
        "PYTHONUNBUFFERED": "1",
    })
    .add_local_dir("configs", remote_path="/root/configs")
)

app = modal.App("re-zero-glm")


@app.function(
    image=glm_image,
    gpu="H100:2",
    timeout=120 * MINUTES,
    volumes=VOLUMES,
)
def train(config_path: str, resume: bool = False):
    """Train GLM-4.7V."""
    import os
    import subprocess

    full_path = f"/root/configs/{config_path}"
    print(f"Starting GLM training with config: {full_path}")
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
def main(config: str = "glm47v-redteam.toml", resume: bool = False):
    """Launch GLM training.

    Examples:
        modal run deploy/train_glm.py --config glm47v-redteam.toml
        modal run deploy/train_glm.py --config glm47v-codevuln.toml --resume
    """
    print(f"[GLM] Launching: {config}")
    train.remote(config, resume)
