"""Generate training metrics chart from the current Nemotron-14B GRPO run (steps 0-96)."""
import matplotlib.pyplot as plt
import numpy as np

# === TRAINER DATA (steps 0-94) ===
# Steps 0-24 from earlier log extraction, 25-94 from Modal logs
trainer_steps = list(range(95))
loss = [
    # 0-24
    0.0000, 0.0000, -0.0000, -0.0000, 0.0000, -0.0001, -0.0000, 0.0001, 0.0000, -0.0000,
    -0.0000, -0.0000, -0.0000, 0.0000, -0.0001, -0.0000, -0.0000, 0.0000, 0.0000, 0.0000,
    -0.0002, -0.0000, -0.0001, -0.0000, 0.0000,
    # 25-54
    0.0000, -0.0002, -0.0002, -0.0000, -0.0000, -0.0000, -0.0000, -0.0000, -0.0004, -0.0001,
    -0.0002, -0.0002, -0.0001, -0.0001, -0.0003, -0.0007, -0.0006, -0.0005, -0.0000, -0.0000,
    -0.0002, 0.0000, 0.0000, 0.0001, -0.0009, -0.0003, -0.0006, -0.0005, -0.0008, -0.0012,
    # 55-74
    -0.0002, -0.0009, -0.0008, -0.0004, -0.0007, -0.0024, -0.0014, -0.0008, -0.0015, -0.0018,
    -0.0034, -0.0030, -0.0031, -0.0008, -0.0039, -0.0021, -0.0037, -0.0030, -0.0026, -0.0027,
    # 75-94
    -0.0039, -0.0021, -0.0011, -0.0015, -0.0017, -0.0007, -0.0008, -0.0014, -0.0005, 0.0001,
    -0.0045, -0.0001, -0.0033, -0.0007, -0.0004, -0.0022, -0.0001, -0.0020, -0.0000, 0.0001,
]
entropy = [
    # 0-24
    0.4882, 0.4806, 0.4826, 0.4864, 0.4833, 0.4682, 0.4993, 0.4902, 0.4903, 0.4815,
    0.4828, 0.4901, 0.4770, 0.4793, 0.4819, 0.4892, 0.4947, 0.5102, 0.4986, 0.4897,
    0.4839, 0.4695, 0.4901, 0.4998, 0.4877,
    # 25-54
    0.4855, 0.4860, 0.5076, 0.4821, 0.4786, 0.4801, 0.4643, 0.4912, 0.4848, 0.4923,
    0.4684, 0.4580, 0.4565, 0.4712, 0.4610, 0.4351, 0.4374, 0.4328, 0.4376, 0.4621,
    0.4565, 0.4409, 0.4593, 0.4330, 0.4023, 0.4211, 0.4207, 0.4387, 0.4133, 0.4024,
    # 55-74
    0.4361, 0.4248, 0.4389, 0.4379, 0.4306, 0.4179, 0.3891, 0.3978, 0.4144, 0.3828,
    0.4023, 0.3848, 0.4085, 0.3735, 0.3399, 0.3709, 0.3648, 0.3576, 0.3537, 0.3675,
    # 75-94
    0.3427, 0.3616, 0.3576, 0.3422, 0.3499, 0.3360, 0.3448, 0.3298, 0.3530, 0.3310,
    0.3678, 0.3377, 0.3897, 0.3451, 0.3528, 0.3402, 0.3817, 0.3925, 0.3258, 0.3256,
]
grad_norm = [
    # 0-24
    0.0000, 0.0051, 0.0008, 0.0006, 0.0023, 0.0022, 0.0006, 0.0058, 0.0007, 0.0005,
    0.0013, 0.0014, 0.0013, 0.0012, 0.0047, 0.0013, 0.0003, 0.0029, 0.0012, 0.0045,
    0.0064, 0.0005, 0.0017, 0.0018, 0.0000,
    # 25-54
    0.0015, 0.0087, 0.0048, 0.0015, 0.0008, 0.0004, 0.0008, 0.0046, 0.0104, 0.0057,
    0.0056, 0.0078, 0.0046, 0.0058, 0.0045, 0.0093, 0.0095, 0.0116, 0.0111, 0.0050,
    0.0086, 0.0075, 0.0080, 0.0117, 0.0131, 0.0112, 0.0151, 0.0192, 0.0101, 0.0199,
    # 55-74
    0.0197, 0.0187, 0.0157, 0.0180, 0.0181, 0.0245, 0.0223, 0.0208, 0.0246, 0.0542,
    0.0279, 0.0319, 0.0316, 0.0318, 0.0311, 0.0307, 0.0338, 0.0366, 0.0413, 0.0329,
    # 75-94
    0.0313, 0.0320, 0.0303, 0.0311, 0.0267, 0.0263, 0.0234, 0.0271, 0.0228, 0.0165,
    0.0246, 0.0209, 0.0212, 0.0218, 0.0235, 0.0203, 0.0204, 0.0156, 0.0196, 0.0210,
]
mismatch_kl = [
    # 0-24
    0.0009, 0.0009, 0.0009, 0.0010, 0.0009, 0.0009, 0.0010, 0.0010, 0.0009, 0.0009,
    0.0010, 0.0009, 0.0009, 0.0009, 0.0009, 0.0009, 0.0009, 0.0010, 0.0010, 0.0009,
    0.0010, 0.0009, 0.0010, 0.0010, 0.0010,
    # 25-54
    0.0009, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010, 0.0011, 0.0012, 0.0012, 0.0012,
    0.0014, 0.0012, 0.0014, 0.0014, 0.0013, 0.0011, 0.0010, 0.0010, 0.0009, 0.0010,
    0.0009, 0.0010, 0.0010, 0.0009, 0.0009, 0.0008, 0.0009, 0.0010, 0.0009, 0.0010,
    # 55-74
    0.0010, 0.0010, 0.0010, 0.0011, 0.0010, 0.0009, 0.0011, 0.0011, 0.0008, 0.0009,
    0.0008, 0.0009, 0.0009, 0.0008, 0.0009, 0.0009, 0.0008, 0.0011, 0.0011, 0.0010,
    # 75-94
    0.0011, 0.0012, 0.0014, 0.0010, 0.0010, 0.0009, 0.0009, 0.0010, 0.0009, 0.0009,
    0.0010, 0.0009, 0.0010, 0.0009, 0.0009, 0.0009, 0.0010, 0.0009, 0.0009, 0.0009,
]

