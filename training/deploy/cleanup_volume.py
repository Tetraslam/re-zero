"""Delete ONLY:
  1. /root/checkpoints/nemotron-all-envs/  (old v1 data, 463 GB)
  2. /root/checkpoints/nemotron-all-envs-v2/weights/step_60/  (corrupted partial, 7 GB)

Nothing else is touched.
"""

import modal

checkpoints_vol = modal.Volume.from_name("re-zero-checkpoints")

app = modal.App("re-zero-cleanup")


@app.function(
    image=modal.Image.debian_slim(python_version="3.12"),
    volumes={"/root/checkpoints": checkpoints_vol},
    timeout=600,
)
def cleanup():
    import shutil
    from pathlib import Path

    targets = [
        Path("/root/checkpoints/nemotron-all-envs"),
        Path("/root/checkpoints/nemotron-all-envs-v2/weights/step_60"),
    ]

    for target in targets:
        if target.exists():
            print(f"Deleting: {target}")
            shutil.rmtree(target)
            print(f"  Done.")
        else:
            print(f"Not found (skipping): {target}")

    checkpoints_vol.commit()
    print("Volume committed.")


@app.local_entrypoint()
def main():
    cleanup.remote()
