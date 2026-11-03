#!/bin/bash
#SBATCH --job-name=neurico-suite-once
#SBATCH --partition=general
#SBATCH --gres=gpu:1
#SBATCH --constraint="a100|h100|h200"
#SBATCH --prefer="h200|h100"
#SBATCH --time=12:00:00
#SBATCH --mem=96G
#SBATCH --cpus-per-task=8
#SBATCH --output=logs/slurm/suite-once-%j.out
#SBATCH --error=logs/slurm/suite-once-%j.err
#
# Run one queued suite's (evals x model) pairs once, without the daemon (which stays paused).
# Results go to the suite's normal results dir; pairs already marked success are skipped, so
# a resubmit resumes. Parallel per-model jobs write per-model summary files.
#   SUITE=<id> MODEL=<catalog id> EVALS="a b c" sbatch --exclude=$(paste -sd, logs/slurm/bad_nodes.txt) \
#       scripts/slurm/suite_once.sbatch
set -euo pipefail
cd "${NEURICO_ROOT:-$SLURM_SUBMIT_DIR}"
S=$(dirname "$PWD")
: "${SUITE:?}" "${MODEL:?}" "${EVALS:?}"
export NEURICO_MODE=host NEURICO_SAFETY_KB="$PWD/safety_kb"
MODELS_DIR="${NEURICO_MODELS_DIR:-/net/spaces/chenhao/chai-lab-models/haokunliu/models}"
export HF_HOME="$MODELS_DIR/hf_cache" NEURICO_HF_CACHE="$MODELS_DIR/hf_cache"
LOCAL_SCRATCH=""
for cand in "${SLURM_TMPDIR:-}" /local/scratch/$USER /local/$USER /scratch/$USER /tmp/$USER; do
    [ -n "$cand" ] || continue
    if mkdir -p "$cand" 2>/dev/null && [ -w "$cand" ]; then LOCAL_SCRATCH="$cand"; break; fi
done
CACHE="${LOCAL_SCRATCH:-$S}/.cache"
mkdir -p "$CACHE"
export XDG_CACHE_HOME="$CACHE" VLLM_CACHE_ROOT="$CACHE/vllm" TORCHINDUCTOR_CACHE_DIR="$CACHE/torchinductor" TRITON_CACHE_DIR="$CACHE/triton"
export NEURICO_VLLM_STARTUP_TIMEOUT=2700
PY="$S/safety_venv/bin/python"
echo "node $(hostname) job=$SLURM_JOB_ID gpus=${CUDA_VISIBLE_DEVICES:-} suite=$SUITE model=$MODEL started $(date -Is)"
nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv,noheader
if ! "$PY" -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)"; then
    echo "CUDA self-check FAILED on $(hostname)" >&2
    echo "$(hostname)" >> logs/slurm/bad_nodes.txt
    exit 3
fi
OUT="$PWD/safety_kb/results/$SUITE"
# shellcheck disable=SC2086
"$PY" src/safety/suites.py --job "$SUITE" --out "$OUT" --evals $EVALS --models "$MODEL" \
    --gpu "${CUDA_VISIBLE_DEVICES:-0}" --summary-name "summary.$MODEL.json"
echo "finished $(date -Is)"
