"""Extract ALL training metrics from v2 wandb + find all data sources."""

import modal

checkpoints_vol = modal.Volume.from_name("re-zero-checkpoints")

app = modal.App("re-zero-extract-logs")


@app.function(
    image=modal.Image.debian_slim(python_version="3.12").pip_install("wandb"),
    volumes={"/root/checkpoints": checkpoints_vol},
    timeout=300,
)
def extract():
    import json
    import os
    import re

    from wandb.proto import wandb_internal_pb2
    from wandb.sdk.internal.datastore import DataStore

    base = "/root/checkpoints/nemotron-all-envs-v2"

    # Find ALL wandb dirs recursively
    print("=== ALL WANDB DIRS ===")
    for dirpath, dirnames, filenames in os.walk(base):
        for f in filenames:
            if f.endswith(".wandb"):
                fp = os.path.join(dirpath, f)
                print(f"  {fp}  ({os.path.getsize(fp)} bytes)")

    # Parse the SUCCESS lines from all wandb output_raw records
    step_pattern = re.compile(
        r'Step (\d+) \|.*?Loss: ([-\d.]+) \|.*?Entropy: ([-\d.]+) \|.*?Mismatch KL: ([-\d.]+) \|.*?Grad\. Norm: ([-\d.]+)'
    )

    all_trainer_rows = []
    for dirpath, dirnames, filenames in os.walk(base):
        for f in filenames:
            if not f.endswith(".wandb"):
                continue
            fp = os.path.join(dirpath, f)
            ds = DataStore()
            ds.open_for_scan(fp)
            while True:
                data = ds.scan_data()
                if data is None:
                    break
                record = wandb_internal_pb2.Record()
                record.ParseFromString(data)
                field = record.WhichOneof("record_type")
                if field == "output_raw":
                    text = record.output_raw.line
                    for line in text.split("\n"):
                        m = step_pattern.search(line)
                        if m:
                            all_trainer_rows.append({
                                "step": int(m.group(1)),
                                "loss": float(m.group(2)),
                                "entropy": float(m.group(3)),
                                "mismatch_kl": float(m.group(4)),
                                "grad_norm": float(m.group(5)),
                            })

    all_trainer_rows.sort(key=lambda x: x["step"])
    print(f"\n=== TRAINER METRICS ({len(all_trainer_rows)} steps) ===")
    for row in all_trainer_rows:
        print(json.dumps(row))

    # Now check: the resumed run's wandb might be in the NEW output dir
    # The resumed run writes to the SAME output_dir but has its own wandb run
    # Check if there's a second wandb run with more data
    print(f"\n=== WANDB DIR LISTING ===")
    wandb_dir = f"{base}/wandb"
    for entry in sorted(os.listdir(wandb_dir)):
        path = os.path.join(wandb_dir, entry)
        if os.path.isdir(path):
            total = sum(os.path.getsize(os.path.join(dp, f))
                       for dp, dn, fn in os.walk(path) for f in fn)
            print(f"  {entry}/  ({total} bytes)")

    # The resume data might be in torchrun logs too
    print(f"\n=== TORCHRUN LOGS ===")
    torchrun_dir = f"{base}/torchrun"
    if os.path.exists(torchrun_dir):
        for f in sorted(os.listdir(torchrun_dir)):
            fp = os.path.join(torchrun_dir, f)
            size = os.path.getsize(fp)
            print(f"  {f} ({size} bytes)")
            if size > 100:
                with open(fp) as fh:
                    content = fh.read()
                # Check for step lines
                matches = step_pattern.findall(content)
                if matches:
                    print(f"    Found {len(matches)} step entries!")
                    for m in matches[-5:]:
                        print(f"    Step {m[0]}: Loss={m[1]} Entropy={m[2]}")


@app.local_entrypoint()
def main():
    extract.remote()
