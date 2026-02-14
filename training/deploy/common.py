"""Shared Modal infrastructure for vLLM model serving and training."""

import modal

MINUTES = 60

hf_cache_vol = modal.Volume.from_name("re-zero-hf-cache", create_if_missing=True)
vllm_cache_vol = modal.Volume.from_name("re-zero-vllm-cache", create_if_missing=True)
checkpoints_vol = modal.Volume.from_name("re-zero-checkpoints", create_if_missing=True)
mlflow_vol = modal.Volume.from_name("re-zero-mlflow", create_if_missing=True)

CACHE_VOLUMES = {
    "/root/.cache/huggingface": hf_cache_vol,
    "/root/.cache/vllm": vllm_cache_vol,
}

# Training writes checkpoints here; serve scripts read from here
CHECKPOINTS_PATH = "/root/checkpoints"
CHECKPOINTS_VOLUME = {CHECKPOINTS_PATH: checkpoints_vol}

MLFLOW_PATH = "/root/mlflow"
MLFLOW_VOLUME = {MLFLOW_PATH: mlflow_vol}

PRIME_RL_GIT = "prime-rl @ git+https://github.com/PrimeIntellect-ai/prime-rl.git"


def create_vllm_image(
    extra_packages: list[str] | None = None,
    local_dirs: dict[str, str] | None = None,
) -> modal.Image:
    packages = ["vllm", "huggingface-hub"]
    if extra_packages:
        packages.extend(extra_packages)
    img = (
        modal.Image.from_registry(
            "nvidia/cuda:12.8.0-devel-ubuntu22.04", add_python="3.12"
        )
        .entrypoint([])
        .pip_install(*packages)
        .env({
            "HF_XET_HIGH_PERFORMANCE": "1",
            "PYTHONUNBUFFERED": "1",
        })
    )
    if local_dirs:
        for local_path, remote_path in local_dirs.items():
            img = img.add_local_dir(local_path, remote_path)
    return img
