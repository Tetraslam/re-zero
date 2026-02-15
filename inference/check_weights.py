"""Check what files are in the checkpoint weights dir."""

import modal

checkpoints_vol = modal.Volume.from_name("re-zero-checkpoints")

app = modal.App("re-zero-check-weights")


@app.function(
    image=modal.Image.debian_slim(python_version="3.12"),
    volumes={"/root/checkpoints": checkpoints_vol},
    timeout=120,
)
def check():
    import os

    weights_dir = "/root/checkpoints/nemotron-all-envs-v2/weights/step_280"
    if not os.path.exists(weights_dir):
        print(f"NOT FOUND: {weights_dir}")
        return

    print(f"=== {weights_dir} ===")
    for f in sorted(os.listdir(weights_dir)):
        size = os.path.getsize(os.path.join(weights_dir, f))
        size_mb = size / (1024 ** 2)
        print(f"  {f}  ({size_mb:.1f} MB)")


@app.local_entrypoint()
def main():
    check.remote()
