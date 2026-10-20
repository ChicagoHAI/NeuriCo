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
export PATH="$HOME/.local/bin:$PATH"
GPUS=$(nvidia-smi --query-gpu=index --format=csv,noheader | paste -sd, -)
echo "node $(hostname) gpus=$GPUS job=$SLURM_JOB_ID started $(date -Is)"
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
CAMPAIGN="${NEURICO_CAMPAIGN:-open-weight-scorecards}"
./neurico --host safety start --campaign "$CAMPAIGN" --gpus "$GPUS" --max-neurico-jobs 2 --max-suite-jobs 1 --force &
DAEMON=$!
trap 'echo "time limit approaching: stopping daemon"; kill -TERM $DAEMON; wait $DAEMON' TERM
wait $DAEMON
echo "daemon exited $(date -Is)"
