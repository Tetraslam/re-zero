"""Quick diagnostic to check what keys are in the re-zero-keys secret."""
import modal

app = modal.App("re-zero-check")

@app.function(secrets=[modal.Secret.from_name("re-zero-keys")])
def check():
    import os
    keys = [k for k in sorted(os.environ.keys()) if any(x in k.upper() for x in ["HF", "HUGGING", "TOKEN", "KEY", "SECRET", "MLFLOW", "WANDB"])]
    for k in keys:
        v = os.environ.get(k, "")
        masked = v[:8] + "..." if len(v) > 8 else v
        print(f"  {k} = {masked}")
    return keys

@app.local_entrypoint()
def main():
    result = check.remote()
    print(f"Found {len(result)} relevant keys: {result}")
