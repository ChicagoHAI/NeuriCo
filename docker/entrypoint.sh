#!/bin/bash
# =============================================================================
# idea-explorer Container Entrypoint
# Validates environment, configures credentials, and starts the container
# =============================================================================

set -e

# Ensure PATH includes Python venv, uv-managed Python, and uv (in case not inherited from Dockerfile ENV)
export PATH="/app/.venv/bin:/python/bin:/usr/local/bin:${PATH}"

# Ensure PYTHONPATH includes /app for module imports
export PYTHONPATH="/app:${PYTHONPATH}"

# Handle running as arbitrary user (e.g., with --user flag)
# If HOME is not writable, use /tmp as home
if [ ! -w "${HOME:-/}" ]; then
    export HOME=/tmp
fi

# Color output for better visibility
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  idea-explorer Container Starting${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# -----------------------------------------------------------------------------
# Check version compatibility between Docker image and host code
# -----------------------------------------------------------------------------
check_version_compatibility() {
    # Image version: baked into Docker image at /app/src/__version__.py
    local image_version=""
    if [ -f /app/src/__version__.py ]; then
        image_version=$(python -c "exec(open('/app/src/__version__.py').read()); print(__version__)" 2>/dev/null || echo "")
    fi

    # Host version: mounted from host via config/ directory
    local host_version=""
    if [ -f /app/config/VERSION ]; then
        host_version=$(cat /app/config/VERSION | tr -d '[:space:]')
    fi

    if [ -n "$image_version" ]; then
        echo -e "${BLUE}Version:${NC} ${image_version}"
    fi

    # Compare versions if both are available
    if [ -n "$image_version" ] && [ -n "$host_version" ] && [ "$image_version" != "$host_version" ]; then
        echo ""
        echo -e "  ${RED}WARNING: VERSION MISMATCH${NC}"
        echo -e "  Docker image version:  ${RED}${image_version}${NC}"
        echo -e "  Host code version:     ${GREEN}${host_version}${NC}"
        echo ""
        echo -e "  Your Docker image is out of date. Some features may not work."
        echo -e "  Update with: ${BOLD:-}./idea-explorer build${NC}"
        echo ""
    fi
}

# -----------------------------------------------------------------------------
# Validate environment variables
# -----------------------------------------------------------------------------
validate_env() {
    echo -e "${BLUE}Checking environment...${NC}"

    # Check API keys (optional - CLIs use OAuth, but keys needed for some features)
    # OPENAI_API_KEY: Required for IdeaHub integration and paper-finder
    # GITHUB_TOKEN: Required for GitHub repo creation
    # Note: Claude/Codex/Gemini CLIs use OAuth credentials from ~/.claude, ~/.codex, ~/.gemini

    if [ -n "$OPENAI_API_KEY" ]; then
        echo -e "  ${GREEN}[OK]${NC} OPENAI_API_KEY configured (IdeaHub, paper-finder)"
    else
        echo -e "  ${YELLOW}[INFO]${NC} OPENAI_API_KEY not set (IdeaHub and paper-finder won't work)"
    fi

    if [ -n "$GITHUB_TOKEN" ]; then
        echo -e "  ${GREEN}[OK]${NC} GITHUB_TOKEN configured"
    else
        echo -e "  ${YELLOW}[INFO]${NC} GITHUB_TOKEN not set - use --no-github flag"
    fi

    if [ -n "$S2_API_KEY" ]; then
        echo -e "  ${GREEN}[OK]${NC} S2_API_KEY configured (paper-finder)"
    fi

    echo ""
}

# -----------------------------------------------------------------------------
# Configure git credentials
# -----------------------------------------------------------------------------
setup_git() {
    if [ -n "$GITHUB_TOKEN" ]; then
        echo -e "${BLUE}Configuring Git credentials...${NC}"

        # Configure credential helper
        git config --global credential.helper store

        # Store credentials securely
        echo "https://oauth2:${GITHUB_TOKEN}@github.com" > ~/.git-credentials
        chmod 600 ~/.git-credentials

        # Configure GitHub CLI if available
        if command -v gh &> /dev/null; then
            echo "$GITHUB_TOKEN" | gh auth login --with-token 2>/dev/null || true
        fi

        echo -e "  ${GREEN}[OK]${NC} Git credentials configured"
        echo ""
    fi
}

# -----------------------------------------------------------------------------
# Check GPU availability
# -----------------------------------------------------------------------------
check_gpu() {
    echo -e "${BLUE}GPU Status:${NC}"

    if command -v nvidia-smi &> /dev/null; then
        if nvidia-smi &> /dev/null; then
            nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader | \
                while IFS=',' read -r idx name mem driver; do
                    echo -e "  ${GREEN}[GPU $idx]${NC} $name |$mem | Driver:$driver"
                done
        else
            echo -e "  ${YELLOW}[WARN]${NC} nvidia-smi failed - GPU may not be accessible"
            echo "         Ensure --gpus all flag is used when running the container"
        fi
    else
        echo -e "  ${YELLOW}[WARN]${NC} nvidia-smi not available"
    fi
    echo ""
}

# -----------------------------------------------------------------------------
# Start paper-finder service (if S2_API_KEY is configured)
# -----------------------------------------------------------------------------
start_paper_finder() {
    echo -e "${BLUE}Paper-finder Service:${NC}"

    if [ -n "$S2_API_KEY" ]; then
        if [ -n "$OPENAI_API_KEY" ]; then
            echo -e "  ${GREEN}[OK]${NC} S2_API_KEY configured"

            # Check if paper-finder is installed
            if [ -d "/app/services/paper-finder" ]; then
                echo "  Starting paper-finder service..."

                # Create logs directory if needed
                mkdir -p /app/logs

                # Start paper-finder in background
                cd /app/services/paper-finder/agents/mabool/api
                nohup make start-dev >> /app/logs/paper-finder.log 2>&1 &
                PAPER_FINDER_PID=$!
                cd /workspaces

                # Wait for paper-finder to be healthy (max 60 seconds)
                for i in {1..60}; do
                    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
                        echo -e "  ${GREEN}[OK]${NC} Paper-finder started at localhost:8000"
                        if [ -n "$COHERE_API_KEY" ]; then
                            echo -e "  ${GREEN}[OK]${NC} COHERE_API_KEY configured (full reranking)"
                        else
                            echo -e "  ${YELLOW}[INFO]${NC} COHERE_API_KEY not set (reranking disabled, 92.5% quality)"
                        fi
                        echo ""
                        return 0
                    fi
                    sleep 1
                done
                echo -e "  ${YELLOW}[WARN]${NC} Paper-finder failed to start - using manual search fallback"
                echo "         Check /app/logs/paper-finder.log for errors"
            else
                echo -e "  ${YELLOW}[WARN]${NC} Paper-finder not installed"
            fi
        else
            echo -e "  ${YELLOW}[WARN]${NC} OPENAI_API_KEY required for paper-finder"
        fi
    else
        echo -e "  ${YELLOW}[INFO]${NC} S2_API_KEY not set - paper-finder disabled"
        echo "         Agents will use manual search (arXiv, Semantic Scholar, Papers with Code)"
    fi
    echo ""
}

# -----------------------------------------------------------------------------
# Display available commands
# -----------------------------------------------------------------------------
show_help() {
    echo -e "${BLUE}Available Commands:${NC}"
    echo ""
    echo "  Fetch idea from IdeaHub:"
    echo -e "    ${GREEN}python /app/src/cli/fetch_from_ideahub.py <url> [--submit]${NC}"
    echo ""
    echo "  Submit a research idea:"
    echo -e "    ${GREEN}python /app/src/cli/submit.py <idea.yaml>${NC}"
    echo ""
    echo "  Run research exploration:"
    echo -e "    ${GREEN}python /app/src/core/runner.py <idea_id> [options]${NC}"
    echo ""
    echo "  Options for runner.py:"
    echo "    --provider {claude|codex|gemini}  AI provider (default: claude)"
    echo "    --full-permissions                Skip permission prompts"
    echo "    --no-github                       Run locally without GitHub"
    echo "    --timeout SECONDS                 Execution timeout (default: 3600)"
    echo ""
    echo -e "${BLUE}Workspace:${NC} /workspaces (mounted from host)"
    echo -e "${BLUE}App:${NC} /app"
    echo ""
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

# Run all setup steps
check_version_compatibility
validate_env
setup_git
check_gpu
start_paper_finder

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Container Ready${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

show_help

# Execute the command passed to the container
exec "$@"
