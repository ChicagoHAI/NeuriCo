#!/bin/bash
# =============================================================================
# neurico-lean Container Entrypoint
# Adds Lean 4 status reporting before handing off to the standard entrypoint.
# =============================================================================

set -e

# Make elan/lean/lake available (installed to /home/neurico/.elan at build time)
export ELAN_HOME="${ELAN_HOME:-/home/neurico/.elan}"
export PATH="${ELAN_HOME}/bin:${PATH}"

# ── Lean status check ────────────────────────────────────────────────────────
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}Lean 4 Status:${NC}"

if command -v lean &>/dev/null; then
    LEAN_VER=$(lean --version 2>/dev/null | head -1)
    LAKE_VER=$(lake --version 2>/dev/null | head -1)
    echo -e "  ${GREEN}[OK]${NC} lean  — ${LEAN_VER}"
    echo -e "  ${GREEN}[OK]${NC} lake  — ${LAKE_VER}"

    # Report whether the Mathlib cache already exists in the global cache dir
    CACHE_DIR="${HOME}/.cache/mathlib"
    if [ -d "${CACHE_DIR}" ] && [ "$(ls -A "${CACHE_DIR}" 2>/dev/null)" ]; then
        CACHE_SIZE=$(du -sh "${CACHE_DIR}" 2>/dev/null | cut -f1)
        echo -e "  ${GREEN}[OK]${NC} Mathlib cache — ${CACHE_SIZE} at ${CACHE_DIR}"
    else
        echo -e "  ${YELLOW}[INFO]${NC} Mathlib cache not yet populated"
        echo -e "         Run setup in workspace: bash .claude/skills/lean-prover/scripts/setup_lean_project.sh"
        echo -e "         First run downloads ~1-2GB (Mathlib.Tactic); cached for subsequent workspaces."
    fi
else
    echo -e "  ${YELLOW}[WARN]${NC} lean not found on PATH — elan may not be installed correctly"
fi

echo ""

# ── Hand off to the standard neurico entrypoint ──────────────────────────────
exec /app/docker/entrypoint.sh "$@"
