#!/bin/bash
# =============================================================================
# NeuriCo Docker Runner
# Handles GPU passthrough and credential mounting for containerized execution
# =============================================================================

set -e

# Get script and project directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
IMAGE_NAME="chicagohai/neurico:latest"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# -----------------------------------------------------------------------------
# ASCII Art Banner
# -----------------------------------------------------------------------------
show_banner() {
    echo -e "${BLUE}${BOLD}"
    echo '  _   _                 _  ____       '
    echo ' | \ | | ___ _   _ _ __(_)/ ___|___   '
    echo ' |  \| |/ _ \ | | |  __| | |   / _ \  '
    echo ' | |\  |  __/ |_| | |  | | |__| (_) | '
    echo ' |_| \_|\___|\__,_|_|  |_|\____\___/  '
    echo -e "${NC}"
    local version=""
    if [ -f "$PROJECT_ROOT/config/VERSION" ]; then
        version=$(cat "$PROJECT_ROOT/config/VERSION" | tr -d '[:space:]')
    fi
    echo -e "  ${DIM}Autonomous Research Framework${NC}  ${CYAN}v${version:-unknown}${NC}  ${DIM}github.com/ChicagoHAI/neurico${NC}"
    echo ""
}

# -----------------------------------------------------------------------------
# Status dashboard
# -----------------------------------------------------------------------------
show_status() {
    echo -e "  ${BOLD}Status:${NC}"

    # Docker
    if command -v docker &> /dev/null; then
        echo -e "    Docker .............. ${GREEN}[OK]${NC}"
    else
        echo -e "    Docker .............. ${RED}[MISSING]${NC} install docker first"
    fi

    # Docker image (with version check)
    if docker image inspect "$IMAGE_NAME" &> /dev/null; then
        local host_version=$(cat "$PROJECT_ROOT/config/VERSION" 2>/dev/null | tr -d '[:space:]')
        local cached_version=$(cat "$PROJECT_ROOT/.docker-image-version" 2>/dev/null | tr -d '[:space:]')
        if [ -n "$host_version" ] && [ -n "$cached_version" ] && [ "$host_version" != "$cached_version" ]; then
            echo -e "    Docker image ........ ${YELLOW}[OUTDATED]${NC} image v${cached_version}, code v${host_version}"
            echo -e "                          Run: ${BOLD}./neurico build${NC} to update"
        else
            echo -e "    Docker image ........ ${GREEN}[OK]${NC} $IMAGE_NAME"
        fi
    else
        echo -e "    Docker image ........ ${YELLOW}[MISSING]${NC} run: ./neurico setup"
    fi

    # GPU
    if docker info 2>/dev/null | grep -qi nvidia; then
        echo -e "    GPU ................. ${GREEN}[OK]${NC} nvidia-container-toolkit"
    else
        echo -e "    GPU ................. ${YELLOW}[WARN]${NC} nvidia-container-toolkit not found"
    fi

    # .env
    if [ -f "$PROJECT_ROOT/.env" ]; then
        echo -e "    .env ................ ${GREEN}[OK]${NC} configured"
    else
        echo -e "    .env ................ ${YELLOW}[MISSING]${NC} run: ./neurico setup"
    fi

    # Claude credentials
    if [ -d "$HOME/.claude" ] && [ "$(ls -A "$HOME/.claude" 2>/dev/null)" ]; then
        echo -e "    Claude credentials .. ${GREEN}[OK]${NC} ~/.claude found"
    else
        echo -e "    Claude credentials .. ${DIM}[--]${NC} not configured"
    fi

    # Codex credentials
    if [ -d "$HOME/.codex" ] && [ "$(ls -A "$HOME/.codex" 2>/dev/null)" ]; then
        echo -e "    Codex credentials ... ${GREEN}[OK]${NC} ~/.codex found"
    fi

    # Gemini credentials
    if [ -d "$HOME/.gemini" ] && [ "$(ls -A "$HOME/.gemini" 2>/dev/null)" ]; then
        echo -e "    Gemini credentials .. ${GREEN}[OK]${NC} ~/.gemini found"
    fi

    echo ""
}

# -----------------------------------------------------------------------------
# Check Docker is available
# -----------------------------------------------------------------------------
check_docker() {
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}Error: Docker not found${NC}"
        echo "Please install Docker to use neurico containers."
        exit 1
    fi
}

# -----------------------------------------------------------------------------
# Get user ID flags to match host user (fixes permission issues with mounted volumes)
# -----------------------------------------------------------------------------
get_user_flags() {
    echo "--user $(id -u):$(id -g)"
}

# -----------------------------------------------------------------------------
# Get TTY flag (only allocate pseudo-terminal when one is available)
# This allows neurico to be invoked as a subprocess without failing
# -----------------------------------------------------------------------------
get_tty_flag() {
    if [ -t 0 ]; then
        echo "-it"
    else
        echo "-i"
    fi
}

# -----------------------------------------------------------------------------
# Get GPU flags (auto-detects availability)
# -----------------------------------------------------------------------------
get_gpu_flags() {
    if docker info 2>/dev/null | grep -qi nvidia; then
        echo "--gpus all"
    else
        echo -e "${YELLOW}Note: Running without GPU (nvidia-container-toolkit not configured)${NC}" >&2
        echo -e "      To enable GPU: sudo apt install nvidia-container-toolkit && sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker" >&2
        echo ""
    fi
}

# -----------------------------------------------------------------------------
# Get CLI credential mounts (for Claude, Codex, Gemini authentication)
# When running with --user flag, HOME=/tmp, so mount credentials there
# -----------------------------------------------------------------------------
get_cli_credential_mounts() {
    local mounts=""
    local found_any=false

    echo -e "${BLUE}Checking CLI credentials...${NC}" >&2

    # Claude Code credentials (~/.claude/)
    if [ -d "$HOME/.claude" ] && [ "$(ls -A "$HOME/.claude" 2>/dev/null)" ]; then
        mounts="$mounts -v \"$HOME/.claude:/tmp/.claude\""
        echo -e "  ${GREEN}[OK]${NC} Mounting Claude credentials" >&2
        found_any=true
    fi

    # Codex credentials (~/.codex/)
    if [ -d "$HOME/.codex" ] && [ "$(ls -A "$HOME/.codex" 2>/dev/null)" ]; then
        mounts="$mounts -v \"$HOME/.codex:/tmp/.codex\""
        echo -e "  ${GREEN}[OK]${NC} Mounting Codex credentials" >&2
        found_any=true
    fi

    # Gemini CLI credentials (~/.gemini/)
    if [ -d "$HOME/.gemini" ] && [ "$(ls -A "$HOME/.gemini" 2>/dev/null)" ]; then
        mounts="$mounts -v \"$HOME/.gemini:/tmp/.gemini\""
        echo -e "  ${GREEN}[OK]${NC} Mounting Gemini credentials" >&2
        found_any=true
    fi

    if [ "$found_any" = false ]; then
        echo -e "  ${YELLOW}[WARN]${NC} No CLI credentials found." >&2
        echo -e "         Run 'claude', 'codex', or 'gemini' on host to login first." >&2
    fi

    echo ""  >&2
    echo "$mounts"
}

