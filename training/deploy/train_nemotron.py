"""Run Nemotron training on Modal GPUs.

Nemotron is a Mamba/Transformer hybrid — needs causal-conv1d + mamba-ssm compiled from source.
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


def _install_mamba():
    """Compile causal-conv1d + mamba-ssm from source (needs CUDA toolkit)."""
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


nemotron_image = (
    base_image
    .run_function(_install_mamba, gpu="any")
    .env({
        "HF_XET_HIGH_PERFORMANCE": "1",
        "PYTHONUNBUFFERED": "1",
    })
    .add_local_dir("configs", remote_path="/root/configs")
)

app = modal.App("re-zero-nemotron")


@app.function(
    image=nemotron_image,
    gpu="H100:2",
    timeout=120 * MINUTES,
    volumes=VOLUMES,
)
def train(config_path: str, resume: bool = False):
    """Train Nemotron (needs mamba-ssm)."""
    import os
    import subprocess

    full_path = f"/root/configs/{config_path}"
    print(f"Starting Nemotron training with config: {full_path}")
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
def main(config: str = "nemotron-redteam.toml", resume: bool = False):
    """Launch Nemotron training.

    Examples:
        modal run deploy/train_nemotron.py --config nemotron-redteam.toml
        modal run deploy/train_nemotron.py --config nemotron-redteam.toml --resume
    """
    print(f"[Nemotron] Launching: {config}")
    train.remote(config, resume)
