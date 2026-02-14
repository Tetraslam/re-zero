"""Run prime-rl training jobs on Modal GPUs.

Two image variants:
- glm_image: base prime-rl (no mamba-ssm) — for GLM-4.7V
- nemotron_image: base + causal-conv1d + mamba-ssm compiled from source — for Nemotron
"""

import modal

# ── constants ──

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

# ── images ──
# prime-rl uses [tool.uv.sources] for pinned git deps (dion, torchtitan, transformers, vllm, etc.)
# Only `uv sync` resolves these. We clone the repo, uv sync into a venv, then run `rl` from that venv.
# IMPORTANT: do NOT set VIRTUAL_ENV/PATH globally — that breaks Modal's own runner (grpclib etc).

# Base image: clone prime-rl, install deps (no CUDA compilation needed here)
base_image = (
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
)

_common_env = {
    "HF_XET_HIGH_PERFORMANCE": "1",
    "PYTHONUNBUFFERED": "1",
}

# GLM image: no mamba-ssm needed (pure transformer)
glm_image = (
    base_image
    .env(_common_env)
    .add_local_dir("configs", remote_path="/root/configs")
)


def _install_mamba():
    """Compile causal-conv1d + mamba-ssm from source (needs CUDA toolkit, runs on GPU node)."""
    import os
    import subprocess

    env = {
        **os.environ,
        "VIRTUAL_ENV": "/opt/prime-rl/.venv",
        "TORCH_CUDA_ARCH_LIST": "9.0",
        "MAX_JOBS": "8",
    }
    subprocess.run(
        ["uv", "pip", "install", "causal-conv1d"],
        env=env, check=True,
    )
    subprocess.run(
        ["uv", "pip", "install", "mamba-ssm"],
        env=env, check=True,
    )


# Nemotron image: needs mamba-ssm (Mamba/Transformer hybrid architecture)
# run_function with gpu= gives a beefier build machine for faster CUDA compilation.
# Slow the first time (~20-30 min) but cached for all future runs.
nemotron_image = (
    base_image
    .run_function(_install_mamba, gpu="any")
    .env(_common_env)
    .add_local_dir("configs", remote_path="/root/configs")
)

# ── app ──

app = modal.App("re-zero-training")


def _run_training(config_path: str, resume: bool = False):
    """Shared training logic for both model types."""
    import os
    import subprocess

    full_path = f"/root/configs/{config_path}"
    print(f"Starting training with config: {full_path}")
    if resume:
        print("Resume mode: will resume from latest checkpoint")

    # Build env for the subprocess only — activate prime-rl venv here, not globally
    venv_bin = f"{PRIME_RL_VENV}/bin"
    env = {
        **os.environ,
        "VIRTUAL_ENV": PRIME_RL_VENV,
        "PATH": f"{venv_bin}:{os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}",
        "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
        "MLFLOW_TRACKING_URI": "file:///root/mlflow",
    }

    # `rl` is a console_script from prime-rl (prime_rl.rl:main)
    # It spawns 3 subprocesses: inference (vLLM), orchestrator, trainer (via torchrun)
    # cwd=/root so default checkpoint dir "checkpoints/" writes to /root/checkpoints/ (Modal volume)
    cmd = [f"{venv_bin}/rl", "@", full_path]
    if resume:
        cmd.extend(["--ckpt.resume-step", "-1"])

    result = subprocess.run(
        cmd,
        cwd="/root",
        check=True,
        env=env,
    )
    return result.returncode


@app.function(
    image=glm_image,
    gpu="H100:2",
    timeout=120 * MINUTES,
    volumes=VOLUMES,
)
def train_glm(config_path: str, resume: bool = False):
    """Train GLM-4.7V (no mamba-ssm needed)."""
    return _run_training(config_path, resume)


@app.function(
    image=nemotron_image,
    gpu="H100:2",
    timeout=120 * MINUTES,
    volumes=VOLUMES,
)
def train_nemotron(config_path: str, resume: bool = False):
    """Train Nemotron (needs mamba-ssm)."""
    return _run_training(config_path, resume)


@app.local_entrypoint()
def main(config: str = "nemotron-redteam.toml", resume: bool = False):
    """Launch training from CLI.

    Automatically routes to the correct function (GLM vs Nemotron) based on config name.

    Examples:
        modal run deploy/train.py --config glm47v-redteam.toml
        modal run deploy/train.py --config nemotron-redteam.toml --resume
    """
    if config.startswith("glm"):
        print(f"[GLM] Launching: {config}")
        train_glm.remote(config, resume)
    else:
        print(f"[Nemotron] Launching: {config}")
        train_nemotron.remote(config, resume)