# === ORCHESTRATOR DATA (reward, steps 0-96) ===
orch_steps = list(range(97))
reward = [
    # 0-25
    0.0000, 0.0160, 0.0043, 0.0030, 0.0170, 0.0159, 0.0030, -0.0056, 0.0034, 0.0021,
    0.0067, 0.0089, 0.0089, 0.0047, 0.0160, 0.0077, 0.0011, -0.0725, 0.0041, 0.0078,
    0.0219, 0.0024, 0.0125, 0.0111, 0.0000, 0.0077,
    # 26-55
    0.0209, 0.0012, 0.0079, 0.0043, 0.0021, 0.0033, 0.0263, 0.0561, 0.0160, 0.0239,
    0.0638, 0.0324, 0.0240, 0.0410, 0.0691, 0.0967, 0.0965, 0.0682, 0.0445, 0.0338,
    0.0463, 0.0410, 0.1053, 0.1364, 0.0857, 0.1479, 0.1815, 0.0852, 0.2069, 0.2290,
    # 56-75
    0.1717, 0.1698, 0.1832, 0.2109, 0.3216, 0.3648, 0.2729, 0.4068, 0.4745, 0.5688,
    0.5710, 0.5978, 0.8079, 0.7149, 0.8304, 0.9607, 0.9066, 0.8546, 1.0810, 1.0108,
    # 76-96
    1.0439, 1.1647, 1.2574, 1.4395, 1.3708, 1.5222, 1.4688, 1.5353, 1.5380, 1.5233,
    1.5761, 1.5625, 1.5039, 1.4575, 1.5777, 1.6373, 1.4973, 1.5197, 1.6002, 1.6192,
    1.6241,
]

# === CHART ===
plt.style.use('dark_background')
fig, axes = plt.subplots(3, 2, figsize=(16, 14))
fig.suptitle(
    'OpenReasoning-Nemotron-14B  |  GRPO Training  |  5 CTF Environments\n'
    '4×H100  |  LoRA r=32  |  batch=128  |  rollouts/ex=4  |  Steps 0–96 of 200',
    fontsize=14, fontweight='bold', color='white', y=0.98
)

colors = {
    'reward': '#00ff88',
    'loss': '#ff6b6b',
    'entropy': '#4ecdc4',
    'grad_norm': '#ffd93d',
    'kl': '#a78bfa',
}
window = 7  # smoothing window


def style_ax(ax, title, ylabel, color):
    ax.set_title(title, fontsize=12, fontweight='bold', color=color, pad=10)
    ax.set_ylabel(ylabel, fontsize=10, color='#888888')
    ax.set_xlabel('Step', fontsize=10, color='#888888')
    ax.tick_params(colors='#888888')
    ax.grid(True, alpha=0.15, color='white')
    for spine in ax.spines.values():
        spine.set_color('#333333')


def smooth(data, w):
    return np.convolve(data, np.ones(w) / w, mode='valid')


