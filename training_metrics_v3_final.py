"""Final training metrics chart — OpenReasoning-Nemotron-14B GRPO v2 (full 300 steps).
Parsed from logdump.txt (manual copy of Modal app logs)."""
import re
import matplotlib.pyplot as plt
import numpy as np

# === PARSE LOGDUMP ===
trainer_pattern = re.compile(
    r'Step (\d+) \|.*?Loss: ([-\d.]+) \|.*?Entropy: ([-\d.]+) \|.*?Mismatch KL: ([-\d.]+) \|.*?Grad\. Norm: ([-\d.]+)'
)
orch_pattern = re.compile(
    r'\[orchestrator\].*Step (\d+) \|.*?Reward: ([-\d.]+)'
)

trainer_data = {}  # step -> {loss, entropy, mismatch_kl, grad_norm}
orch_data = {}     # step -> reward

with open('logdump.txt') as f:
    for line in f:
        # Trainer (deduplicate by step — [default0] and [rank_0] print same data)
        m = trainer_pattern.search(line)
        if m:
            step = int(m.group(1))
            if step not in trainer_data:
                trainer_data[step] = {
                    'loss': float(m.group(2)),
                    'entropy': float(m.group(3)),
                    'mismatch_kl': float(m.group(4)),
                    'grad_norm': float(m.group(5)),
                }

        # Orchestrator
        m = orch_pattern.search(line)
        if m:
            step = int(m.group(1))
            if step not in orch_data:
                orch_data[step] = float(m.group(2))

# Sort by step
trainer_steps = sorted(trainer_data.keys())
orch_steps = sorted(orch_data.keys())

loss = [trainer_data[s]['loss'] for s in trainer_steps]
entropy = [trainer_data[s]['entropy'] for s in trainer_steps]
grad_norm = [trainer_data[s]['grad_norm'] for s in trainer_steps]
mismatch_kl = [trainer_data[s]['mismatch_kl'] for s in trainer_steps]
reward = [orch_data[s] for s in orch_steps]

print(f"Trainer steps: {len(trainer_steps)} (range {trainer_steps[0]}-{trainer_steps[-1]})")
print(f"Orchestrator steps: {len(orch_steps)} (range {orch_steps[0]}-{orch_steps[-1]})")
print(f"Final reward: {reward[-1]:.4f} (peak: {max(reward):.4f})")
print(f"Entropy: {entropy[0]:.4f} -> {entropy[-1]:.4f}")

# === CHART ===
plt.style.use('dark_background')
fig, axes = plt.subplots(3, 2, figsize=(16, 14))
fig.suptitle(
    'OpenReasoning-Nemotron-14B  |  GRPO Training v2  |  5 CTF Environments\n'
    '8\u00d7H100  |  LoRA r=32  |  batch=64  |  16 rollouts/ex  |  temp=0.9  |  300 steps',
    fontsize=14, fontweight='bold', color='white', y=0.98
)

colors = {
    'reward': '#00ff88',
    'loss': '#ff6b6b',
    'entropy': '#4ecdc4',
    'grad_norm': '#ffd93d',
    'kl': '#a78bfa',
}
window = 7


def style_ax(ax, title, ylabel, color):
    ax.set_title(title, fontsize=12, fontweight='bold', color=color, pad=10)
    ax.set_ylabel(ylabel, fontsize=10, color='#888888')
    ax.set_xlabel('Step', fontsize=10, color='#888888')
    ax.tick_params(colors='#888888')
    ax.grid(True, alpha=0.15, color='white')
    for spine in ax.spines.values():
        spine.set_color('#333333')


def smooth(steps, data, w):
    arr = np.array(data)
    kernel = np.ones(w) / w
    smoothed = np.convolve(arr, kernel, mode='valid')
    return steps[w - 1:], smoothed


# 1. Reward
ax = axes[0, 0]
ax.plot(orch_steps, reward, color=colors['reward'], linewidth=1.0, alpha=0.4)
sx, sy = smooth(np.array(orch_steps), reward, window)
ax.plot(sx, sy, color=colors['reward'], linewidth=2.5, label=f'{window}-step avg')
ax.axhline(y=0, color='#555555', linestyle='--', linewidth=0.8)
ax.fill_between(orch_steps, reward, 0, alpha=0.06, color=colors['reward'])
ax.legend(loc='lower right', fontsize=9)
style_ax(ax, f'Reward (0 \u2192 {reward[-1]:.2f})', 'Reward', colors['reward'])

