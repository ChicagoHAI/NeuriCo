#!/bin/bash
# =============================================================================
# neurico-lean Container Entrypoint
# Adds Lean 4 status reporting before handing off to the standard entrypoint.
# =============================================================================

set -e

# Make elan/lean/lake available (installed to /home/neurico/.elan at build time)
export ELAN_HOME="${ELAN_HOME:-/home/neurico/.elan}"
export PATH="${ELAN_HOME}/bin:${PATH}"

#Lean status check
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

# -----------------------------------------------------------------------------
# Claude isolation: Claude Code 2.1+ writes session-env/ inside its config dir
# at runtime. Windows bind-mounts block new subdirectory creation even with :ro,
# so copy credentials from the read-only host mount into a container-private
# writable directory and point CLAUDE_CONFIG_DIR there before handing off.
# Supports both mount styles: .claude-host and /tmp/.claude (default neurico).
# -----------------------------------------------------------------------------
if [ "${NEURICO_LOGIN_ONLY:-0}" != "1" ]; then
    _claude_src=""
    if [ -d "$HOME/.claude-host" ]; then
        _claude_src="$HOME/.claude-host"
    elif [ -d "/tmp/.claude" ]; then
        _claude_src="/tmp/.claude"
    fi
    if [ -n "$_claude_src" ]; then
        mkdir -p "$HOME/.claude-container"
        for f in .claude.json .credentials.json settings.json; do
            if [ -f "$_claude_src/$f" ]; then
                cp "$_claude_src/$f" "$HOME/.claude-container/$f" 2>/dev/null || true
                chmod 600 "$HOME/.claude-container/$f" 2>/dev/null || true
            fi
        done
        export CLAUDE_CONFIG_DIR="$HOME/.claude-container"
    fi
fi

# Hand off to the standard neurico entrypoint
exec /app/docker/entrypoint.sh "$@"
