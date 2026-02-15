"""Generate training metrics chart from the current Nemotron-14B GRPO run."""
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

# Trainer data (from [default0] logs, steps 0-54)
trainer_steps = list(range(55))
loss = [0.0000, 0.0000, -0.0000, -0.0000, 0.0000, -0.0001, -0.0000, 0.0001, 0.0000, -0.0000,
        -0.0000, -0.0000, -0.0000, 0.0000, -0.0001, -0.0000, -0.0000, 0.0000, 0.0000, 0.0000,
        -0.0002, -0.0000, -0.0001, -0.0000, 0.0000, 0.0000, -0.0002, -0.0002, -0.0000, -0.0000,
        -0.0000, -0.0000, -0.0000, -0.0004, -0.0001, -0.0002, -0.0002, -0.0001, -0.0001, -0.0003,
        -0.0007, -0.0006, -0.0005, -0.0000, -0.0000, -0.0002, 0.0000, 0.0000, 0.0001, -0.0009,
        -0.0003, -0.0006, -0.0005, -0.0008, -0.0012]
entropy = [0.4882, 0.4806, 0.4826, 0.4864, 0.4833, 0.4682, 0.4993, 0.4902, 0.4903, 0.4815,
           0.4828, 0.4901, 0.4770, 0.4793, 0.4819, 0.4892, 0.4947, 0.5102, 0.4986, 0.4897,
           0.4839, 0.4695, 0.4901, 0.4998, 0.4877, 0.4855, 0.4860, 0.5076, 0.4821, 0.4786,
           0.4801, 0.4643, 0.4912, 0.4848, 0.4923, 0.4684, 0.4580, 0.4565, 0.4712, 0.4610,
           0.4351, 0.4374, 0.4328, 0.4376, 0.4621, 0.4565, 0.4409, 0.4593, 0.4330, 0.4023,
           0.4211, 0.4207, 0.4387, 0.4133, 0.4024]
grad_norm = [0.0000, 0.0051, 0.0008, 0.0006, 0.0023, 0.0022, 0.0006, 0.0058, 0.0007, 0.0005,
             0.0013, 0.0014, 0.0013, 0.0012, 0.0047, 0.0013, 0.0003, 0.0029, 0.0012, 0.0045,
             0.0064, 0.0005, 0.0017, 0.0018, 0.0000, 0.0015, 0.0087, 0.0048, 0.0015, 0.0008,
             0.0004, 0.0008, 0.0046, 0.0104, 0.0057, 0.0056, 0.0078, 0.0046, 0.0058, 0.0045,
             0.0093, 0.0095, 0.0116, 0.0111, 0.0050, 0.0086, 0.0075, 0.0080, 0.0117, 0.0131,
             0.0112, 0.0151, 0.0192, 0.0101, 0.0199]
mismatch_kl = [0.0009, 0.0009, 0.0009, 0.0010, 0.0009, 0.0009, 0.0010, 0.0010, 0.0009, 0.0009,
               0.0010, 0.0009, 0.0009, 0.0009, 0.0009, 0.0009, 0.0009, 0.0010, 0.0010, 0.0009,
               0.0010, 0.0009, 0.0010, 0.0010, 0.0010, 0.0009, 0.0010, 0.0010, 0.0010, 0.0010,
               0.0010, 0.0011, 0.0012, 0.0012, 0.0012, 0.0014, 0.0012, 0.0014, 0.0014, 0.0013,
               0.0011, 0.0010, 0.0010, 0.0009, 0.0010, 0.0009, 0.0010, 0.0010, 0.0009, 0.0009,
               0.0008, 0.0009, 0.0010, 0.0009, 0.0010]

# Orchestrator data (reward, steps 0-54)
orch_steps = list(range(55))
reward = [0.0000, 0.0160, 0.0043, 0.0030, 0.0170, 0.0159, 0.0030, -0.0056, 0.0034, 0.0021,
          0.0067, 0.0089, 0.0089, 0.0047, 0.0160, 0.0077, 0.0011, -0.0725, 0.0041, 0.0078,
          0.0219, 0.0024, 0.0125, 0.0111, 0.0000, 0.0077, 0.0209, 0.0012, 0.0079, 0.0043,
          0.0021, 0.0033, 0.0263, 0.0561, 0.0160, 0.0239, 0.0638, 0.0324, 0.0240, 0.0410,
          0.0691, 0.0967, 0.0965, 0.0682, 0.0445, 0.0338, 0.0463, 0.0410, 0.1053, 0.1364,
          0.0857, 0.1479, 0.1815, 0.0852, 0.2069]

# Style
plt.style.use('dark_background')
fig, axes = plt.subplots(3, 2, figsize=(16, 14))
fig.suptitle('OpenReasoning-Nemotron-14B  |  GRPO Training  |  5 CTF Environments\n4×H100  |  LoRA r=32  |  batch=128  |  rollouts/ex=4',
             fontsize=14, fontweight='bold', color='white', y=0.98)

colors = {
    'reward': '#00ff88',
    'loss': '#ff6b6b',
    'entropy': '#4ecdc4',
    'grad_norm': '#ffd93d',
    'kl': '#a78bfa',
}