# 2. Loss
ax = axes[0, 1]
ax.plot(trainer_steps, loss, color=colors['loss'], linewidth=1.0, alpha=0.4)
sx, sy = smooth(np.array(trainer_steps), loss, window)
ax.plot(sx, sy, color=colors['loss'], linewidth=2.5, label=f'{window}-step avg')
ax.axhline(y=0, color='#555555', linestyle='--', linewidth=0.8)
ax.legend(loc='upper left', fontsize=9)
style_ax(ax, 'GRPO Loss', 'Loss', colors['loss'])

# 3. Entropy
ax = axes[1, 0]
ax.plot(trainer_steps, entropy, color=colors['entropy'], linewidth=1.0, alpha=0.4)
sx, sy = smooth(np.array(trainer_steps), entropy, window)
ax.plot(sx, sy, color=colors['entropy'], linewidth=2.5, label=f'{window}-step avg')
ax.legend(loc='upper right', fontsize=9)
style_ax(ax, f'Entropy ({entropy[0]:.3f} \u2192 {entropy[-1]:.3f})', 'Entropy', colors['entropy'])

# 4. Gradient Norm
ax = axes[1, 1]
ax.plot(trainer_steps, grad_norm, color=colors['grad_norm'], linewidth=1.0, alpha=0.4)
sx, sy = smooth(np.array(trainer_steps), grad_norm, window)
ax.plot(sx, sy, color=colors['grad_norm'], linewidth=2.5, label=f'{window}-step avg')
ax.legend(loc='upper left', fontsize=9)
style_ax(ax, 'Gradient Norm', 'Grad Norm', colors['grad_norm'])

# 5. Mismatch KL
ax = axes[2, 0]
ax.plot(trainer_steps, mismatch_kl, color=colors['kl'], linewidth=1.0, alpha=0.4)
sx, sy = smooth(np.array(trainer_steps), mismatch_kl, window)
ax.plot(sx, sy, color=colors['kl'], linewidth=2.5, label=f'{window}-step avg')
ax.legend(loc='upper left', fontsize=9)
style_ax(ax, 'Mismatch KL (Trainer vs Inference)', 'KL Divergence', colors['kl'])

# 6. Summary
ax = axes[2, 1]
ax.axis('off')
summary_text = (
    f"Run: nemotron-all-envs-v2 (FINAL)\n"
    f"Model: nvidia/OpenReasoning-Nemotron-14B (14.7B)\n"
    f"Architecture: Qwen2ForCausalLM (dense transformer)\n"
    f"LoRA: rank=32, alpha=64, q/k/v/o_proj\n"
    f"Hardware: 8x H100 80GB (2 inf DP=2, 6 train FSDP)\n"
    f"\n"
    f"Hyperparameters:\n"
    f"  batch_size=64, rollouts/ex=16, temp=0.9\n"
    f"  lr=1e-5, max_tokens=1024, seq_len=4096\n"
    f"\n"
    f"Results ({len(trainer_steps)} trainer / {len(orch_steps)} orch steps):\n"
    f"  Reward:    {reward[0]:.4f} -> {reward[-1]:.4f} (peak {max(reward):.4f})\n"
    f"  Loss:      {loss[0]:.4f} -> {loss[-1]:.4f}\n"
    f"  Entropy:   {entropy[0]:.4f} -> {entropy[-1]:.4f}\n"
    f"  Grad norm: {grad_norm[0]:.4f} -> {grad_norm[-1]:.4f}\n"
    f"  KL:        {mismatch_kl[0]:.4f} -> {mismatch_kl[-1]:.4f}\n"
    f"\n"
    f"Weight checkpoints: 34 (step_5 to step_280)\n"
    f"\n"
    f"Environments:\n"
    f"  - redteam-attack\n"
    f"  - code-vulnerability\n"
    f"  - config-verification\n"
    f"  - network-logs\n"
    f"  - phishing-detection"
)
ax.text(0.05, 0.95, summary_text, transform=ax.transAxes,
        fontsize=9.5, fontfamily='monospace', color='#cccccc',
        verticalalignment='top',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='#1a1a2e', edgecolor='#333355'))

plt.tight_layout(rect=[0, 0, 1, 0.94])
plt.savefig('training_metrics_v3_final.png', dpi=150, bbox_inches='tight',
            facecolor=fig.get_facecolor())
plt.close()
print("Saved to training_metrics_v3_final.png")
