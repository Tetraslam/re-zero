#!/usr/bin/env bash
# Run training jobs in a tmux session for resilience.
# Usage:
#   ./run_training.sh <config>              # fresh start
#   ./run_training.sh <config> --resume     # resume from latest checkpoint
#   ./run_training.sh all                   # run priority queue (Phase 1 configs)
#
# The tmux session is named "re-zero-train". Attach with: tmux attach -t re-zero-train
# Detach with: Ctrl-B then D

set -euo pipefail
cd "$(dirname "$0")"

export MODAL_CONFIG_PATH="$(pwd)/.modal.toml"
LOGDIR="$(pwd)/logs"
mkdir -p "$LOGDIR"

run_one() {
    local config="$1"
    local resume_flag="${2:-}"
    local logfile="$LOGDIR/$(basename "$config" .toml)-$(date +%Y%m%d-%H%M%S).log"

    echo "═══════════════════════════════════════════════════════"
    echo "  Training: $config $resume_flag"
    echo "  Log: $logfile"
    echo "  Started: $(date)"
    echo "═══════════════════════════════════════════════════════"

    uv run modal run deploy/train.py --config "$config" $resume_flag 2>&1 | tee "$logfile"
    local exit_code=${PIPESTATUS[0]}

    if [ $exit_code -eq 0 ]; then
        echo "[$(date)] ✓ $config completed successfully"
    else
        echo "[$(date)] ✗ $config failed with exit code $exit_code"
    fi
    return $exit_code
}

# Priority training queue: most impactful runs first
PHASE1_CONFIGS=(
    "nemotron-redteam.toml"
    "nemotron-codevuln.toml"
    "glm47v-codevuln.toml"
    "glm47v-redteam.toml"
)

PHASE2_CONFIGS=(
    "nemotron-config-verification.toml"
    "nemotron-phishing.toml"
    "nemotron-network-logs.toml"
    "glm47v-config-verification.toml"
    "glm47v-phishing.toml"
    "glm47v-network-logs.toml"
)

run_queue() {
    local configs=("$@")
    local failed=()

    for config in "${configs[@]}"; do
        if ! run_one "$config"; then
            failed+=("$config")
            echo "[$(date)] Continuing to next config despite failure..."
        fi
        echo ""
    done

    if [ ${#failed[@]} -gt 0 ]; then
        echo "═══════════════════════════════════════════════════════"
        echo "  Failed configs: ${failed[*]}"
        echo "═══════════════════════════════════════════════════════"
    fi
}

if [ "${1:-}" = "all" ]; then
    echo "Running Phase 1 training queue (4 priority configs)..."
    run_queue "${PHASE1_CONFIGS[@]}"
    echo ""
    echo "Phase 1 complete. Run './run_training.sh phase2' for remaining configs."
elif [ "${1:-}" = "phase2" ]; then
    echo "Running Phase 2 training queue (6 remaining configs)..."
    run_queue "${PHASE2_CONFIGS[@]}"
elif [ "${1:-}" = "tmux" ]; then
    # Launch Phase 1 in a tmux session
    tmux new-session -d -s re-zero-train "cd $(pwd) && ./run_training.sh all; echo 'Press Enter to exit'; read"
    echo "Training launched in tmux session 're-zero-train'"
    echo "  Attach: tmux attach -t re-zero-train"
    echo "  Detach: Ctrl-B then D"
    echo "  Logs:   $LOGDIR/"
elif [ -n "${1:-}" ]; then
    run_one "$1" "${2:-}"
else
    echo "Usage:"
    echo "  ./run_training.sh <config.toml>          # run single config"
    echo "  ./run_training.sh <config.toml> --resume  # resume from checkpoint"
    echo "  ./run_training.sh all                     # run Phase 1 queue"
    echo "  ./run_training.sh phase2                  # run Phase 2 queue"
    echo "  ./run_training.sh tmux                    # run Phase 1 in tmux session"
    echo ""
    echo "Configs:"
    ls -1 configs/*.toml 2>/dev/null || echo "  (none found)"
fi