def style_ax(ax, title, ylabel, color):
    ax.set_title(title, fontsize=12, fontweight='bold', color=color, pad=10)
    ax.set_ylabel(ylabel, fontsize=10, color='#888888')
    ax.set_xlabel('Step', fontsize=10, color='#888888')
    ax.tick_params(colors='#888888')
    ax.grid(True, alpha=0.15, color='white')
    for spine in ax.spines.values():
        spine.set_color('#333333')

# 1. Reward (top-left) — the headline metric
ax = axes[0, 0]
ax.plot(orch_steps, reward, color=colors['reward'], linewidth=1.5, alpha=0.7)
# Rolling average
window = 5
reward_smooth = np.convolve(reward, np.ones(window)/window, mode='valid')
ax.plot(range(window-1, len(reward)), reward_smooth, color=colors['reward'], linewidth=2.5, label=f'{window}-step avg')
ax.axhline(y=0, color='#555555', linestyle='--', linewidth=0.8)
ax.fill_between(orch_steps, reward, 0, alpha=0.1, color=colors['reward'])
ax.legend(loc='upper left', fontsize=9)
style_ax(ax, 'Reward', 'Reward [-1, +1]', colors['reward'])

# 2. Loss (top-right)
ax = axes[0, 1]
ax.plot(trainer_steps, loss, color=colors['loss'], linewidth=1.5, alpha=0.7)
loss_smooth = np.convolve(loss, np.ones(window)/window, mode='valid')
ax.plot(range(window-1, len(loss)), loss_smooth, color=colors['loss'], linewidth=2.5, label=f'{window}-step avg')
ax.axhline(y=0, color='#555555', linestyle='--', linewidth=0.8)
ax.legend(loc='lower left', fontsize=9)
style_ax(ax, 'GRPO Loss', 'Loss', colors['loss'])

# 3. Entropy (mid-left)
ax = axes[1, 0]
ax.plot(trainer_steps, entropy, color=colors['entropy'], linewidth=1.5, alpha=0.7)
entropy_smooth = np.convolve(entropy, np.ones(window)/window, mode='valid')
ax.plot(range(window-1, len(entropy)), entropy_smooth, color=colors['entropy'], linewidth=2.5, label=f'{window}-step avg')
ax.legend(loc='upper right', fontsize=9)
style_ax(ax, 'Entropy', 'Entropy', colors['entropy'])

# 4. Gradient Norm (mid-right)
ax = axes[1, 1]
ax.plot(trainer_steps, grad_norm, color=colors['grad_norm'], linewidth=1.5, alpha=0.7)
gn_smooth = np.convolve(grad_norm, np.ones(window)/window, mode='valid')
ax.plot(range(window-1, len(grad_norm)), gn_smooth, color=colors['grad_norm'], linewidth=2.5, label=f'{window}-step avg')
ax.legend(loc='upper left', fontsize=9)
style_ax(ax, 'Gradient Norm', 'Grad Norm', colors['grad_norm'])

# 5. Mismatch KL (bottom-left)
ax = axes[2, 0]
ax.plot(trainer_steps, mismatch_kl, color=colors['kl'], linewidth=1.5, alpha=0.7)
kl_smooth = np.convolve(mismatch_kl, np.ones(window)/window, mode='valid')
ax.plot(range(window-1, len(mismatch_kl)), kl_smooth, color=colors['kl'], linewidth=2.5, label=f'{window}-step avg')
ax.legend(loc='upper left', fontsize=9)
style_ax(ax, 'Mismatch KL (Trainer vs Inference)', 'KL Divergence', colors['kl'])

# 6. Summary stats (bottom-right)
ax = axes[2, 1]
ax.axis('off')
summary_text = (
    f"Run: nemotron-all-envs\n"
    f"Model: nvidia/OpenReasoning-Nemotron-14B (14.7B)\n"
    f"Architecture: Qwen2ForCausalLM (dense transformer)\n"
    f"LoRA: rank=32, alpha=64, q/k/v/o_proj\n"
    f"Hardware: 4× H100 80GB (1 inf + 3 train)\n"
    f"\n"
    f"Steps completed: {len(trainer_steps)}/200\n"
    f"Latest reward: {reward[-1]:.4f}  (peak: {max(reward):.4f})\n"
    f"Latest loss: {loss[-1]:.4f}\n"
    f"Latest entropy: {entropy[-1]:.4f}  (start: {entropy[0]:.4f})\n"
    f"Latest grad norm: {grad_norm[-1]:.4f}\n"
    f"\n"
    f"Environments:\n"
    f"  - redteam-attack\n"
    f"  - code-vulnerability\n"
    f"  - config-verification\n"
    f"  - network-logs\n"
    f"  - phishing-detection"
)
ax.text(0.05, 0.95, summary_text, transform=ax.transAxes,
        fontsize=10, fontfamily='monospace', color='#cccccc',
        verticalalignment='top',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='#1a1a2e', edgecolor='#333355'))

plt.tight_layout(rect=[0, 0, 1, 0.95])
plt.savefig('/Users/tetraslam/personal/re-zero/training_metrics.png', dpi=150, bbox_inches='tight',
            facecolor=fig.get_facecolor())
plt.close()
print("Saved to training_metrics.png")
