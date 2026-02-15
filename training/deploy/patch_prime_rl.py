"""Patch prime-rl for NemotronH compatibility.

NemotronH (hybrid Mamba architecture) requires two changes:
1. Allow 'eager' attention (it doesn't support flash_attention_2 or sdpa)
2. Alias 'backbone' -> 'model' (NemotronH uses 'backbone' not 'model' for its inner model)
"""

import pathlib
import sys

PRIME_RL_DIR = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("/root/prime-rl")

# 1. Patch config.py to allow 'eager' attention
config_py = PRIME_RL_DIR / "src/prime_rl/trainer/config.py"
text = config_py.read_text()
text = text.replace('"fa4"]', '"fa4", "eager"]')
config_py.write_text(text)
print(f"[patch] Added 'eager' to AttnImplementation in {config_py}")

# 2. Patch model.py to add backbone→model alias before inject_prime_lm_head
model_py = PRIME_RL_DIR / "src/prime_rl/trainer/model.py"
text = model_py.read_text()
old = "    inject_prime_lm_head(model"
new = (
    '    # NemotronH compatibility: alias backbone->model, embeddings->embed_tokens, norm_f->norm\n'
    '    if not hasattr(model, "model") and hasattr(model, "backbone"):\n'
    "        model.model = model.backbone\n"
    '        if hasattr(model.model, "embeddings") and not hasattr(model.model, "embed_tokens"):\n'
    "            model.model.embed_tokens = model.model.embeddings\n"
    '        if hasattr(model.model, "norm_f") and not hasattr(model.model, "norm"):\n'
    "            model.model.norm = model.model.norm_f\n"
    "    inject_prime_lm_head(model"
)
text = text.replace(old, new, 1)  # Only replace first occurrence
model_py.write_text(text)
print(f"[patch] Added NemotronH compatibility aliases in {model_py}")
