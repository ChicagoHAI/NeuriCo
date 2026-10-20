#!/bin/bash
#SBATCH --job-name=neurico-safety
#SBATCH --partition=general,complementary-ai
#SBATCH --gres=gpu:4
#SBATCH --constraint="a100|h100|h200"
#SBATCH --time=12:00:00
#SBATCH --mem=200G
#SBATCH --cpus-per-task=16
#SBATCH --output=logs/slurm/safety-daemon-%j.out
#SBATCH --error=logs/slurm/safety-daemon-%j.err
#SBATCH --signal=B:TERM@600
#
# Runs the NeuriCo safety engine daemon in host mode on a GPU node. The daemon
# resumes its queue from safety_kb/queue/state.json, so resubmitting this job
# after the allocation ends continues the work (scripts/slurm/ensure_daemon.sh).
set -euo pipefail
cd "${NEURICO_ROOT:-$SLURM_SUBMIT_DIR}"
S=$(dirname "$PWD")
export NEURICO_MODE=host
export UV_CACHE_DIR="$S/.uv_cache" UV_PYTHON_INSTALL_DIR="$S/.uv_python"
export NEURICO_HF_CACHE="$S/hf_cache" HF_HOME="$S/hf_cache"
export NEURICO_SAFETY_VENV="$S/safety_venv"
export NEURICO_SAFETY_KB="$PWD/safety_kb"
export NEURICO_CODEX_CATALOG_DIR="$S/.codex-catalog"
# Keep every cache (vLLM compile, torch inductor, triton, HF, uv) on the share, not in /home.
export NEURICO_CACHE_ROOT="$S/.cache" XDG_CACHE_HOME="$S/.cache"
export VLLM_CACHE_ROOT="$S/.cache/vllm" TORCHINDUCTOR_CACHE_DIR="$S/.cache/torchinductor" TRITON_CACHE_DIR="$S/.cache/triton"
export NEURICO_VLLM_STARTUP_TIMEOUT=2700
mkdir -p "$S/.cache"
export PATH="$HOME/.local/bin:$PATH"
# Only one daemon may own the queue: cancel pending siblings, bow out if another is running.
for sib in $(squeue -u "$USER" -h -n neurico-safety -t PENDING -o %i); do
    [ "$sib" != "$SLURM_JOB_ID" ] && scancel "$sib" && echo "cancelled pending sibling $sib"
done
if squeue -u "$USER" -h -n neurico-safety -t RUNNING -o %i | grep -v -x "$SLURM_JOB_ID" | grep -q .; then
    echo "another neurico-safety daemon is already running; exiting"; exit 0
fi
GPUS=$(nvidia-smi --query-gpu=index --format=csv,noheader | paste -sd, -)
GPU_GB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | sort -n | head -1 | awk '{printf "%d", $1/1024}')
echo "node $(hostname) gpus=$GPUS job=$SLURM_JOB_ID started $(date -Is)"
nvidia-smi --query-gpu=index,name,driver_version,memory.total --format=csv,noheader
# CUDA self-check: some nodes expose GPUs but cannot initialise the driver (cuInit error).
# Record such a node and exit so ensure_daemon.sh resubmits elsewhere.
if ! "$NEURICO_SAFETY_VENV/bin/python" -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)"; then
    echo "CUDA self-check FAILED on $(hostname): torch.cuda.is_available() is false; excluding this node" >&2
    mkdir -p logs/slurm && echo "$(hostname)" >> logs/slurm/bad_nodes.txt
    exit 3
fi
echo "CUDA self-check OK on $(hostname)"
CAMPAIGN="${NEURICO_CAMPAIGN:-open-weight-scorecards}"
./neurico --host safety start --campaign "$CAMPAIGN" --gpus "$GPUS" --gpu-memory-gb "$GPU_GB" --max-neurico-jobs 2 --max-suite-jobs 1 --force &
DAEMON=$!
trap 'echo "time limit approaching: stopping daemon"; kill -TERM $DAEMON; wait $DAEMON' TERM
wait $DAEMON
echo "daemon exited $(date -Is)"
