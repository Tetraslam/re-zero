"""Patch prime-rl for compatibility fixes.

Applied during Modal image build. Keeps patches minimal and safe —
each patch checks whether the target code exists before modifying.
"""

import pathlib
import sys

PRIME_RL_DIR = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("/root/prime-rl")

# 1. Patch get_max_tokens() API mismatch (prime-rl vs vLLM >= 0.16)
#    prime-rl calls: get_max_tokens(max_model_len=..., request=request, prompt=engine_prompt, ...)
#    vLLM expects:   get_max_tokens(max_model_len, max_tokens, input_length, default_sampling_params)
serving_file = PRIME_RL_DIR / "src/prime_rl/inference/vllm/serving_chat_with_tokens.py"
if serving_file.exists():
    text = serving_file.read_text()
    old_call = """max_tokens = get_max_tokens(
                    max_model_len=self.max_model_len,
                    request=request,
                    prompt=engine_prompt,
                    default_sampling_params=self.default_sampling_params,
                )"""
    new_call = """_input_length = len(engine_prompt.get("prompt_token_ids", [])) if isinstance(engine_prompt, dict) else len(getattr(engine_prompt, "prompt_token_ids", []))
                max_tokens = get_max_tokens(
                    max_model_len=self.max_model_len,
                    max_tokens=request.max_tokens,
                    input_length=_input_length,
                    default_sampling_params=self.default_sampling_params,
                )"""
    if old_call in text:
        text = text.replace(old_call, new_call)
        serving_file.write_text(text)
        print(f"[patch] Fixed get_max_tokens() API in {serving_file}")
    elif "_input_length" in text:
        print(f"[patch] get_max_tokens() already patched in {serving_file}")
    else:
        print(f"[patch] SKIP: get_max_tokens() call pattern not found (may be fixed upstream)")

# 2. Patch verifiers EnvGroup — normalize dataset schemas before concatenation
#    Different CTF envs have different 'answer' field types (string vs complex dict).
#    concatenate_datasets() fails when schemas don't align.
#    Fix: serialize non-string 'answer' columns to JSON strings before concat.
env_group_py = PRIME_RL_DIR / ".venv/lib/python3.12/site-packages/verifiers/envs/env_group.py"
if env_group_py.exists():
    text = env_group_py.read_text()
    # Find the concatenate_datasets call and add schema normalization before it
    old_concat = "dataset = concatenate_datasets(datasets) if datasets else None"
    new_concat = """# --- PATCH: normalize heterogeneous schemas before concatenation ---
        import json as _json
        from datasets import Value as _Value, Features as _Features
        def _normalize_datasets(ds_list):
            \"\"\"Convert non-string 'answer' columns to JSON strings for schema compat.\"\"\"
            normalized = []
            for ds in ds_list:
                if ds is not None and 'answer' in ds.features:
                    feat = ds.features['answer']
                    if not (isinstance(feat, _Value) and feat.dtype == 'string'):
                        ds = ds.map(lambda row: {**row, 'answer': _json.dumps(row['answer'], default=str)})
                        new_features = {k: (v if k != 'answer' else _Value('string')) for k, v in ds.features.items()}
                        ds = ds.cast(_Features(new_features))
                normalized.append(ds)
            return normalized
        datasets = _normalize_datasets(datasets)
        eval_datasets = _normalize_datasets(eval_datasets) if eval_datasets else eval_datasets
        # --- END PATCH ---
        dataset = concatenate_datasets(datasets) if datasets else None"""
    if old_concat in text:
        text = text.replace(old_concat, new_concat)
        env_group_py.write_text(text)
        print(f"[patch] Added schema normalization to EnvGroup in {env_group_py}")
    elif "_normalize_datasets" in text:
        print(f"[patch] EnvGroup schema normalization already patched in {env_group_py}")
    else:
        print(f"[patch] SKIP: concatenate_datasets pattern not found in {env_group_py}")
else:
    print(f"[patch] SKIP: {env_group_py} not found (verifiers not installed yet)")

# 3. Patch loss.py — add min clamp to seq_log_importance_ratio
#    Without this, large negative log-ratios cause exp(-huge) = 0 → zero loss
loss_py = PRIME_RL_DIR / "src/prime_rl/trainer/rl/loss.py"
if loss_py.exists():
    text = loss_py.read_text()
    old_clamp = "log_importance_ratio[loss_mask].sum().detach(), max=10.0"
    new_clamp = "log_importance_ratio[loss_mask].sum().detach(), min=-10.0, max=10.0"
    if old_clamp in text:
        text = text.replace(old_clamp, new_clamp)
        loss_py.write_text(text)
        print(f"[patch] Added min=-10.0 clamp to seq_log_importance_ratio in {loss_py}")
    else:
        print(f"[patch] SKIP: loss clamp pattern not found (may be fixed upstream)")

print("[patch] Done.")
