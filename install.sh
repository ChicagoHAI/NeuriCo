#!/bin/bash
# =============================================================================
# NeuriCo — One-Liner Installer
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ChicagoHAI/neurico/main/install.sh | bash
#
# Or with a custom install directory:
#   INSTALL_DIR=~/my-folder curl -fsSL ... | bash
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

main() {
    echo -e "${BLUE}${BOLD}"
    echo '  _   _                 _  ____       '
    echo ' | \ | | ___ _   _ _ __(_)/ ___|___   '
    echo ' |  \| |/ _ \ | | |  __| | |   / _ \  '
    echo ' | |\  |  __/ |_| | |  | | |__| (_) | '
    echo ' |_| \_|\___|\__,_|_|  |_|\____\___/  '
    echo -e "${NC}"
    echo -e "  ${DIM}Autonomous Research Framework — Installer${NC}"
    echo ""

    # ── Check prerequisites ──
    local missing=false

    if ! command -v git &> /dev/null; then
        echo -e "  ${RED}[MISSING]${NC} git — install: sudo apt install git (or brew install git)"
        missing=true
    fi

    if ! command -v docker &> /dev/null; then
        echo -e "  ${RED}[MISSING]${NC} docker — install: https://docs.docker.com/get-docker/"
        missing=true
    fi

    if [ "$missing" = true ]; then
        echo ""
        echo -e "  ${RED}Please install the missing tools above, then re-run this script.${NC}"
        exit 1
    fi

    echo -e "  ${GREEN}[OK]${NC} Prerequisites satisfied (git, docker)"
    echo ""

    # ── Clone or update repo ──
    local install_dir="${INSTALL_DIR:-$(pwd)/neurico}"

    if [ -d "$install_dir/.git" ]; then
        echo -e "  ${DIM}Found existing install at $install_dir${NC}"
        echo -ne "  Update with git pull? [Y/n] "
        read update_choice < /dev/tty
        if [[ ! "$update_choice" =~ ^[Nn] ]]; then
            echo -e "  Updating code..."
            git -C "$install_dir" pull --ff-only || {
                echo -e "  ${YELLOW}[WARN]${NC} git pull failed — continuing with existing version"
            }
            # Force pull the latest Docker image to stay in sync with updated code
            echo -e "  Updating Docker image..."
            local _pull_platform=""
            [[ "$(uname)" == "Darwin" ]] && _pull_platform="--platform linux/amd64"
            if docker pull $_pull_platform ghcr.io/chicagohai/neurico:latest 2>/dev/null; then
                docker tag ghcr.io/chicagohai/neurico:latest chicagohai/neurico:latest
                echo -e "  ${GREEN}[OK]${NC} Docker image updated"
            else
                echo -e "  ${YELLOW}[WARN]${NC} Docker image pull failed — run './neurico build' later"
            fi
        fi
    else
        echo -e "  Cloning to ${BOLD}$install_dir${NC}..."
        git clone https://github.com/ChicagoHAI/neurico "$install_dir"
        echo -e "  ${GREEN}[OK]${NC} Repository cloned"
    fi
    echo ""

    # ── Launch setup wizard ──
    echo -e "  Launching interactive setup wizard..."
    echo ""
    cd "$install_dir"
    exec ./neurico setup
}

main
