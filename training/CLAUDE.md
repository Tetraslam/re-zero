# Training Module — Re:Zero

## What this is
RL training pipeline for security-focused models using Prime Intellect's libraries (prime-rl, verifiers, environments hub), running on Modal GPUs ($5k credits, tetracorp workspace). Trained models also get served via vLLM on Modal.

## Current status (2026-02-14, evening)

### GLM-4.7-Flash training: WORKING (validation complete, 3 steps confirmed)
GLM-4.7-Flash (`zai-org/GLM-4.7-Flash`) is a 30B MoE (3B active) text-only transformer with MLA (Multi-head Latent Attention). Architecture: `Glm4MoeLiteForCausalLM`. 64 routed experts + 1 shared expert, 4 experts per token, 47 layers, hidden_size=2048. No Mamba2 issues. Uses 4x H100: 1 for inference, 3 for training (FSDP + LoRA).

**Validated results (redteam env, 3 steps completed):**
| Step | Loss | Entropy | Mismatch KL | Grad Norm | Reward | Throughput | Time/step |
|------|------|---------|-------------|-----------|--------|------------|-----------|
| 0 | -0.0013 | 1.0298 | 0.0063 | 0.0109 | -0.7053 | 286 tok/s | 802s (~13 min) |
| 1 | -0.0023 | 1.0407 | 0.0064 | 0.0082 | -0.7338 | 342 tok/s | 730s (~12 min) |
| 2 | -0.0043 | 1.0154 | 0.0060 | 0.0119 | -0.6959 | 337 tok/s | 742s (~12 min) |

Training produces real gradients. Loss is negative and growing in magnitude (good). A new run (`ap-XhoPfhddUmFMwaXRQQnBib`) is currently active and loading weights.

**Required patches (in `deploy/train_glm4flash.py`):**
1. `get_max_tokens()` API fix: prime-rl calls `get_max_tokens(request=..., prompt=...)` but vLLM v0.16.0 expects `get_max_tokens(max_tokens=int, input_length=int)`. Without this, `/v1/chat/completions/tokens` returns 500 and training gets zero logprobs.

**Required config settings:**
- `[trainer.tokenizer] name = "zai-org/GLM-4.7-Flash"` — prime-rl defaults to Qwen tokenizer otherwise
- `max_model_len = 2048` in `[inference.model]` — reduces KV cache pressure (only 3.25 GiB available after model loading)

**Speed:** ~12-13 min/step (with max_model_len=2048). 50 steps ≈ 10 hours. For production, increase max_steps to 200 and timeout beyond 2 hours.