# -----------------------------------------------------------------------------
# Get workspace directory from config
# Reads workspace.yaml (or falls back to workspace.yaml.example)
# -----------------------------------------------------------------------------
get_workspace_dir() {
    local config_file="$PROJECT_ROOT/config/workspace.yaml"
    local template_file="$PROJECT_ROOT/config/workspace.yaml.example"
    local parent_dir=""

    # Try user config first, then template
    if [ -f "$config_file" ]; then
        parent_dir=$(grep -E '^\s*parent_dir:' "$config_file" | sed 's/.*parent_dir:\s*["'\'']\?\([^"'\'']*\)["'\'']\?.*/\1/' | tr -d ' ')
    elif [ -f "$template_file" ]; then
        parent_dir=$(grep -E '^\s*parent_dir:' "$template_file" | sed 's/.*parent_dir:\s*["'\'']\?\([^"'\'']*\)["'\'']\?.*/\1/' | tr -d ' ')
    fi

    # Default to ./workspaces if not found or empty
    if [ -z "$parent_dir" ]; then
        parent_dir="$PROJECT_ROOT/workspaces"
    # Handle relative paths (make them relative to project root)
    elif [[ "$parent_dir" != /* ]]; then
        parent_dir="$PROJECT_ROOT/$parent_dir"
    fi

    echo "$parent_dir"
}

# -----------------------------------------------------------------------------
# Ensure directories exist
# -----------------------------------------------------------------------------
ensure_directories() {
    local workspace_dir=$(get_workspace_dir)
    mkdir -p "$workspace_dir"
    mkdir -p "$PROJECT_ROOT/logs"
    # Pre-create ideas subdirectories on the host so they exist when
    # the volume is mounted into Docker (the mount overlays the image's
    # pre-created dirs, so the container can't rely on them).
    mkdir -p "$PROJECT_ROOT/ideas/submitted"
    mkdir -p "$PROJECT_ROOT/ideas/in_progress"
    mkdir -p "$PROJECT_ROOT/ideas/completed"
}

# -----------------------------------------------------------------------------
# Check for .env file
# -----------------------------------------------------------------------------
check_env_file() {
    if [ ! -f "$PROJECT_ROOT/.env" ]; then
        echo -e "${YELLOW}Warning: .env file not found${NC}"
        if [ -f "$PROJECT_ROOT/.env.example" ]; then
            echo "Create one from the template:"
            echo "  cp .env.example .env"
            echo "  # Edit .env with your API keys"
        fi
        echo ""
    fi
}

# -----------------------------------------------------------------------------
# Build the container image
# -----------------------------------------------------------------------------
cmd_build() {
    local version=$(cat "$PROJECT_ROOT/config/VERSION" 2>/dev/null | tr -d '[:space:]')
    echo -e "${BLUE}Building neurico container image${version:+ (v${version})}...${NC}"
    cd "$PROJECT_ROOT"
    docker build -t "$IMAGE_NAME" -f docker/Dockerfile .

    # Cache the image version for fast pre-run checks
    if [ -n "$version" ]; then
        echo "$version" > "$PROJECT_ROOT/.docker-image-version"
    fi

    echo -e "${GREEN}Build complete!${version:+ (v${version})}${NC}"
}

# -----------------------------------------------------------------------------
# Quick version check (no Docker overhead) for pre-run warnings
# -----------------------------------------------------------------------------
warn_if_outdated() {
    local host_version=$(cat "$PROJECT_ROOT/config/VERSION" 2>/dev/null | tr -d '[:space:]')
    local cached_version=$(cat "$PROJECT_ROOT/.docker-image-version" 2>/dev/null | tr -d '[:space:]')

    if [ -n "$host_version" ] && [ -n "$cached_version" ] && [ "$host_version" != "$cached_version" ]; then
        echo -e "${YELLOW}Warning: Docker image may be outdated (image: v${cached_version}, code: v${host_version})${NC}"
        echo -e "${YELLOW}Run './neurico build' to update.${NC}"
        echo ""
    fi
}

# -----------------------------------------------------------------------------
# Run interactive shell
# -----------------------------------------------------------------------------
cmd_shell() {
    ensure_directories
    check_env_file

    local gpu_flags=$(get_gpu_flags)
    local user_flags=$(get_user_flags)
    local credential_mounts=$(get_cli_credential_mounts)
    local workspace_dir=$(get_workspace_dir)

    echo -e "${BLUE}Starting interactive shell...${NC}"
    echo -e "${BLUE}Workspace:${NC} $workspace_dir -> /workspaces"

    eval "docker run -it --rm \
        $gpu_flags \
        $user_flags \
        --env-file \"$PROJECT_ROOT/.env\" \
        -e NEURICO_WORKSPACE=/workspaces \
        -v \"$workspace_dir:/workspaces\" \
        -v \"$PROJECT_ROOT/ideas:/app/ideas\" \
        -v \"$PROJECT_ROOT/logs:/app/logs\" \
        -v \"$PROJECT_ROOT/config:/app/config:ro\" \
        -v \"$PROJECT_ROOT/templates:/app/templates:ro\" \
        $credential_mounts \
        -w /workspaces \
        \"$IMAGE_NAME\" \
        bash"
}

# -----------------------------------------------------------------------------
# Fetch from IdeaHub
# -----------------------------------------------------------------------------
cmd_fetch() {
    if [ -z "$1" ]; then
        echo -e "${RED}Usage: $0 fetch <ideahub_url> [--submit]${NC}"
        exit 1
    fi

    ensure_directories
    check_env_file
    warn_if_outdated

    local gpu_flags=$(get_gpu_flags)
    local user_flags=$(get_user_flags)
    local credential_mounts=$(get_cli_credential_mounts)
    local workspace_dir=$(get_workspace_dir)

    local tty_flag=$(get_tty_flag)

    echo -e "${BLUE}Fetching from IdeaHub...${NC}"
    echo -e "${BLUE}Workspace:${NC} $workspace_dir -> /workspaces"

    eval "docker run $tty_flag --rm \
        $gpu_flags \
        $user_flags \
        --env-file \"$PROJECT_ROOT/.env\" \
        -e NEURICO_WORKSPACE=/workspaces \
        -v \"$workspace_dir:/workspaces\" \
        -v \"$PROJECT_ROOT/ideas:/app/ideas\" \
        -v \"$PROJECT_ROOT/logs:/app/logs\" \
        -v \"$PROJECT_ROOT/config:/app/config:ro\" \
        -v \"$PROJECT_ROOT/templates:/app/templates:ro\" \
        $credential_mounts \
        -w /app \
        \"$IMAGE_NAME\" \
        python /app/src/cli/fetch_from_ideahub.py $@"
}

# -----------------------------------------------------------------------------
# Submit a research idea
# -----------------------------------------------------------------------------
cmd_submit() {
    if [ -z "$1" ]; then
        echo -e "${RED}Usage: $0 submit <idea.yaml> [options]${NC}"
        exit 1
    fi

    ensure_directories
    check_env_file
    warn_if_outdated

    local gpu_flags=$(get_gpu_flags)
    local user_flags=$(get_user_flags)
    local credential_mounts=$(get_cli_credential_mounts)
    local idea_file="$1"
    shift

    # Handle relative vs absolute paths for idea file
    if [[ "$idea_file" = /* ]]; then
        # Absolute path - mount the parent directory
        local idea_dir=$(dirname "$idea_file")
        local idea_name=$(basename "$idea_file")
        local mount_flag="-v \"$idea_dir:/input:ro\""
        local idea_path="/input/$idea_name"
    else
        # Relative path - assume it's in ideas/ directory
        local idea_path="/app/$idea_file"
        local mount_flag=""
    fi

    local workspace_dir=$(get_workspace_dir)

    local tty_flag=$(get_tty_flag)

    echo -e "${BLUE}Submitting research idea...${NC}"
    echo -e "${BLUE}Workspace:${NC} $workspace_dir -> /workspaces"

    eval "docker run $tty_flag --rm \
        $gpu_flags \
        $user_flags \
        --env-file \"$PROJECT_ROOT/.env\" \
        -e NEURICO_WORKSPACE=/workspaces \
        -v \"$workspace_dir:/workspaces\" \
        -v \"$PROJECT_ROOT/ideas:/app/ideas\" \
        -v \"$PROJECT_ROOT/logs:/app/logs\" \
        -v \"$PROJECT_ROOT/config:/app/config:ro\" \
        -v \"$PROJECT_ROOT/templates:/app/templates:ro\" \
        $credential_mounts \
        $mount_flag \
        -w /app \
        \"$IMAGE_NAME\" \
        python /app/src/cli/submit.py \"$idea_path\" $@"
}

# -----------------------------------------------------------------------------
# Run research exploration
# -----------------------------------------------------------------------------
cmd_run() {
    if [ -z "$1" ]; then
        echo -e "${RED}Usage: $0 run <idea_id> [--provider claude|codex|gemini] [options]${NC}"
        exit 1
    fi

    ensure_directories
    check_env_file
    warn_if_outdated

    local gpu_flags=$(get_gpu_flags)
    local user_flags=$(get_user_flags)
    local credential_mounts=$(get_cli_credential_mounts)
    local workspace_dir=$(get_workspace_dir)

    local tty_flag=$(get_tty_flag)

    echo -e "${BLUE}Running research exploration...${NC}"
    echo -e "${BLUE}Workspace:${NC} $workspace_dir -> /workspaces"

    eval "docker run $tty_flag --rm \
        $gpu_flags \
        $user_flags \
        --env-file \"$PROJECT_ROOT/.env\" \
        -e NEURICO_WORKSPACE=/workspaces \
        -v \"$workspace_dir:/workspaces\" \
        -v \"$PROJECT_ROOT/ideas:/app/ideas\" \
        -v \"$PROJECT_ROOT/logs:/app/logs\" \
        -v \"$PROJECT_ROOT/config:/app/config:ro\" \
        -v \"$PROJECT_ROOT/templates:/app/templates:ro\" \
        $credential_mounts \
        -w /app \
        \"$IMAGE_NAME\" \
        python /app/src/core/runner.py $@"
}

# -----------------------------------------------------------------------------
# Docker Compose operations
# -----------------------------------------------------------------------------
cmd_up() {
    check_env_file
    cd "$PROJECT_ROOT"
    docker compose up -d
    echo -e "${GREEN}Container started in background${NC}"
}

cmd_down() {
    cd "$PROJECT_ROOT"
    docker compose down
    echo -e "${GREEN}Container stopped${NC}"
}

cmd_logs() {
    cd "$PROJECT_ROOT"
    docker compose logs -f
}

# -----------------------------------------------------------------------------
# Login to CLI tools (interactive shell for authentication)
# -----------------------------------------------------------------------------
cmd_login() {
    local provider="${1:-claude}"

    ensure_directories

    echo -e "${BLUE}Starting login shell for $provider...${NC}"
    echo ""
    echo "Run one of these commands inside the container:"
    echo "  claude   # Login to Claude Code"
    echo "  codex    # Login to Codex"
    echo "  gemini   # Login to Gemini CLI"
    echo ""
    echo "After logging in, exit the shell. Your credentials will be saved."
    echo ""

    # For login, we need write access to credential directories
    # Create them on host if they don't exist
    mkdir -p "$HOME/.claude" "$HOME/.codex" "$HOME/.gemini"

    local gpu_flags=$(get_gpu_flags)
    local user_flags=$(get_user_flags)

    # Use --user to match host UID so writes to mounted credential dirs succeed.
    # The entrypoint detects the non-writable /home/researcher and sets HOME=/tmp,
    # which makes CLI tools write to /tmp/.claude etc. (the mounted volumes).
    eval "docker run -it --rm \
        $gpu_flags \
        $user_flags \
        --env-file \"$PROJECT_ROOT/.env\" \
        -v \"$HOME/.claude:/tmp/.claude\" \
        -v \"$HOME/.codex:/tmp/.codex\" \
        -v \"$HOME/.gemini:/tmp/.gemini\" \
        -w /tmp \
        \"$IMAGE_NAME\" \
        bash"
}

# -----------------------------------------------------------------------------
# Setup wizard helpers
# -----------------------------------------------------------------------------

# Check prerequisites: verify required tools are installed
check_prerequisites() {
    echo -e "  ${BOLD}Step 1/5: Checking prerequisites${NC}"

    local all_ok=true

    if command -v git &> /dev/null; then
        echo -e "    ${GREEN}[OK]${NC} git found"
    else
        echo -e "    ${RED}[MISSING]${NC} git not found — install git first"
        all_ok=false
    fi

    if command -v docker &> /dev/null; then
        echo -e "    ${GREEN}[OK]${NC} docker found"
    else
        echo -e "    ${RED}[MISSING]${NC} docker not found — install Docker first"
        all_ok=false
    fi

    if command -v curl &> /dev/null; then
        echo -e "    ${GREEN}[OK]${NC} curl found"
    else
        echo -e "    ${YELLOW}[WARN]${NC} curl not found (optional, used for IdeaHub)"
    fi

    if docker info 2>/dev/null | grep -qi nvidia; then
        echo -e "    ${GREEN}[OK]${NC} nvidia-container-toolkit (GPU support)"
    else
        echo -e "    ${YELLOW}[WARN]${NC} nvidia-container-toolkit not found (GPU support optional)"
    fi

    echo ""

    if [ "$all_ok" = false ]; then
        echo -e "  ${RED}Missing required tools. Please install them and re-run setup.${NC}"
        exit 1
    fi
}

# Check Docker image: pull if needed, update if outdated
check_image() {
    echo -e "  ${BOLD}Step 2/5: Docker image${NC}"

    local host_version=""
    if [ -f "$PROJECT_ROOT/config/VERSION" ]; then
        host_version=$(cat "$PROJECT_ROOT/config/VERSION" | tr -d '[:space:]')
    fi

    if docker image inspect "$IMAGE_NAME" &> /dev/null; then
        # Image exists — check if version matches host code
        local image_version=""
        image_version=$(docker run --rm --entrypoint python "$IMAGE_NAME" \
            -c "exec(open('/app/src/__version__.py').read()); print(__version__)" 2>/dev/null || echo "")

        if [ -n "$host_version" ] && [ -n "$image_version" ] && [ "$host_version" = "$image_version" ]; then
            echo -e "    ${GREEN}[OK]${NC} Image up to date (v${image_version})"
            echo "$image_version" > "$PROJECT_ROOT/.docker-image-version"
            echo ""
            return
        elif [ -n "$host_version" ] && [ -n "$image_version" ]; then
            echo -e "    ${YELLOW}[OUTDATED]${NC} Image v${image_version}, host code v${host_version}"
            echo -e "    Pulling updated image..."
        else
            # Can't determine version — image predates version system, pull latest
            echo -e "    ${YELLOW}[WARN]${NC} Cannot determine image version, pulling latest..."
        fi
    else
        echo -e "    Pulling ghcr.io/chicagohai/neurico:latest..."
    fi

    # Try pulling latest image
    if docker pull ghcr.io/chicagohai/neurico:latest; then
        docker tag ghcr.io/chicagohai/neurico:latest "$IMAGE_NAME"
        # Cache the new image version
        local new_version=""
        new_version=$(docker run --rm --entrypoint python "$IMAGE_NAME" \
            -c "exec(open('/app/src/__version__.py').read()); print(__version__)" 2>/dev/null || echo "")
        if [ -n "$new_version" ]; then
            echo "$new_version" > "$PROJECT_ROOT/.docker-image-version"
        fi
        echo -e "    ${GREEN}[OK]${NC} Image ready${new_version:+ (v${new_version})}"
    else
        echo -e "    ${YELLOW}[WARN]${NC} Pull failed — build locally with: ./neurico build"
    fi
    echo ""
}

# Read the current value of an env var from .env (uncommented lines only)
# Usage: get_env_value "VAR_NAME"
get_env_value() {
    local var_name="$1"
    if [ -f "$PROJECT_ROOT/.env" ]; then
        grep -E "^${var_name}=" "$PROJECT_ROOT/.env" 2>/dev/null | head -1 | sed "s/^${var_name}=//"
    fi
}

# Mask a secret for display (first 4 + last 4 chars; values ≤8 chars show ****)
# Usage: mask_value "value"
mask_value() {
    local val="$1"
    local len=${#val}
    if [ "$len" -le 8 ]; then
        echo "****"
    else
        echo "${val:0:4}...${val:len-4:4}"
    fi
}

# Read input with masked display (shows * for each character typed)
# Usage: read_masked VARNAME
# Sets the named variable to the entered value.
#
# Uses stty for echo control instead of read -s, because read -s manipulates
# terminal attributes on stdin — which breaks when stdin is a pipe (curl|bash).
# stty < /dev/tty explicitly targets the real terminal device.
read_masked() {
    local __resultvar="$1"
    local _input="" _char=""

    # Save terminal settings and disable echo via stty on /dev/tty
    local old_stty
    old_stty=$(stty -g < /dev/tty 2>/dev/null)
    stty -echo < /dev/tty 2>/dev/null
    # Restore terminal on unexpected exit (Ctrl-C, etc.)
    trap 'stty '"$old_stty"' < /dev/tty 2>/dev/null; trap - INT TERM' INT TERM

    while true; do
        # Read one character at a time (no -s flag — stty handles echo suppression)
        IFS= read -r -n 1 _char < /dev/tty

        # Enter (empty char) → done
        if [[ -z "$_char" ]]; then
            break
        fi

        # Backspace (0x7f) or Ctrl-H (0x08) → remove last char
        if [[ "$_char" == $'\x7f' ]] || [[ "$_char" == $'\x08' ]]; then
            if [ ${#_input} -gt 0 ]; then
                _input="${_input%?}"
                echo -ne '\b \b' >&2
            fi
        else
            _input+="$_char"
            echo -ne '*' >&2
        fi
    done

    echo "" >&2  # Newline after input

    # Restore terminal settings
    stty "$old_stty" < /dev/tty 2>/dev/null
    trap - INT TERM

    printf -v "$__resultvar" '%s' "$_input"
}

# Return formatted status string for a config variable
# Usage: format_status "VAR_NAME" [is_secret]
# is_secret: "true" to mask the value, anything else shows full value
format_status() {
    local var_name="$1"
    local is_secret="${2:-true}"
    local val
    val=$(get_env_value "$var_name")
    if [ -n "$val" ]; then
        if [ "$is_secret" = "true" ]; then
            echo -e "${GREEN}[SET: $(mask_value "$val")]${NC}"
        else
            echo -e "${GREEN}[SET: $val]${NC}"
        fi
    else
        echo -e "${DIM}[NOT SET]${NC}"
    fi
}

# Write a value to .env, handling existing patterns (replace, uncomment, or append)
# Usage: config_set_env "VAR_NAME" "value"
config_set_env() {
    local var_name="$1"
    local value="$2"
    if grep -q "^${var_name}=" "$PROJECT_ROOT/.env" 2>/dev/null; then
        sed -i "s|^${var_name}=.*|${var_name}=${value}|" "$PROJECT_ROOT/.env"
    elif grep -q "^# *${var_name}=" "$PROJECT_ROOT/.env" 2>/dev/null; then
        sed -i "s|^# *${var_name}=.*|${var_name}=${value}|" "$PROJECT_ROOT/.env"
    else
        echo "${var_name}=${value}" >> "$PROJECT_ROOT/.env"
    fi
}

# Read a secret value from user input (masked with *)
# Usage: prompt_secret "Label" "ENV_VAR" "required|optional" "validation_prefix"
prompt_secret() {
    local label="$1"
    local env_var="$2"
    local required="$3"
    local prefix="$4"

    if [ "$required" = "required" ]; then
        echo -e "    ${BOLD}$label${NC} (recommended)"
    else
        echo -e "    ${BOLD}$label${NC} (optional)"
    fi

    if [ -n "$5" ]; then
        echo -e "    ${DIM}$5${NC}"
    fi

    local value=""
    if [ "$required" = "optional" ]; then
        echo -ne "    > ${DIM}[Enter to skip]${NC} "
    else
        echo -ne "    > "
    fi
    read_masked value

    if [ -z "$value" ]; then
        echo -e "    ${DIM}[SKIP]${NC} $label skipped"
        return 1
    fi

    # Show masked confirmation so user can verify what they entered
    echo -e "    ${DIM}Entered: $(mask_value "$value") (${#value} chars)${NC}"

    # Validate prefix if provided (GitHub tokens can be ghp_ or github_pat_)
    if [ -n "$prefix" ] && [[ ! "$value" == $prefix* ]]; then
        if [ "$env_var" = "GITHUB_TOKEN" ] && [[ "$value" == github_pat_* ]]; then
            : # github_pat_ is also valid
        else
            echo -e "    ${YELLOW}[WARN]${NC} Expected value starting with '$prefix' — saving anyway"
        fi
    fi

    # Write to .env
    if grep -q "^${env_var}=" "$PROJECT_ROOT/.env" 2>/dev/null; then
        sed -i "s|^${env_var}=.*|${env_var}=${value}|" "$PROJECT_ROOT/.env"
    elif grep -q "^# *${env_var}=" "$PROJECT_ROOT/.env" 2>/dev/null; then
        sed -i "s|^# *${env_var}=.*|${env_var}=${value}|" "$PROJECT_ROOT/.env"
    else
        echo "${env_var}=${value}" >> "$PROJECT_ROOT/.env"
    fi

    echo -e "    ${GREEN}[OK]${NC} $env_var saved"
    return 0
}

# Read a visible (non-secret) value from user input
# Usage: prompt_text "Label" "hint" "default_value"
# Sets REPLY to the entered value (or default if empty)
prompt_text() {
    local label="$1"
    local hint="$2"
    local default_val="$3"

    echo -e "    ${BOLD}$label${NC} (optional)"
    if [ -n "$hint" ]; then
        echo -e "    ${DIM}$hint${NC}"
    fi

    if [ -n "$default_val" ]; then
        echo -ne "    > ${DIM}[Enter for '$default_val']${NC} "
    else
        echo -ne "    > ${DIM}[Enter to skip]${NC} "
    fi
    local value=""
    read value < /dev/tty

    if [ -z "$value" ]; then
        REPLY="$default_val"
    else
        REPLY="$value"
    fi
}

# Display a numbered menu and return the selection number
# Usage: prompt_choice "Header" "option1" "option2" ...
# Returns: selected number (1-based) in $REPLY
prompt_choice() {
    local header="$1"
    shift
    local options=("$@")

    echo -e "    ${BOLD}$header${NC}"
    local i=1
    for opt in "${options[@]}"; do
        echo "      [$i] $opt"
        ((i++))
    done

    local selection=""
    while true; do
        echo -ne "    > "
        read selection < /dev/tty
        if [[ "$selection" =~ ^[0-9]+$ ]] && [ "$selection" -ge 1 ] && [ "$selection" -le "${#options[@]}" ]; then
            REPLY="$selection"
            return
        fi
        echo -e "    ${YELLOW}Please enter a number between 1 and ${#options[@]}${NC}"
    done
}

# Login a single provider inside Docker with guided instructions
# Usage: setup_login_provider "Display Name" "cli_command" "/host/cred/dir" "/container/cred/dir"
setup_login_provider() {
    local display_name="$1"
    local cli_cmd="$2"
    local host_dir="$3"
    local container_dir="$4"

    # Skip if credentials already exist
    if [ -d "$host_dir" ] && [ "$(ls -A "$host_dir" 2>/dev/null)" ]; then
        echo ""
        echo -e "    ${GREEN}[OK]${NC} $display_name credentials already configured"
        echo -ne "    Re-login? [y/N] "
        local relogin=""
        read relogin < /dev/tty
        if [[ ! "$relogin" =~ ^[Yy] ]]; then
            echo ""
            return
        fi
    fi

    mkdir -p "$host_dir"
    echo ""
    echo -e "    ${BOLD}${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo -e "    ${BOLD}${YELLOW}  Setting up: $display_name${NC}"
    echo -e "    ${BOLD}${YELLOW}${NC}"
    echo -e "    ${BOLD}${YELLOW}  1. Press Enter to launch $display_name in a container${NC}"
    echo -e "    ${BOLD}${YELLOW}  2. $display_name will prompt you to sign in via your browser${NC}"
    echo -e "    ${BOLD}${YELLOW}     (an OAuth link will appear — click it or paste it)${NC}"
    echo -e "    ${BOLD}${YELLOW}  3. After signing in, you'll see the $display_name chat interface${NC}"
    echo -e "    ${BOLD}${YELLOW}${NC}"
    echo -e "    ${BOLD}${RED}  >>> Once you see the chat prompt, press Ctrl+C TWICE to exit <<<${NC}"
    echo -e "    ${BOLD}${YELLOW}${NC}"
    echo -e "    ${BOLD}${YELLOW}  Your credentials will be saved automatically.${NC}"
    echo -e "    ${BOLD}${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -ne "    Press Enter to launch $display_name..."
    read < /dev/tty

    local gpu_flags=$(get_gpu_flags 2>/dev/null)
    local user_flags=$(get_user_flags)
    eval "docker run -it --rm \
        $gpu_flags \
        $user_flags \
        --env-file \"$PROJECT_ROOT/.env\" \
        -v \"$host_dir:$container_dir\" \
        -w /tmp \
        \"$IMAGE_NAME\" \
        $cli_cmd" || true

    echo ""
    if [ -d "$host_dir" ] && [ "$(ls -A "$host_dir" 2>/dev/null)" ]; then
        echo -e "    ${GREEN}[OK]${NC} $display_name credentials saved"
    else
        echo -e "    ${YELLOW}[WARN]${NC} No $display_name credentials detected — you can login later with: ./neurico login"
    fi
    echo ""
}

# -----------------------------------------------------------------------------
# Interactive setup wizard
# -----------------------------------------------------------------------------
cmd_setup() {
    show_banner

    echo -e "${BOLD}  Welcome to NeuriCo!${NC}"
    echo -e "  ${DIM}This wizard will get you set up in a few minutes.${NC}"
    echo ""

    # ── Step 1: Prerequisites ──
    check_prerequisites

    # ── Step 2: Docker image ──
    check_image

    # ── Step 3: Configuration (.env) ──
    echo -e "  ${BOLD}Step 3/5: Configuration (.env)${NC}"

    if [ -f "$PROJECT_ROOT/.env" ]; then
        echo -e "    ${GREEN}[OK]${NC} .env file already exists"
        echo -ne "    Reconfigure? [y/N] "
        read reconfigure < /dev/tty
        if [[ ! "$reconfigure" =~ ^[Yy] ]]; then
            echo -e "    ${DIM}Keeping existing configuration${NC}"
            echo ""
        else
            echo ""
            setup_env_interactive
        fi
    else
        # Create from template
        if [ -f "$PROJECT_ROOT/.env.example" ]; then
            cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
        else
            touch "$PROJECT_ROOT/.env"
        fi
        setup_env_interactive
    fi

    # ── Step 4: AI CLI Login ──
    echo -e "  ${BOLD}Step 4/5: AI CLI Login${NC}"
    echo -e "    ${DIM}Each provider uses OAuth — you'll login inside a Docker container.${NC}"
    echo -e "    ${DIM}You can set up multiple providers now, or add more later with: ./neurico login${NC}"
    echo ""
    # Detect existing credentials
    local claude_status="" codex_status="" gemini_status=""
    if [ -d "$HOME/.claude" ] && [ "$(ls -A "$HOME/.claude" 2>/dev/null)" ]; then
        claude_status=" ${GREEN}[already configured]${NC}"
    fi
    if [ -d "$HOME/.codex" ] && [ "$(ls -A "$HOME/.codex" 2>/dev/null)" ]; then
        codex_status=" ${GREEN}[already configured]${NC}"
    fi
    if [ -d "$HOME/.gemini" ] && [ "$(ls -A "$HOME/.gemini" 2>/dev/null)" ]; then
        gemini_status=" ${GREEN}[already configured]${NC}"
    fi

    echo -e "    ${BOLD}Which providers do you want to log in to?${NC}"
    echo -e "      [1] Claude (recommended)${claude_status}"
    echo -e "      [2] Codex${codex_status}"
    echo -e "      [3] Gemini${gemini_status}"
    echo "      [4] Skip for now"
    echo -e "    ${DIM}Enter one or more numbers, e.g. 1 2 or 1,2,3${NC}"
    echo -ne "    > "
    local login_input=""
    read login_input < /dev/tty

    # Normalize: replace commas with spaces
    login_input="${login_input//,/ }"

    # Track which providers were logged in (for step 5 default)
    local provider_choice=""

    for choice in $login_input; do
        case "$choice" in
            1)
                [ -z "$provider_choice" ] && provider_choice="1"
                setup_login_provider "Claude" "claude" "$HOME/.claude" "/tmp/.claude"
                ;;
            2)
                [ -z "$provider_choice" ] && provider_choice="2"
                setup_login_provider "Codex" "codex" "$HOME/.codex" "/tmp/.codex"
                ;;
            3)
                [ -z "$provider_choice" ] && provider_choice="3"
                setup_login_provider "Gemini" "gemini" "$HOME/.gemini" "/tmp/.gemini"
                ;;
            4)
                echo -e "    ${DIM}[SKIP]${NC} You can login later with: ./neurico login"
                ;;
        esac
    done

    # Default to claude if nothing was selected
    [ -z "$provider_choice" ] && provider_choice="1"
    echo ""

    # ── Step 5: Run your first idea ──
    echo -e "  ${BOLD}Step 5/5: Run your first idea (optional)${NC}"

    prompt_choice "How would you like to provide your research idea?" \
        "IdeaHub URL (paste a link from hypogenic.ai/ideahub)" \
        "YAML file (local file path)" \
        "Try an example idea (built-in)" \
        "Skip — I'll run later"

    local idea_choice="$REPLY"

    # Determine provider flag from step 4
    local provider_flag="claude"
    case "$provider_choice" in
        2) provider_flag="codex" ;;
        3) provider_flag="gemini" ;;
    esac

    # Build the run command based on user's choice
    local run_cmd=""

    case "$idea_choice" in
        1)
            echo -ne "    Paste your IdeaHub URL: "
            read ideahub_url < /dev/tty
            if [ -n "$ideahub_url" ]; then
                run_cmd="./neurico fetch $ideahub_url --submit --run --provider $provider_flag --full-permissions"
            else
                echo -e "    ${YELLOW}[SKIP]${NC} No URL provided"
            fi
            ;;
        2)
            echo -ne "    Path to YAML file: "
            read yaml_path < /dev/tty
            if [ -n "$yaml_path" ]; then
                run_cmd="./neurico submit $yaml_path --run --provider $provider_flag --full-permissions"
            else
                echo -e "    ${YELLOW}[SKIP]${NC} No path provided"
            fi
            ;;
        3)
            run_cmd="./neurico submit ideas/examples/ml_regularization_test.yaml --run --provider $provider_flag --full-permissions"
            ;;
    esac

    echo ""
    echo -e "  ${GREEN}Setup complete!${NC} You're ready to go."
    echo ""
    echo -e "  ${BOLD}Config files:${NC}"
    echo -e "  ${DIM}  API keys & credentials .... .env${NC}"
    echo -e "  ${DIM}  Workspace config .......... config/workspace.yaml${NC}"
    echo -e "  ${DIM}  CLI credentials ........... ~/.claude/  ~/.codex/  ~/.gemini/${NC}"
    echo ""
    echo -e "  ${DIM}To change configuration later, run: ./neurico config${NC}"
    echo ""

    if [ -n "$run_cmd" ]; then
        echo -e "  Run this to get started:"
        echo ""
        echo -e "    ${BOLD}cd $PROJECT_ROOT && $run_cmd${NC}"
        echo ""

        # If we have a real TTY, offer to run it now
        if [ -t 0 ]; then
            echo -ne "  Run it now? [Y/n] "
            read run_now < /dev/tty
            if [[ ! "$run_now" =~ ^[Nn] ]]; then
                cd "$PROJECT_ROOT"
                exec $run_cmd
            fi
        fi
    else
        echo "  Next steps:"
        echo -e "    ${BOLD}cd $PROJECT_ROOT${NC}"
        echo "    ./neurico fetch <ideahub_url> --submit --run --provider claude --full-permissions"
        echo "    ./neurico help"
        echo ""
    fi
}

# Helper: interactive .env configuration
setup_env_interactive() {
    prompt_secret "GitHub Token" "GITHUB_TOKEN" "required" "ghp_" \
        "Get one at: https://github.com/settings/tokens (repo scope)" || true
    echo ""

    prompt_secret "OpenAI API Key" "OPENAI_API_KEY" "optional" "sk-" \
        "Enables IdeaHub + LLM repo naming" || true
    echo ""

    prompt_secret "Semantic Scholar API Key" "S2_API_KEY" "optional" "" \
        "Enables paper-finder literature search (https://www.semanticscholar.org/product/api)" || true
    echo ""

    # GitHub Organization
    prompt_text "GitHub Organization" \
        "Repos will be created under this org. Leave empty to use your personal account."
    if [ -n "$REPLY" ]; then
        if grep -q "^GITHUB_ORG=" "$PROJECT_ROOT/.env" 2>/dev/null; then
            sed -i "s|^GITHUB_ORG=.*|GITHUB_ORG=$REPLY|" "$PROJECT_ROOT/.env"
        elif grep -q "^# *GITHUB_ORG=" "$PROJECT_ROOT/.env" 2>/dev/null; then
            sed -i "s|^# *GITHUB_ORG=.*|GITHUB_ORG=$REPLY|" "$PROJECT_ROOT/.env"
        else
            echo "GITHUB_ORG=$REPLY" >> "$PROJECT_ROOT/.env"
        fi
        echo -e "    ${GREEN}[OK]${NC} GITHUB_ORG set to $REPLY"
    else
        echo -e "    ${DIM}[SKIP]${NC} Using personal GitHub account"
    fi
    echo ""

    # Workspace directory
    prompt_text "Workspace Directory" \
        "Where research workspaces are created. Relative to project root or absolute path." \
        "workspaces"
    if [ -n "$REPLY" ] && [ "$REPLY" != "workspaces" ]; then
        # Create workspace.yaml from template only if it doesn't exist yet
        local ws_config="$PROJECT_ROOT/config/workspace.yaml"
        if [ ! -f "$ws_config" ] && [ -f "$PROJECT_ROOT/config/workspace.yaml.example" ]; then
            cp "$PROJECT_ROOT/config/workspace.yaml.example" "$ws_config"
        fi
        sed -i "s|parent_dir:.*|parent_dir: \"$REPLY\"|" "$ws_config"
        echo -e "    ${GREEN}[OK]${NC} Workspace directory set to $REPLY"
    else
        echo -e "    ${DIM}[OK]${NC} Using default: ./workspaces"
    fi
    echo ""

    echo -e "    ${GREEN}[OK]${NC} Configuration complete"
    echo ""
    echo -e "    ${BOLD}Where your settings are stored:${NC}"
    echo -e "    ${DIM}  API keys & credentials .... .env${NC}"
    echo -e "    ${DIM}  Workspace config .......... config/workspace.yaml${NC}"
    echo -e "    ${DIM}  CLI credentials ........... ~/.claude/  ~/.codex/  ~/.gemini/${NC}"
    echo ""
    echo -e "    ${DIM}Tip: To add more API keys or change settings later, run:${NC}"
    echo -e "    ${DIM}  ./neurico config${NC}"
    echo ""
}

# -----------------------------------------------------------------------------
# Interactive configuration menu
# -----------------------------------------------------------------------------
cmd_config() {
    # Create .env from template if missing
    if [ ! -f "$PROJECT_ROOT/.env" ]; then
        if [ -f "$PROJECT_ROOT/.env.example" ]; then
            cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
        else
            touch "$PROJECT_ROOT/.env"
        fi
        echo -e "  ${GREEN}[OK]${NC} Created .env from template"
        echo ""
    fi

    while true; do
        echo ""
        echo -e "  ${BOLD}Configuration${NC}"
        echo -e "  ${DIM}Select an item to configure, or 'q' to exit.${NC}"
        echo ""

        # GitHub
        echo -e "  ${BOLD}GitHub${NC}  ${DIM}— token required; org optional (personal account used if empty)${NC}"
        echo -e "    ${BOLD}[1]${NC}  GitHub Token ........... $(format_status GITHUB_TOKEN true)"
        echo -e "    ${BOLD}[2]${NC}  GitHub Organization .... $(format_status GITHUB_ORG false)"
        echo ""

        # Paper Finder
        echo -e "  ${BOLD}Paper Finder${NC}  ${DIM}— OpenAI + S2 required; Cohere optional (improves ranking)${NC}"
        echo -e "    ${BOLD}[3]${NC}  OpenAI API Key ......... $(format_status OPENAI_API_KEY true)"
        echo -e "    ${BOLD}[4]${NC}  Semantic Scholar Key ... $(format_status S2_API_KEY true)"
        echo -e "    ${BOLD}[5]${NC}  Cohere API Key ......... $(format_status COHERE_API_KEY true)"
        echo ""

        # Agent Keys
        echo -e "  ${BOLD}Agent API Keys${NC}  ${DIM}— optional, provided to the agent during experiments${NC}"
        echo -e "    ${BOLD}[6]${NC}  Anthropic API Key ...... $(format_status ANTHROPIC_API_KEY true)"
        echo -e "    ${BOLD}[7]${NC}  Google API Key ......... $(format_status GOOGLE_API_KEY true)"
        echo -e "    ${BOLD}[8]${NC}  OpenRouter API Key ..... $(format_status OPENROUTER_KEY true)"
        echo -e "    ${BOLD}[9]${NC}  Hugging Face Token ..... $(format_status HF_TOKEN true)"
        echo -e "    ${BOLD}[10]${NC} Weights & Biases Key ... $(format_status WANDB_API_KEY true)"

        # Workspace status
        local ws_val
        ws_val=$(get_workspace_dir)
        # Show relative to project root if possible
        ws_val="${ws_val#$PROJECT_ROOT/}"
        echo -e "    ${BOLD}[11]${NC} Workspace Directory .... ${GREEN}[SET: $ws_val]${NC}"
        echo ""

        echo -e "    ${BOLD}[q]${NC}  Save & exit"
        echo ""
        echo -ne "  > "
        local choice=""
        read choice < /dev/tty

        case "$choice" in
            1)
                echo ""
                prompt_secret "GitHub Token" "GITHUB_TOKEN" "required" "ghp_" \
                    "Get one at: https://github.com/settings/tokens (repo scope)" || true
                ;;
            2)
                echo ""
                prompt_text "GitHub Organization" \
                    "Repos will be created under this org. Leave empty to use your personal account."
                if [ -n "$REPLY" ]; then
                    config_set_env "GITHUB_ORG" "$REPLY"
                    echo -e "    ${GREEN}[OK]${NC} GITHUB_ORG set to $REPLY"
                else
                    echo -e "    ${DIM}[SKIP]${NC} No change"
                fi
                ;;
            3)
                echo ""
                prompt_secret "OpenAI API Key" "OPENAI_API_KEY" "optional" "sk-" \
                    "Required for paper-finder" || true
                ;;
            4)
                echo ""
                prompt_secret "Semantic Scholar API Key" "S2_API_KEY" "optional" "" \
                    "Required for paper-finder (https://www.semanticscholar.org/product/api)" || true
                ;;
            5)
                echo ""
                prompt_secret "Cohere API Key" "COHERE_API_KEY" "optional" "" \
                    "Optional — improves paper-finder ranking (https://cohere.com)" || true
                ;;
            6)
                echo ""
                prompt_secret "Anthropic API Key" "ANTHROPIC_API_KEY" "optional" "sk-ant-" \
                    "For Claude API access" || true
                ;;
            7)
                echo ""
                prompt_secret "Google API Key" "GOOGLE_API_KEY" "optional" "" \
                    "For Google AI/Gemini API access" || true
                ;;
            8)
                echo ""
                prompt_secret "OpenRouter API Key" "OPENROUTER_KEY" "optional" "sk-or-" \
                    "For OpenRouter multi-model access (https://openrouter.ai)" || true
                ;;
            9)
                echo ""
                prompt_secret "Hugging Face Token" "HF_TOKEN" "optional" "hf_" \
                    "For Hugging Face model/dataset access" || true
                ;;
            10)
                echo ""
                prompt_secret "Weights & Biases API Key" "WANDB_API_KEY" "optional" "" \
                    "For experiment tracking (https://wandb.ai)" || true
                ;;
            11)
                echo ""
                prompt_text "Workspace Directory" \
                    "Where research workspaces are created. Relative to project root or absolute path." \
                    "workspaces"
                if [ -n "$REPLY" ]; then
                    local ws_config="$PROJECT_ROOT/config/workspace.yaml"
                    if [ ! -f "$ws_config" ] && [ -f "$PROJECT_ROOT/config/workspace.yaml.example" ]; then
                        cp "$PROJECT_ROOT/config/workspace.yaml.example" "$ws_config"
                    fi
                    sed -i "s|parent_dir:.*|parent_dir: \"$REPLY\"|" "$ws_config"
                    echo -e "    ${GREEN}[OK]${NC} Workspace directory set to $REPLY"
                else
                    echo -e "    ${DIM}[SKIP]${NC} No change"
                fi
                ;;
            q|Q|"")
                echo ""
                echo -e "  ${GREEN}Configuration saved to .env${NC}"
                echo ""
                return
                ;;
            *)
                echo -e "  ${YELLOW}Invalid choice. Enter 1-11 or q to exit.${NC}"
                ;;
        esac

        echo ""
        echo -ne "  ${DIM}Press Enter to continue...${NC}"
        read < /dev/tty
    done
}

# -----------------------------------------------------------------------------
# Show help
# -----------------------------------------------------------------------------
cmd_help() {
    show_banner
    show_status

    echo "Usage: $0 <command> [arguments]"
    echo ""
    echo "Commands:"
    echo "  setup                     Interactive setup wizard (start here!)"
    echo "  config                    Configure API keys and settings"
    echo "  build                     Build the container image"
    echo "  login [provider]          Login to CLI tools (claude/codex/gemini)"
    echo "  shell                     Start an interactive shell"
    echo "  fetch <url> [--submit]    Fetch idea from IdeaHub"
    echo "  submit <idea.yaml>        Submit a research idea"
    echo "  run <id> [options]        Run research exploration"
    echo "  up                        Start container in background (compose)"
    echo "  down                      Stop background container (compose)"
    echo "  logs                      View container logs (compose)"
    echo "  help                      Show this help message"
    echo ""
    echo "First-time setup:"
    echo "  $0 setup                  # Interactive wizard (recommended)"
    echo ""
    echo "Daily usage:"
    echo "  $0 fetch https://ideahub.example.com/idea/123 --submit --run --provider claude --full-permissions"
    echo "  $0 run my-idea-id --provider claude --full-permissions"
    echo "  $0 shell"
    echo ""
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

# Parse command
ACTION="${1:-help}"
shift 2>/dev/null || true

# Check Docker is available (skip for commands that don't need it)
if [ "$ACTION" != "config" ] && [ "$ACTION" != "help" ] && [ "$ACTION" != "--help" ] && [ "$ACTION" != "-h" ]; then
    check_docker
fi

case "$ACTION" in
    setup)
        cmd_setup
        ;;
    config)
        cmd_config
        ;;
    build)
        cmd_build
        ;;
    login)
        cmd_login "$@"
        ;;
    shell)
        cmd_shell
        ;;
    fetch)
        cmd_fetch "$@"
        ;;
    submit)
        cmd_submit "$@"
        ;;
    run)
        cmd_run "$@"
        ;;
    up)
        cmd_up
        ;;
    down)
        cmd_down
        ;;
    logs)
        cmd_logs
        ;;
    help|--help|-h)
        cmd_help
        ;;
    *)
        echo -e "${RED}Unknown command: $ACTION${NC}"
        cmd_help
        exit 1
        ;;
esac