# 1. Reward
ax = axes[0, 0]
ax.plot(orch_steps, reward, color=colors['reward'], linewidth=1.0, alpha=0.5)
r_smooth = smooth(reward, window)
ax.plot(range(window - 1, len(reward)), r_smooth, color=colors['reward'], linewidth=2.5, label=f'{window}-step avg')
ax.axhline(y=0, color='#555555', linestyle='--', linewidth=0.8)
ax.fill_between(orch_steps, reward, 0, alpha=0.08, color=colors['reward'])
ax.legend(loc='upper left', fontsize=9)
style_ax(ax, 'Reward (0 → 1.6!)', 'Reward [-1, +1]', colors['reward'])

# 2. Loss
ax = axes[0, 1]
ax.plot(trainer_steps, loss, color=colors['loss'], linewidth=1.0, alpha=0.5)
l_smooth = smooth(loss, window)
ax.plot(range(window - 1, len(loss)), l_smooth, color=colors['loss'], linewidth=2.5, label=f'{window}-step avg')
ax.axhline(y=0, color='#555555', linestyle='--', linewidth=0.8)
ax.legend(loc='lower left', fontsize=9)
style_ax(ax, 'GRPO Loss', 'Loss', colors['loss'])

# 3. Entropy
ax = axes[1, 0]
ax.plot(trainer_steps, entropy, color=colors['entropy'], linewidth=1.0, alpha=0.5)
e_smooth = smooth(entropy, window)
ax.plot(range(window - 1, len(entropy)), e_smooth, color=colors['entropy'], linewidth=2.5, label=f'{window}-step avg')
ax.legend(loc='upper right', fontsize=9)
style_ax(ax, 'Entropy (0.49 → 0.33)', 'Entropy', colors['entropy'])

# 4. Gradient Norm
ax = axes[1, 1]
ax.plot(trainer_steps, grad_norm, color=colors['grad_norm'], linewidth=1.0, alpha=0.5)
g_smooth = smooth(grad_norm, window)
ax.plot(range(window - 1, len(grad_norm)), g_smooth, color=colors['grad_norm'], linewidth=2.5, label=f'{window}-step avg')
ax.legend(loc='upper left', fontsize=9)
style_ax(ax, 'Gradient Norm (0.001 → 0.03)', 'Grad Norm', colors['grad_norm'])

# 5. Mismatch KL
ax = axes[2, 0]
ax.plot(trainer_steps, mismatch_kl, color=colors['kl'], linewidth=1.0, alpha=0.5)
k_smooth = smooth(mismatch_kl, window)
ax.plot(range(window - 1, len(mismatch_kl)), k_smooth, color=colors['kl'], linewidth=2.5, label=f'{window}-step avg')
ax.legend(loc='upper left', fontsize=9)
style_ax(ax, 'Mismatch KL (Trainer vs Inference)', 'KL Divergence', colors['kl'])

# 6. Summary
ax = axes[2, 1]
ax.axis('off')
summary_text = (
    f"Run: nemotron-all-envs (v1 baseline)\n"
    f"Model: nvidia/OpenReasoning-Nemotron-14B (14.7B)\n"
    f"Architecture: Qwen2ForCausalLM (dense transformer)\n"
    f"LoRA: rank=32, alpha=64, q/k/v/o_proj\n"
    f"Hardware: 4x H100 80GB (1 inf + 3 train)\n"
    f"\n"
    f"Steps completed: 96/200\n"
    f"Latest reward:   {reward[-1]:.4f}  (peak: {max(reward):.4f})\n"
    f"Latest loss:     {loss[-1]:.4f}\n"
    f"Latest entropy:  {entropy[-1]:.4f}  (start: {entropy[0]:.4f})\n"
    f"Latest grad norm:{grad_norm[-1]:.4f}  (start: {grad_norm[1]:.4f})\n"
    f"\n"
    f"Environments:\n"
    f"  - redteam-attack\n"
    f"  - code-vulnerability\n"
    f"  - config-verification\n"
    f"  - network-logs\n"
    f"  - phishing-detection\n"
    f"\n"
    f"v2 run planned: 8xH100, 16 rollouts/ex,\n"
    f"batch=64, temp=0.9, 300 steps"
)
ax.text(0.05, 0.95, summary_text, transform=ax.transAxes,
        fontsize=10, fontfamily='monospace', color='#cccccc',
        verticalalignment='top',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='#1a1a2e', edgecolor='#333355'))

plt.tight_layout(rect=[0, 0, 1, 0.95])
plt.savefig('/Users/tetraslam/personal/re-zero/training_metrics_v2.png', dpi=150, bbox_inches='tight',
            facecolor=fig.get_facecolor())
plt.close()
print("Saved to training_metrics_v2.png")