### GLM-4.6V: NOT YET SET UP (team requested)
GLM-4.6V (`zai-org/GLM-4.6V`) is a **106B parameter vision-language MoE** model. Architecture: `Glm4vMoeForConditionalGeneration`. This is the model the team originally wanted (confusion with "GLM-4.7V" which doesn't exist yet — they meant 4.6V).

**Why it's not running yet:**
- 106B in BF16 = ~212 GB. Needs **at least 3 H100s just for inference** (tensor parallelism required).
- Realistically needs **8x H100** total: 2-3 for inference (TP), 5-6 for training (FSDP + LoRA).
- It's a **vision-language** model but all 5 CTF environments are **text-only** — the vision encoder would be dead weight.
- prime-rl uses `ForCausalLM` models; GLM-4.6V is `ForConditionalGeneration` — may need additional patching.
- vLLM supports it (>= v0.12.0), but inference TP config + prime-rl integration is untested.
- Cost per step would be significantly higher than GLM-4.7-Flash (8x vs 4x H100).

**To set up GLM-4.6V, you need to:**
1. Create `deploy/train_glm46v.py` with 8x H100, tensor parallel inference (tp=2 or tp=3)
2. Create `configs/glm46v-*.toml` configs with adjusted GPU splits (e.g., `inference_gpu_ids=[0,1,2]`, `trainer_gpu_ids=[3,4,5,6,7]`)
3. Test whether prime-rl handles `ForConditionalGeneration` or if more patching is needed
4. Determine LoRA target modules for the 4.6V architecture (may differ from Flash's MLA projections)

### Nemotron training: BLOCKED (Loss=0.0, root cause identified, fix untested)
Nemotron-3-Nano-30B (`nvidia/Nemotron-3-Nano-30B-v1`) produces Loss=0.0 due to Mamba2/Transformer hybrid architecture mismatch with prime-rl.

**Root cause (identified but NOT tested):**
- Nemotron has Mamba2 (SSM) layers that produce different logprobs in vLLM vs PyTorch
- Mismatch KL is ~8 nats (vs 0.006 for pure transformers like GLM-4.7-Flash)
- `seq_log_importance_ratio` sums token-level log ratios across ~3500 tokens → total ≈ -7000
- `exp(-7000) = 0.0` exactly (float64 underflow) → loss coefficient = 0 → Loss = 0
- **Proposed fix**: Add `min=-10.0` clamp to `seq_log_importance_ratio` in prime-rl's `loss.py` (giving `exp(-10) ≈ 4.5e-5`, small but non-zero)
- All other debugging exhausted: FP32 precision, all masking disabled (inf thresholds), advantages verified non-zero, loss_mask active, torch.compile disabled — loss remains exactly 0.0
- The clamp fix requires patching prime-rl source inside the Modal container (similar to get_max_tokens patch)
- **Do not waste GPU credits on Nemotron until the clamp fix is tested and confirmed working.**

## Package management
- **uv only**. Never use pip. Never manually edit pyproject.toml for package versions.
- Add packages: `uv add <package>`
- Remove packages: `uv remove <package>`
- Sync environment: `uv sync`
- Install CLI tools: `uv tool install <tool>` (e.g. `uv tool install prime`)
- **modal CLI**: use `.venv/bin/modal` (it's in the project venv, NOT global PATH)

## Prime Intellect stack

### CLI (`prime`)
```bash
uv tool install prime        # install
prime login                  # authenticate (required once)
prime env list               # browse environments hub
prime env install owner/name # install an environment
```
We do NOT use `prime rl run` (that's PI's hosted infra). We run training on Modal instead.

### prime-rl
Async RL training framework. Three components running as subprocesses:
1. **Inference** — vLLM server for rollout generation (GPU 0)
2. **Orchestrator** — batches prompts, sends to inference, collects rewards from environments
3. **Trainer** — GRPO policy gradient updates via torchrun (remaining GPUs)

Configs are TOML. Entry point: `rl @ <config.toml>`
- Repo: github.com/PrimeIntellect-ai/prime-rl
- Docs: docs.primeintellect.ai/prime-rl/

### verifiers
Library for RL environments and reward functions. Environments are Python packages with datasets, harnesses, and rubrics.
- `uv add verifiers` (already installed)
- Repo: github.com/PrimeIntellect-ai/verifiers

## Models
| Model | HuggingFace ID | Params | Architecture | Training Status |
|-------|---------------|--------|-------------|-----------------|
| GLM-4.7-Flash | `zai-org/GLM-4.7-Flash` | 30B (3B active) | MoE transformer + MLA (`Glm4MoeLiteForCausalLM`) | WORKING (4x H100) |
| GLM-4.6V | `zai-org/GLM-4.6V` | 106B | Vision-language MoE (`Glm4vMoeForConditionalGeneration`) | NOT SET UP (needs 8x H100) |
| Nemotron-3-Nano-30B | `nvidia/Nemotron-3-Nano-30B-v1` | 30B | Mamba2/Transformer hybrid | BLOCKED (Loss=0) |

## CTF environments (from intertwine on Prime Intellect Environments Hub)
All 5 environments provide **continuous rewards** in [-1, +1] (NOT binary), enabling gradient signal for RL.

1. `intertwine/sv-env-redteam-attack` — red team attack simulation (5 scenarios, 3-turn budget, composite rubric: 1.0x jailbreak_success + 0.25x strategy_sophistication)
2. `intertwine/sv-env-code-vulnerability` — vulnerability detection & repair
3. `intertwine/sv-env-config-verification` — security config auditing
4. `intertwine/sv-env-phishing-detection` — phishing classification
5. `intertwine/sv-env-network-logs` — network anomaly detection

## Modal (training + serving)
All compute runs on Modal (tetracorp workspace). We have $5k in credits.

### Training commands
```bash
# Standalone entry point
.venv/bin/modal run deploy/train_glm4flash.py --config glm4flash-redteam.toml
.venv/bin/modal run deploy/train_glm4flash.py --config glm4flash-codevuln.toml --resume

# Unified entry point (same thing)
.venv/bin/modal run deploy/train.py --config glm4flash-redteam.toml
```

### Training infrastructure
- Configs are mounted from `configs/` into the container at `/root/configs/`
- Training uses prime-rl inside the Modal container (trainer + orchestrator + vLLM inference, all async)
- Checkpoints are saved to the `re-zero-checkpoints` Modal Volume at `/root/checkpoints/`
- GPU: 4x H100 (timeout: 120 min)
- **HF token**: Stored in `huggingface` Modal secret as `HF_TOKEN`. Required for model downloads.
- **Detached mode**: When launched with `modal run`, the app runs detached. Use `modal app list` and `modal app logs <app-id>` to monitor.
- **Image caching**: Modal caches Docker images aggressively. To force a rebuild, change the image definition (e.g., add a comment to `.run_commands()`). Bumping version strings inside `run_function` may NOT trigger a rebuild.

### Monitoring training
```bash
# List running apps
.venv/bin/modal app list

# Stream logs from a running app
.venv/bin/modal app logs <app-id>

# Stop a running app
.venv/bin/modal app stop <app-id>
```

Key log lines to watch:
- `Orchestrator Step N: Reward=X.XX` — reward should improve over steps
- `Trainer Step N: Loss=X.XX, Entropy=X.XX` — loss should be NON-ZERO, entropy should decrease slowly
- `Mismatch KL=X.XX` — measures inference/trainer logprob divergence (should be <1 for standard transformers)
- `Throughput: X tokens/s` — inference speed

### Serving
```bash
# Deploy (persistent endpoint with auto-scaling)
.venv/bin/modal deploy deploy/serve_glm4flash.py

# Dev mode (auto-reload on code changes)
.venv/bin/modal serve deploy/serve_glm4flash.py
```
- OpenAI-compatible API via vLLM (`/v1/chat/completions`, `/v1/completions`)
- 1x H100 with FP8 quantization (~30GB), CUDA graphs, prefix caching, chunked prefill
- 32K context, tool calling via `hermes` parser
- To serve a trained checkpoint, set `CHECKPOINT` in `serve_glm4flash.py` (e.g. `"glm4flash-redteam/step-50"`)
- Four Modal Volumes: `re-zero-hf-cache` (HF downloads), `re-zero-vllm-cache` (vLLM cache), `re-zero-checkpoints` (trained weights), `re-zero-mlflow` (metrics)

### General
- Run `modal setup` once to authenticate.
- Never commit Modal tokens or secrets. Use `modal secret create` for API keys.

## File layout
```
training/
├── configs/                            # prime-rl training TOML configs
│   ├── glm4flash-redteam.toml         # GLM-4.7-Flash x Red Team
│   ├── glm4flash-codevuln.toml        # GLM-4.7-Flash x Code Vulnerability
│   ├── glm4flash-config-verification.toml # GLM-4.7-Flash x Config Verification
│   ├── glm4flash-phishing.toml        # GLM-4.7-Flash x Phishing Detection
│   └── glm4flash-network-logs.toml    # GLM-4.7-Flash x Network Logs
├── deploy/
│   ├── common.py                       # shared image, volumes
│   ├── train.py                        # unified training entry point
│   ├── train_glm4flash.py             # standalone GLM-4.7-Flash training (4x H100)
│   └── serve_glm4flash.py             # vLLM serving for GLM-4.7-Flash (1x H100, FP8)
├── CLAUDE.md
├── README.md
└── pyproject.toml
```

## GRPO training — how it works (prime-rl)

### Algorithm
GRPO (Group Relative Policy Optimization) is the RL algorithm used. Key steps per training step:
1. **Rollout generation**: vLLM generates `batch_size * rollouts_per_example` completions from prompts
2. **Reward collection**: Orchestrator sends completions to environment, gets rewards [-1, +1]
3. **Advantage computation**: Per-prompt group normalization (mean=0, std=1 within each group of `rollouts_per_example`)
4. **Policy gradient**: `loss = -(importance_ratio * advantages).detach() * trainer_logprobs` with masking

### Loss function masking (critical for debugging)
prime-rl's loss function (`prime_rl/trainer/rl/loss.py`) has THREE layers of importance ratio masking:
1. **Token-level**: `token_mask_high/low` — masks individual tokens where ratio exceeds threshold
2. **Geometric mean**: `geo_mask_high/low` — masks tokens where geometric mean ratio is extreme
3. **Sequence-level**: `sequence_mask_high/low` — masks ENTIRE SEQUENCE if ANY single token exceeds threshold

### Config reference (TOML)
```toml
# Required
inference_gpu_ids = [0]           # GPUs for vLLM inference
trainer_gpu_ids = [1, 2, 3]      # GPUs for trainer (torchrun FSDP)
max_steps = 200                   # total training steps
seq_len = 4096                    # max sequence length
output_dir = "/root/checkpoints/run-name"

[model]
name = "zai-org/GLM-4.7-Flash"

[wandb]
project = "re-zero"
name = "run-name"
offline = true                    # we use mlflow instead

[ckpt]
interval = 5                      # checkpoint every N steps
keep_last = 3                     # keep last N checkpoints

[trainer.model]
trust_remote_code = true

[trainer.model.lora]
rank = 16
alpha = 32.0
target_modules = ["q_b_proj", "kv_b_proj", "o_proj"]

[trainer.optim]
lr = 5e-6
weight_decay = 0.0

[orchestrator]
batch_size = 128                  # prompts per step
rollouts_per_example = 4          # completions per prompt (for GRPO advantage)

[orchestrator.sampling]
max_tokens = 512                  # max generation length

[[orchestrator.env]]
id = "intertwine/sv-env-redteam-attack"

[inference]
gpu_memory_utilization = 0.95

[inference.model]
trust_remote_code = true
enable_auto_tool_choice = true
tool_call_parser = "hermes"
enforce_eager = true
max_model_len = 4096

[inference.parallel]
dp = 1                            # data parallel replicas for inference
```

### Hyperparameter guidelines
- **batch_size**: 128 for 4-GPU setup. Total rollouts = batch_size * rollouts_per_example
- **rollouts_per_example**: 4 is minimum for meaningful GRPO advantage normalization. 8-16 for better signal
- **lr**: 5e-6 for LoRA
- **max_steps**: 50 for validation runs, 200 for real training
- **max_tokens**: 512 for most CTF tasks (sufficient for tool calls and reasoning)

## GLM-4.7-Flash — specific notes

### Architecture details
- Model type: `glm4_moe_lite` / `Glm4MoeLiteForCausalLM`
- 47 layers, hidden_size=2048, 20 attention heads (MHA, no GQA)
- MoE: 64 routed experts + 1 shared expert, top-4 routing, `noaux_tc` routing method
- MLA: q_lora_rank=768, kv_lora_rank=512 (compressed attention, DeepSeek-V2/V3 style)
- Vocab: 154,880 tokens, max context: 202,752 tokens
- Requires transformers >= 5.0.0rc0 (installed from git in image)

### GPU allocation
- 4x H100 total: GPU 0 = vLLM inference, GPUs 1-3 = trainer (FSDP)
- 30B params in BF16 ~ 60GB -> fits on 1 H100 for inference (with gpu_memory_utilization=0.95)
- Training uses LoRA (rank=16) on attention projections — full fine-tuning would exceed 3-GPU memory

### LoRA configuration
- rank=16, alpha=32.0
- target_modules: `["q_b_proj", "kv_b_proj", "o_proj"]` (MLA attention projections)
- If LoRA fails to match any modules, inspect the model's module names and update target_modules
- lr=5e-6 (higher than full fine-tuning since only training adapters)

### Expected behavior (when working correctly)
- Step 0: Loss > 0, Entropy ~4-5, Mismatch KL < 1.0 (pure transformer)
- Reward should start around -0.5 to -0.7 and improve over steps
- 512 rollouts per step (batch_size=128, rollouts_per_example=4)
- Increase max_steps from 50 to 200 once training is confirmed working

## Workflow
1. **Setup** — `uv sync`, `uv tool install prime`, `prime login`, `modal setup`
2. **Install CTF environments** — `prime env install intertwine/sv-env-redteam-attack` (repeat for all 5)
3. **Train on Modal** — `.venv/bin/modal run deploy/train_glm4flash.py --config glm4flash-redteam.toml`
4. **Monitor** — `.venv/bin/modal app list` then `.venv/bin/modal app logs <app-id>`
5. **Iterate** — watch reward curves, adjust configs, try different environments
6. **Serve trained models** — create serve script, point at trained checkpoints

## Rules
- Never use pip
- Never manually edit pyproject.toml dependency versions
- Never commit .env, .modal/, model weights, or mlflow/ directories
- Never hardcode API keys or tokens
- Keep configs in configs/ as TOML files
- Keep deployment scripts in deploy/
- Always use `.venv/bin/modal` (not bare `modal`) — it's in the project venv
- Before launching training, always check `modal app list` for already-running apps to avoid duplicates
- Stop previous runs before starting new ones on the same config to avoid wasting credits
