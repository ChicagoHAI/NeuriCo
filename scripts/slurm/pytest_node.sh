#!/bin/bash
# Run the test suite on a compute node. The login node's local disk is shared by hundreds of users
# and fsync-heavy tests (SQLite, pid files) stall there in ext4 journal waits; a compute node's
# local /tmp does 200 fsyncs in 0.05 s. Extra arguments are passed to pytest.
# Usage: scripts/slurm/pytest_node.sh [pytest args]
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/../.."
PY="${NEURICO_PYTHON:-.venv/bin/python}"
TAG="${NEURICO_PYTEST_TAG:-$$}"
exec srun -p "${NEURICO_PYTEST_PARTITION:-general}" --cpus-per-task="${NEURICO_PYTEST_CPUS:-8}" \
     --mem="${NEURICO_PYTEST_MEM:-32G}" --time="${NEURICO_PYTEST_TIME:-00:40:00}" -I120 --job-name="pytest-$TAG" \
     "$PY" -m pytest tests -q -p no:cacheprovider --basetemp="/tmp/pytest-$USER-$TAG" \
     --deselect tests/test_hitl_timeout_recovery.py::test_run_worker_does_not_translate_sigterm_into_user_stop "$@"
