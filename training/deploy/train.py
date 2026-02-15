"""Run prime-rl RL training jobs on Modal GPUs."""

import sys
import tomllib

import modal

from deploy.common import (
    CACHE_VOLUMES,
    CHECKPOINTS_VOLUME,
    MINUTES,
    PRIME_RL_DIR,
    create_training_image,
)

train_image = (
    create_training_image()
    .add_local_dir("configs", remote_path="/root/configs", copy=True)
    .add_local_python_source("deploy")
)

app = modal.App("re-zero-training")


def _gpu_count_from_config(config_path: str) -> int:
    """Read inference_gpu_ids + trainer_gpu_ids from TOML to determine total GPUs."""
    with open(f"configs/{config_path}", "rb") as f:
        cfg = tomllib.load(f)
    inf = cfg.get("inference_gpu_ids", [0])
    trn = cfg.get("trainer_gpu_ids", [1, 2, 3])
    return len(set(inf) | set(trn))


# Parse --config from CLI at module level so the decorator gets the right GPU count.
_config_name = "nemotron-redteam.toml"
for _i, _arg in enumerate(sys.argv):
    if _arg == "--config" and _i + 1 < len(sys.argv):
        _config_name = sys.argv[_i + 1]
try:
    _gpu_count = _gpu_count_from_config(_config_name)
except FileNotFoundError:
    _gpu_count = 4  # safe default for remote execution


