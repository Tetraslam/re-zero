"""Read-only volume inspector. Lists contents, sizes, and STABLE markers.
Deletes NOTHING. Run with:
    modal run deploy/inspect_volume.py
"""

import modal

checkpoints_vol = modal.Volume.from_name("re-zero-checkpoints")

app = modal.App("re-zero-inspect")


@app.function(
    image=modal.Image.debian_slim(python_version="3.12"),
    volumes={"/root/checkpoints": checkpoints_vol},
    timeout=300,
)
def inspect():
    import os
    from pathlib import Path

    root = Path("/root/checkpoints")

    print("=" * 80)
    print("VOLUME CONTENTS — READ ONLY (nothing will be deleted)")
    print("=" * 80)

    # List top-level directories and their total sizes
    for entry in sorted(root.iterdir()):
        if entry.is_dir():
            # Calculate total size
            total_bytes = 0
            file_count = 0
            for dirpath, dirnames, filenames in os.walk(entry):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    try:
                        total_bytes += os.path.getsize(fp)
                    except OSError:
                        pass
                    file_count += 1
            size_gb = total_bytes / (1024 ** 3)
            print(f"\n{'=' * 60}")
            print(f"DIR: {entry.name}  ({size_gb:.2f} GB, {file_count} files)")
            print(f"{'=' * 60}")

            # List subdirectories one level deep
            for sub in sorted(entry.iterdir()):
                if sub.is_dir():
                    sub_bytes = 0
                    sub_files = 0
                    for dp, dn, fn in os.walk(sub):
                        for f in fn:
                            try:
                                sub_bytes += os.path.getsize(os.path.join(dp, f))
                            except OSError:
                                pass
                            sub_files += 1
                    sub_gb = sub_bytes / (1024 ** 3)
                    print(f"  {sub.name}/  ({sub_gb:.2f} GB, {sub_files} files)")

                    # For checkpoint dirs, check STABLE markers
                    if sub.name in ("checkpoints", "weights"):
                        for step_dir in sorted(sub.iterdir()):
                            if step_dir.is_dir() and step_dir.name.startswith("step_"):
                                has_stable = (step_dir / "STABLE").exists()
                                step_bytes = sum(
                                    os.path.getsize(os.path.join(dp, f))
                                    for dp, dn, fn in os.walk(step_dir)
                                    for f in fn
                                )
                                step_gb = step_bytes / (1024 ** 3)
                                marker = "STABLE" if has_stable else "NO STABLE"
                                print(f"    {step_dir.name}  [{marker}]  ({step_gb:.2f} GB)")

                    # For run_default/checkpoints, also check STABLE
                    if sub.name == "run_default":
                        orch_ckpt = sub / "checkpoints"
                        if orch_ckpt.exists():
                            print(f"    checkpoints/")
                            for step_dir in sorted(orch_ckpt.iterdir()):
                                if step_dir.is_dir() and step_dir.name.startswith("step_"):
                                    has_stable = (step_dir / "STABLE").exists()
                                    marker = "STABLE" if has_stable else "NO STABLE"
                                    print(f"      {step_dir.name}  [{marker}]")
                elif sub.is_file():
                    print(f"  {sub.name}  ({sub.stat().st_size / 1024:.1f} KB)")

    # Disk usage summary
    statvfs = os.statvfs("/root/checkpoints")
    total = statvfs.f_frsize * statvfs.f_blocks / (1024 ** 3)
    free = statvfs.f_frsize * statvfs.f_bfree / (1024 ** 3)
    used = total - free
    print(f"\n{'=' * 80}")
    print(f"DISK: {used:.1f} GB used / {total:.1f} GB total / {free:.1f} GB free")
    print(f"{'=' * 80}")


@app.local_entrypoint()
def main():
    inspect.remote()
