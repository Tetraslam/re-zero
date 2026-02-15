"""Shared Modal infrastructure for prime-rl training and vLLM model serving."""

import modal

MINUTES = 60
PRIME_RL_DIR = "/root/prime-rl"

hf_cache_vol = modal.Volume.from_name("re-zero-hf-cache", create_if_missing=True)
vllm_cache_vol = modal.Volume.from_name("re-zero-vllm-cache", create_if_missing=True)
checkpoints_vol = modal.Volume.from_name("re-zero-checkpoints", create_if_missing=True)

CACHE_VOLUMES = {
    "/root/.cache/huggingface": hf_cache_vol,
    "/root/.cache/vllm": vllm_cache_vol,
}

CHECKPOINTS_PATH = "/root/checkpoints"
CHECKPOINTS_VOLUME = {CHECKPOINTS_PATH: checkpoints_vol}

CTF_ENVS = [
    "intertwine/sv-env-redteam-attack",
    "intertwine/sv-env-code-vulnerability",
    "intertwine/sv-env-config-verification",
    "intertwine/sv-env-network-logs",
    "intertwine/sv-env-phishing-detection",
]


def create_training_image() -> modal.Image:
    return (
        modal.Image.from_registry(
            "nvidia/cuda:12.8.0-devel-ubuntu22.04", add_python="3.12"
        )
        .apt_install("git", "build-essential", "curl", "openssh-client")
        .run_commands("curl -LsSf https://astral.sh/uv/install.sh | sh")
        .env({
            "PATH": "/root/.local/bin:$PATH",
            "HF_XET_HIGH_PERFORMANCE": "1",
            "TORCH_CUDA_ARCH_LIST": "9.0",
        })
        .run_commands(
            f"git clone https://github.com/PrimeIntellect-ai/prime-rl.git {PRIME_RL_DIR}"
        )
        .run_commands(f"cd {PRIME_RL_DIR} && uv sync --all-extras", gpu="H100")
        # jaraco.functools required by setuptools (pulled in by vLLM's cpp_extension import)
        .run_commands(f"cd {PRIME_RL_DIR} && uv pip install jaraco.functools")
        .run_commands(
            "uv tool install prime",
            *[f"cd {PRIME_RL_DIR} && prime env install {env}" for env in CTF_ENVS],
        )
        # Patch AFTER uv sync so verifiers package exists for EnvGroup patch
        .add_local_file("deploy/patch_prime_rl.py", "/tmp/patch_prime_rl.py", copy=True)
        .run_commands(f"python3 /tmp/patch_prime_rl.py {PRIME_RL_DIR}")
    )


def create_vllm_image(extra_packages: list[str] | None = None) -> modal.Image:
    packages = ["vllm", "huggingface-hub"]
    if extra_packages:
        packages.extend(extra_packages)
    return (
        modal.Image.from_registry(
            "nvidia/cuda:12.8.0-devel-ubuntu22.04", add_python="3.12"
        )
        .entrypoint([])
        .pip_install(*packages)
        .env({"HF_XET_HIGH_PERFORMANCE": "1"})
    )