@app.function(
    image=train_image,
    gpu=f"H100:{_gpu_count}",
    timeout=24 * 60 * MINUTES,  # 24 hours
    volumes={**CACHE_VOLUMES, **CHECKPOINTS_VOLUME},
    secrets=[
        modal.Secret.from_name("re-zero-keys"),
        modal.Secret.from_name("huggingface"),
    ],
)
def train(config_path: str, resume: bool = False):
    import os
    import subprocess
    import threading

    full_path = f"/root/configs/{config_path}"
    print(f"[re-zero] Starting RL training with config: {full_path}")
    if resume:
        print("[re-zero] RESUME MODE: will load latest stable checkpoint")
    print(f"[re-zero] prime-rl directory: {PRIME_RL_DIR}")

    with open(full_path) as f:
        print(f"[re-zero] Config contents:\n{f.read()}")

    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,name,memory.total", "--format=csv,noheader"],
        capture_output=True,
        text=True,
    )
    print(f"[re-zero] GPUs:\n{result.stdout}")

    # Extract output_dir from config for log tailing
    with open(full_path, "rb") as f:
        config = tomllib.load(f)
    output_dir = config.get("output_dir", "/root/checkpoints/default")

    import shutil
    from pathlib import Path

    if resume:
        # --- Fix 1: Clean incomplete TRAINER checkpoints ---
        # prime-rl writes a STABLE marker after a checkpoint save completes.
        # If a run is killed mid-save, the latest checkpoint directory exists
        # but has no STABLE marker, causing "metadata is None" on load.
        # We remove incomplete checkpoints from the tip, working backwards.
        trainer_ckpt_dir = Path(output_dir) / "checkpoints"
        latest_valid_step = None
        if trainer_ckpt_dir.exists():
            step_dirs = sorted(
                [d for d in trainer_ckpt_dir.iterdir() if d.is_dir() and d.name.startswith("step_")],
                key=lambda p: int(p.name.split("_")[1]),
                reverse=True,
            )
            for step_dir in step_dirs:
                if (step_dir / "STABLE").exists():
                    latest_valid_step = int(step_dir.name.split("_")[1])
                    print(f"[re-zero] Latest valid trainer checkpoint: step_{latest_valid_step}", flush=True)
                    break
                print(f"[re-zero] Removing incomplete trainer checkpoint: {step_dir}", flush=True)
                shutil.rmtree(step_dir)

        if latest_valid_step is None:
            # No valid trainer checkpoints — can't resume.
            # Must also clean orchestrator state to prevent trainer/orchestrator desync
            # (orchestrator resuming from step N while trainer starts from 0).
            print("[re-zero] WARNING: No valid trainer checkpoints found!", flush=True)
            run_default_dir = Path(output_dir) / "run_default"
            if run_default_dir.exists():
                shutil.rmtree(run_default_dir)
                print("[re-zero] Cleaned orchestrator state to prevent desync.", flush=True)
            resume = False
            print("[re-zero] Falling back to fresh start (no --resume).", flush=True)

        # --- Fix 2: Ensure orchestrator checkpoints have STABLE markers ---
        # Without these, the trainer's MultiRunManager sets progress.step=0 instead of
        # the correct resume step, causing a deadlock where the trainer waits for
        # step_0 rollouts while the orchestrator generates from the resume step.
        if resume:
            orch_ckpt_dir = Path(output_dir) / "run_default" / "checkpoints"
            if orch_ckpt_dir.exists():
                for step_dir in orch_ckpt_dir.glob("step_*"):
                    stable_marker = step_dir / "STABLE"
                    if not stable_marker.exists():
                        stable_marker.touch()
                        print(f"[re-zero] Created STABLE marker: {stable_marker}", flush=True)
    else:
        # --- Fresh start: clean stale orchestrator state ---
        # If run_default/ exists from a previous run but we're NOT resuming,
        # the orchestrator will auto-resume from its last checkpoint while the
        # trainer starts from step 0, causing a desync.
        run_default_dir = Path(output_dir) / "run_default"
        if run_default_dir.exists():
            print("[re-zero] Fresh start: cleaning stale orchestrator state (run_default/).", flush=True)
            shutil.rmtree(run_default_dir)
        trainer_ckpt_dir = Path(output_dir) / "checkpoints"
        if trainer_ckpt_dir.exists():
            print("[re-zero] Fresh start: cleaning stale trainer checkpoints.", flush=True)
            shutil.rmtree(trainer_ckpt_dir)

    # Background thread to tail ALL log files (inference, orchestrator, trainer)
    stop_tailing = threading.Event()

    def tail_logs():
        """Tail orchestrator + trainer logs only (skip wandb/debug noise)."""
        seen_files = {}  # path -> last position
        while not stop_tailing.is_set():
            log_patterns = [
                f"{output_dir}/logs/trainer/rank_0.log",
                f"{output_dir}/run_default/logs/orchestrator.log",
                f"{output_dir}/run_default/logs/inference.log",
            ]
            for path in log_patterns:
                if not os.path.exists(path):
                    continue
                if path not in seen_files:
                    seen_files[path] = 0
                    print(f"[re-zero] Tailing: {path}", flush=True)
                try:
                    with open(path) as f:
                        f.seek(seen_files[path])
                        new_content = f.read()
                        if new_content:
                            tag = os.path.basename(path).replace(".log", "")
                            for line in new_content.splitlines():
                                print(f"[{tag}] {line}", flush=True)
                            seen_files[path] = f.tell()
                except Exception:
                    pass
            stop_tailing.wait(3)

    log_thread = threading.Thread(target=tail_logs, daemon=True)
    log_thread.start()

    rl_bin = f"{PRIME_RL_DIR}/.venv/bin/rl"
    env = {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
    }
    cmd = [rl_bin, "@", full_path]
    if resume:
        cmd.extend(["--ckpt.resume-step", "-1"])
    print(f"[re-zero] Running: {' '.join(cmd)}", flush=True)

    result = subprocess.run(cmd, cwd=PRIME_RL_DIR, env=env)

    stop_tailing.set()
    log_thread.join(timeout=5)

    if result.returncode != 0:
        raise RuntimeError(f"rl exited with code {result.returncode}")


@app.local_entrypoint()
def main(config: str = "nemotron-redteam.toml", resume: bool = False):
    """Launch training. Use --resume to continue from latest checkpoint.

    IMPORTANT: Always use --detach so the job survives local terminal disconnects:
        modal run --detach deploy/train.py --config nemotron-all-envs.toml --resume

    Monitor with:
        modal app list
        modal app logs <app-id>
        modal container exec <container-id> -- tail -20 /root/checkpoints/<name>/logs/trainer/rank_0.log
    """
    print(f"[re-zero] Config {config} requires {_gpu_count}x H100")
    if resume:
        print("[re-zero] Resume mode enabled — will load latest stable checkpoint")
    train.remote(config, resume=resume)
