#!/bin/bash
# =============================================================================
# NeuriCo host mode (no Docker)
#
# Sourced by docker/run.sh. When NEURICO_MODE=host (set by `./neurico --host`,
# `./neurico-host`, or the environment) run.sh hands every subcommand to
# host_dispatch, which runs the same Python entrypoints the container would
# run, with the project venv's interpreter, directly on this machine.
#
# Rules:
#   * NEURICO_MODE=host is the single source of truth (is_host_mode).
#   * Never require or call docker.
#   * Forward arguments exactly like the Docker route; call the same scripts.
#   * A job runs in its own process group; logs/host-jobs/<name>.pid holds the
#     group id, so `./neurico --host kill <name>` replaces `docker kill`.
#   * Only signal process groups we started ourselves (shared machines).
#   * Never print secret values; keys are reported by name only.
#
# Relies on run.sh for: PROJECT_ROOT, colours, get_workspace_dir,
# hitl_web_port_from_args, hitl_direct_web_port_from_args, cmd_config,
# cmd_bump_version, show_banner.
# =============================================================================

is_host_mode() {
    [ "${NEURICO_MODE:-docker}" = "host" ]
}

# Directory of job pid files (override for tests).
host_jobs_dir() {
    echo "${NEURICO_HOST_JOBS_DIR:-$PROJECT_ROOT/logs/host-jobs}"
}

# Workspace parent: environment first (config_loader.py precedence), then config/workspace.yaml.
host_workspace_dir() {
    if [ -n "${NEURICO_WORKSPACE:-}" ]; then
        echo "$NEURICO_WORKSPACE"
    else
        get_workspace_dir
    fi
}

# -----------------------------------------------------------------------------
# Environment (host counterpart of `docker run --env-file .env -e ...`)
# -----------------------------------------------------------------------------

# Export KEY=VALUE pairs from a dotenv file without overriding variables that
# are already exported (python-dotenv semantics: the environment wins, so a
# batch tool's NEURICO_GPUS / HF_HOME / NEURICO_CONTAINER_NAME survive).
host_source_dotenv() {
    local file="$1"
    [ -f "$file" ] || return 0
    local -A prior=()
    local name
    while IFS= read -r name; do
        prior["$name"]="${!name}"
    done < <(compgen -e)
    set -a
    # shellcheck disable=SC1090
    . "$file"
    set +a
    for name in "${!prior[@]}"; do
        export "$name=${prior[$name]}"
    done
}

# Load .env.local then .env (first wins) and export what the container's
# Dockerfile/entrypoint would have set. Idempotent.
host_load_env() {
    [ -n "${_NEURICO_HOST_ENV_LOADED:-}" ] && return 0
    export NEURICO_MODE=host
    export NEURICO_PROJECT_ROOT="$PROJECT_ROOT"
    export NEURICO_SRC="$PROJECT_ROOT/src"
    export NEURICO_ENV_FILE="$PROJECT_ROOT/.env"
    host_source_dotenv "$PROJECT_ROOT/.env.local"
    host_source_dotenv "$PROJECT_ROOT/.env"

    local workspace_dir
    workspace_dir=$(host_workspace_dir)
    export NEURICO_WORKSPACE="$workspace_dir"
    export NEURICO_WORKSPACE_DIR="$workspace_dir"      # interactive manager
    export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
    export PYTHONUNBUFFERED=1
    export GEMINI_CLI_TRUST_WORKSPACE="${GEMINI_CLI_TRUST_WORKSPACE:-true}"   # Dockerfile ENV
    if [ -n "${NEURICO_HF_CACHE:-}" ]; then
        mkdir -p "$NEURICO_HF_CACHE" 2>/dev/null || true
        export HF_HOME="$NEURICO_HF_CACHE"
    fi
    if [ -n "${NEURICO_GPUS:-}" ]; then
        export CUDA_VISIBLE_DEVICES="$NEURICO_GPUS"
    fi
    # The non-chmod half of ensure_directories (host files belong to the user).
    mkdir -p "$workspace_dir" "$PROJECT_ROOT/logs" "$(host_jobs_dir)" \
        "$PROJECT_ROOT/ideas/submitted" "$PROJECT_ROOT/ideas/in_progress" "$PROJECT_ROOT/ideas/completed"
    _NEURICO_HOST_ENV_LOADED=1
}

# -----------------------------------------------------------------------------
# Interpreter
# -----------------------------------------------------------------------------

# Serialised `uv sync --frozen` (several jobs may start at once).
host_uv_sync() {
    local lock="$PROJECT_ROOT/logs/host-uv-sync.lock"
    mkdir -p "$PROJECT_ROOT/logs"
    local -a sync=( uv sync --frozen )
    [ -n "${NEURICO_HOST_UV_PYTHON:-}" ] && sync+=( --python "$NEURICO_HOST_UV_PYTHON" )
    if command -v flock >/dev/null 2>&1; then
        ( cd "$PROJECT_ROOT" && flock "$lock" "${sync[@]}" )
    else
        ( cd "$PROJECT_ROOT" && "${sync[@]}" )
    fi
}

# Resolve HOST_PYTHON: the project venv's interpreter, called directly so that
# parallel jobs never race on uv's auto-sync. Built once with uv if missing.
host_python() {
    local venv_python="$PROJECT_ROOT/.venv/bin/python"
    if [ ! -x "$venv_python" ]; then
        if ! command -v uv >/dev/null 2>&1; then
            echo -e "${RED}Error: $PROJECT_ROOT/.venv is missing and uv is not installed${NC}" >&2
            echo "Install uv (https://docs.astral.sh/uv/), then run: ./neurico --host build" >&2
            return 1
        fi
        echo -e "${BLUE}Creating the project venv (uv sync --frozen)...${NC}" >&2
        host_uv_sync || return 1
    fi
    HOST_PYTHON="$venv_python"
}

# -----------------------------------------------------------------------------
# Environment check (port of entrypoint.sh: version, keys by name, GPU, tools)
# -----------------------------------------------------------------------------

host_tool_version() {
    local tool="$1" version=""
    case "$tool" in
        uv|node|claude|codex|gemini|pdflatex|tectonic) version=$("$tool" --version 2>/dev/null | head -1) ;;
        git) version=$(git --version 2>/dev/null) ;;
    esac
    echo "$version"
}

host_check_env() {
    [ -n "${NEURICO_HOST_QUIET:-}" ] && return 0
    local version=""
    [ -f "$PROJECT_ROOT/config/VERSION" ] && version=$(tr -d '[:space:]' < "$PROJECT_ROOT/config/VERSION")
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  NeuriCo host mode (no Docker)${NC}"
    echo -e "${BLUE}========================================${NC}"
    [ -n "$version" ] && echo -e "${BLUE}Version:${NC} $version"
    echo -e "${BLUE}Project:${NC} $PROJECT_ROOT"
    echo -e "${BLUE}Workspace:${NC} ${NEURICO_WORKSPACE:-$(host_workspace_dir)}"
    if [ -n "${HOST_PYTHON:-}" ]; then
        echo -e "${BLUE}Python:${NC} $HOST_PYTHON ($("$HOST_PYTHON" --version 2>&1))"
    fi
    echo ""

    echo -e "${BLUE}Checking environment...${NC}"
    if [ ! -f "$PROJECT_ROOT/.env" ]; then
        echo -e "  ${YELLOW}[WARN]${NC} .env not found (cp .env.example .env, or ./neurico config)"
    fi
    if [ -n "${OPENAI_API_KEY:-}" ]; then
        echo -e "  ${GREEN}[OK]${NC} OPENAI_API_KEY configured (IdeaHub, paper-finder)"
    else
        echo -e "  ${YELLOW}[INFO]${NC} OPENAI_API_KEY not set (IdeaHub and paper-finder won't work)"
    fi
    if [ -n "${GITHUB_TOKEN:-}" ]; then
        echo -e "  ${GREEN}[OK]${NC} GITHUB_TOKEN configured"
    else
        echo -e "  ${YELLOW}[INFO]${NC} GITHUB_TOKEN not set - use --no-github flag"
    fi
    [ -n "${S2_API_KEY:-}" ] && echo -e "  ${GREEN}[OK]${NC} S2_API_KEY configured (paper-finder)"
    [ -n "${OPENROUTER_KEY:-}${OPENROUTER_API_KEY:-}" ] && echo -e "  ${GREEN}[OK]${NC} OPENROUTER key configured"
    [ -n "${HF_TOKEN:-}" ] && echo -e "  ${GREEN}[OK]${NC} HF_TOKEN configured"
    if [ "${NEURICO_AZURE:-}" = "1" ] && [ -n "${AZURE_OPENAI_API_KEY:-}" ]; then
        echo -e "  ${GREEN}[OK]${NC} Azure active for agents (resource: ${AZURE_FOUNDRY_RESOURCE:-custom base URL}; agent auth: ${NEURICO_AGENT_AUTH:-oauth})"
    fi
    [ -n "${HF_HOME:-}" ] && echo -e "  ${GREEN}[OK]${NC} HF_HOME=$HF_HOME"
    echo ""

    echo -e "${BLUE}GPU Status:${NC}"
    if command -v nvidia-smi >/dev/null 2>&1; then
        if nvidia-smi >/dev/null 2>&1; then
            nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader 2>/dev/null | \
                while IFS=',' read -r idx name mem driver; do
                    echo -e "  ${GREEN}[GPU $idx]${NC} $name |$mem | Driver:$driver"
                done
            if [ -n "${CUDA_VISIBLE_DEVICES:-}" ]; then
                echo -e "  ${BLUE}[PIN]${NC} CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES (nvidia-smi still lists every GPU)"
            fi
        else
            echo -e "  ${YELLOW}[WARN]${NC} nvidia-smi failed - GPU may not be accessible"
        fi
    else
        echo -e "  ${YELLOW}[WARN]${NC} nvidia-smi not available"
    fi
    echo ""

    echo -e "${BLUE}CLI tools:${NC}"
    local tool
    for tool in claude codex gemini uv node git; do
        if command -v "$tool" >/dev/null 2>&1; then
            echo -e "  ${GREEN}[OK]${NC} $tool $(host_tool_version "$tool")"
        else
            echo -e "  ${YELLOW}[MISSING]${NC} $tool"
        fi
    done
    if command -v pdflatex >/dev/null 2>&1; then
        echo -e "  ${GREEN}[OK]${NC} pdflatex $(host_tool_version pdflatex)"
    elif command -v tectonic >/dev/null 2>&1; then
        echo -e "  ${GREEN}[OK]${NC} tectonic $(host_tool_version tectonic) (no pdflatex)"
    else
        echo -e "  ${YELLOW}[WARN]${NC} no pdflatex/tectonic: papers will be written but main.pdf will not compile"
        echo "         install texlive (apt install texlive-latex-extra) or tectonic in ~/.local/bin"
    fi
    echo ""
}

# -----------------------------------------------------------------------------
# Job control (replacement for `docker run --name` / `docker kill`)
# -----------------------------------------------------------------------------

# Signal the process group recorded in a pid file. Never signals by name.
host_signal_job() {
    local pid_file="$1" sig="${2:-TERM}"
    local pgid
    pgid=$(tr -d '[:space:]' 2>/dev/null < "$pid_file")
    [[ "$pgid" =~ ^[0-9]+$ ]] || return 1
    kill -s "$sig" -- "-$pgid" 2>/dev/null
}

# True when any process still belongs to the group in the pid file.
host_job_alive() {
    local pgid
    pgid=$(tr -d '[:space:]' 2>/dev/null < "$1")
    [[ "$pgid" =~ ^[0-9]+$ ]] && pgrep -g "$pgid" >/dev/null 2>&1
}

# Run a command as a job: cwd PROJECT_ROOT (docker's -w /app), its own session
# so a group kill reaches every agent child, a pid file holding the group id,
# INT/TERM/HUP forwarded to the group (docker run's signal proxy), and the pid
# file removed on exit. Exit status is the command's.
#
# A plain interactive invocation (TTY, no NEURICO_CONTAINER_NAME) stays in the
# terminal's foreground group so prompts and Ctrl-C behave normally; batch
# tools and the safety daemon always name their jobs and get a new session.
host_run() {
    local name="${NEURICO_CONTAINER_NAME:-neurico-host-$$}"
    local pid_file
    pid_file="$(host_jobs_dir)/$name.pid"
    if [ -n "${NEURICO_DRY_RUN:-}" ]; then
        echo -e "${DIM}[dry-run] job $name (cwd $PROJECT_ROOT)${NC}"
        printf '[dry-run]'; printf ' %q' "$@"; echo
        return 0
    fi
    mkdir -p "$(dirname "$pid_file")"
    rm -f "$pid_file"
    # The child writes its own group id, so the file is right whether or not
    # setsid(1) had to fork.
    local -a wrapper=( bash -c 'echo "$(ps -o pgid= -p $$ | tr -d " ")" > "$1"; cd "$2"; shift 2; exec "$@"' _ "$pid_file" "$PROJECT_ROOT" )
    if command -v setsid >/dev/null 2>&1 && { [ ! -t 0 ] || [ -n "${NEURICO_CONTAINER_NAME:-}" ]; }; then
        setsid --wait "${wrapper[@]}" "$@" &
    else
        "${wrapper[@]}" "$@" &
    fi
    local child=$! rc=0
    trap 'host_signal_job "$pid_file" INT' INT
    trap 'host_signal_job "$pid_file" TERM' TERM
    trap 'host_signal_job "$pid_file" HUP' HUP
    # A trapped signal interrupts `wait`; loop until the child is really gone.
    while kill -0 "$child" 2>/dev/null; do
        wait "$child" && rc=0 || rc=$?
    done
    trap - INT TERM HUP
    rm -f "$pid_file"
    return "$rc"
}

# `./neurico --host kill <name>`: TERM the job's group, KILL after a grace period.
host_cmd_kill() {
    local name="$1"
    if [ -z "$name" ]; then
        echo -e "${RED}Usage: $0 --host kill <job-name>   (see: $0 --host jobs)${NC}"
        return 1
    fi
    local pid_file
    pid_file="$(host_jobs_dir)/$name.pid"
    if [ ! -f "$pid_file" ]; then
        echo -e "${RED}No host job named '$name' (no $pid_file)${NC}"
        return 1
    fi
    if ! host_job_alive "$pid_file"; then
        echo -e "${YELLOW}Job '$name' is not running; removing stale pid file${NC}"
        rm -f "$pid_file"
        return 0
    fi
    local pgid grace="${NEURICO_HOST_KILL_GRACE:-15}" i
    pgid=$(tr -d '[:space:]' 2>/dev/null < "$pid_file")
    host_signal_job "$pid_file" TERM || true
    for ((i = 0; i < grace; i++)); do
        host_job_alive "$pid_file" || break
        sleep 1
    done
    if host_job_alive "$pid_file"; then
        host_signal_job "$pid_file" KILL || true
        echo -e "${YELLOW}Killed job '$name' (process group $pgid, SIGKILL after ${grace}s)${NC}"
    else
        echo -e "${GREEN}Stopped job '$name' (process group $pgid)${NC}"
    fi
}

# `./neurico --host jobs`: list pid files and whether their group is alive.
host_cmd_jobs() {
    local dir pid_file name
    dir=$(host_jobs_dir)
    echo -e "${BOLD}Host jobs${NC} ($dir):"
    local found=false
    for pid_file in "$dir"/*.pid; do
        [ -f "$pid_file" ] || continue
        found=true
        name=$(basename "$pid_file" .pid)
        if host_job_alive "$pid_file"; then
            echo -e "  ${GREEN}[RUNNING]${NC} $name (pgid $(tr -d '[:space:]' < "$pid_file"))"
        else
            echo -e "  ${DIM}[STALE]${NC}   $name"
        fi
    done
    [ "$found" = true ] || echo "  (none)"
}

# -----------------------------------------------------------------------------
# Paper-finder service (one shared instance per host, port 8000 as in dev.sh)
# -----------------------------------------------------------------------------

host_paper_finder_healthy() {
    curl -s -m 2 http://localhost:8000/health >/dev/null 2>&1
}

# Reuse a healthy server; otherwise start one with the repo's own mechanism
# (agents/mabool/api/dev.sh via uv) when the keys and its venv exist. Only
# warns on failure: the paper-finder skill falls back to manual search.
host_paper_finder_start() {
    [ -n "${NEURICO_DRY_RUN:-}" ] && return 0
    echo -e "${BLUE}Paper-finder Service:${NC}"
    if [ -z "${S2_API_KEY:-}" ]; then
        echo -e "  ${YELLOW}[INFO]${NC} S2_API_KEY not set - paper-finder disabled (agents use manual search)"
        echo ""
        return 0
    fi
    if [ -z "${OPENROUTER_KEY:-}${OPENROUTER_API_KEY:-}${OPENAI_API_KEY:-}" ]; then
        echo -e "  ${YELLOW}[WARN]${NC} OPENROUTER_KEY (or OPENAI_API_KEY) required for paper-finder"
        echo ""
        return 0
    fi
    echo -e "  ${GREEN}[OK]${NC} S2_API_KEY configured"
    if host_paper_finder_healthy; then
        echo -e "  ${GREEN}[OK]${NC} Reusing paper-finder at localhost:8000"
        host_paper_finder_cohere_note
        echo ""
        return 0
    fi
    local dir="$PROJECT_ROOT/services/paper-finder"
    if [ ! -f "$dir/agents/mabool/api/dev.sh" ]; then
        echo -e "  ${YELLOW}[WARN]${NC} Paper-finder not installed (services/paper-finder)"
        echo ""
        return 0
    fi
    if [ ! -x "$dir/.venv/bin/python" ] || ! command -v uv >/dev/null 2>&1; then
        echo -e "  ${YELLOW}[WARN]${NC} Paper-finder venv not built - run: ./neurico --host build (needs uv + Python >= 3.12)"
        echo "         Agents will use manual search (arXiv, Semantic Scholar, Papers with Code)"
        echo ""
        return 0
    fi
    local log="$PROJECT_ROOT/logs/paper-finder.log" pid_file="$PROJECT_ROOT/logs/paper-finder.pid"
    echo "  Starting paper-finder service (log: $log)..."
    (
        cd "$dir/agents/mabool/api" && \
        nohup setsid bash -c 'echo "$(ps -o pgid= -p $$ | tr -d " ")" > "$1"; shift; exec "$@"' _ "$pid_file" \
            uv run --no-sync sh dev.sh >> "$log" 2>&1 < /dev/null &
    )
    local i
    for i in $(seq 1 60); do
        if host_paper_finder_healthy; then
            echo -e "  ${GREEN}[OK]${NC} Paper-finder started at localhost:8000"
            host_paper_finder_cohere_note
            echo ""
            return 0
        fi
        sleep 1
    done
    echo -e "  ${YELLOW}[WARN]${NC} Paper-finder failed to start - using manual search fallback"
    echo "         Check $log for errors"
    echo ""
    return 0
}

host_paper_finder_cohere_note() {
    if [ -n "${COHERE_API_KEY:-}" ]; then
        echo -e "  ${GREEN}[OK]${NC} COHERE_API_KEY configured (full reranking)"
    else
        echo -e "  ${YELLOW}[INFO]${NC} COHERE_API_KEY not set (reranking disabled, 92.5% quality)"
    fi
}

# Stop the paper-finder we started (by its pid file only).
host_paper_finder_stop() {
    local pid_file="$PROJECT_ROOT/logs/paper-finder.pid"
    if [ ! -f "$pid_file" ]; then
        echo -e "${YELLOW}No paper-finder started by this checkout ($pid_file missing)${NC}"
        host_paper_finder_healthy && echo "A server still answers on localhost:8000 (started elsewhere); leaving it alone."
        return 0
    fi
    if host_job_alive "$pid_file"; then
        host_signal_job "$pid_file" TERM || true
        local i
        for i in $(seq 1 10); do
            host_job_alive "$pid_file" || break
            sleep 1
        done
        if host_job_alive "$pid_file"; then
            host_signal_job "$pid_file" KILL || true
        fi
        echo -e "${GREEN}Paper-finder stopped${NC}"
    else
        echo -e "${YELLOW}Paper-finder was not running; removing stale pid file${NC}"
    fi
    rm -f "$pid_file"
}

host_paper_finder_status() {
    local pid_file="$PROJECT_ROOT/logs/paper-finder.pid"
    if host_paper_finder_healthy; then
        echo -e "    Paper-finder ........ ${GREEN}[OK]${NC} localhost:8000 answers"
    else
        echo -e "    Paper-finder ........ ${DIM}[--]${NC} not running"
    fi
    if [ -f "$pid_file" ]; then
        if host_job_alive "$pid_file"; then
            echo "      started by this checkout (pgid $(tr -d '[:space:]' < "$pid_file"))"
        else
            echo "      stale pid file: $pid_file"
        fi
    fi
    if [ -x "$PROJECT_ROOT/services/paper-finder/.venv/bin/python" ]; then
        echo -e "    Paper-finder venv ... ${GREEN}[OK]${NC}"
    else
        echo -e "    Paper-finder venv ... ${YELLOW}[MISSING]${NC} run: ./neurico --host build"
    fi
}

# -----------------------------------------------------------------------------
# Helpers shared by the subcommands
# -----------------------------------------------------------------------------

# Absolute path of an idea file that must exist (replaces the /input mount).
host_idea_abs() {
    local idea_file="$1"
    if [ ! -f "$idea_file" ]; then
        echo -e "${RED}Error: idea file not found: $idea_file${NC}" >&2
        return 1
    fi
    echo "$(cd "$(dirname "$idea_file")" && pwd)/$(basename "$idea_file")"
}

# Docker mounted ideas/mounts/<idea_id>.txt paths read-only; natively they are
# simply used in place, so only report the ones that do not exist here.
host_warn_missing_resources() {
    local mounts_file="$PROJECT_ROOT/ideas/mounts/${1}.txt"
    [ -f "$mounts_file" ] || return 0
    local host_path
    while IFS= read -r host_path; do
        [ -z "$host_path" ] && continue
        if [ -e "$host_path" ]; then
            echo -e "${BLUE}Local resource:${NC} $host_path"
        else
            echo -e "${YELLOW}[SKIP]${NC} declared local path not found on this machine: $host_path"
        fi
    done < "$mounts_file"
}

# Common preamble: env, interpreter, banner.
host_prepare() {
    host_load_env
    host_python || exit 1
    host_check_env
}

# -----------------------------------------------------------------------------
# Subcommands (same entrypoints and argument forwarding as the Docker route)
# -----------------------------------------------------------------------------

host_cmd_fetch() {
    if [ -z "$1" ]; then
        echo -e "${RED}Usage: $0 fetch <ideahub_url> [--submit]${NC}"
        exit 1
    fi
    host_prepare
    echo -e "${BLUE}Fetching from IdeaHub...${NC}"
    echo -e "${BLUE}Workspace:${NC} $NEURICO_WORKSPACE"
    host_run "$HOST_PYTHON" "$PROJECT_ROOT/src/cli/fetch_from_ideahub.py" "$@"
}

# submit: strips the runner flags exactly like cmd_submit, then runs them via host_cmd_run.
host_cmd_submit() {
    if [ -z "$1" ]; then
        echo -e "${RED}Usage: $0 submit <idea.yaml> [options]${NC}"
        exit 1
    fi
    host_prepare
    local idea_file="$1"
    shift
    local do_run=false provider="claude" provider_given=false model="" full_permissions=false
    local submit_args=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --run) do_run=true ;;
            --provider) provider="$2"; provider_given=true; shift ;;
            --provider=*) provider="${1#*=}"; provider_given=true ;;
            --model) model="$2"; shift ;;
            --model=*) model="${1#*=}" ;;
            --full-permissions) full_permissions=true ;;
            *) submit_args+=("$1") ;;
        esac
        shift
    done
    [ "$provider_given" = true ] && submit_args+=( --provider "$provider" )
    [ -n "$model" ] && submit_args+=( --model "$model" )
    local idea_abs
    idea_abs=$(host_idea_abs "$idea_file") || exit 1

    echo -e "${BLUE}Submitting research idea...${NC}"
    echo -e "${BLUE}Workspace:${NC} $NEURICO_WORKSPACE"
    local output_file
    output_file=$(mktemp)
    host_run "$HOST_PYTHON" "$PROJECT_ROOT/src/cli/submit.py" "$idea_abs" ${submit_args[@]+"${submit_args[@]}"} | tee "$output_file"
    local submit_rc=${PIPESTATUS[0]}
    if [ "$submit_rc" -ne 0 ]; then
        rm -f "$output_file"
        echo -e "${RED}[ERROR]${NC} submit failed (exit $submit_rc)"
        exit "$submit_rc"
    fi
    if [ "$do_run" = true ]; then
        local idea_id
        idea_id=$(grep "^Idea ID:" "$output_file" | sed 's/^Idea ID:[[:space:]]*//' | tr -d '[:space:]')
        rm -f "$output_file"
        if [ -n "$idea_id" ]; then
            echo ""
            local run_flags=()
            [ "$full_permissions" = true ] && run_flags+=( --full-permissions )
            [ -n "$model" ] && run_flags+=( --model "$model" )
            host_cmd_run "$idea_id" --provider "$provider" ${run_flags[@]+"${run_flags[@]}"}
        else
            echo -e "${RED}[ERROR]${NC} Could not extract idea ID from submit output - run manually with: ./neurico --host run <idea_id>"
        fi
    else
        rm -f "$output_file"
    fi
}

# submit-local: same flag handling as cmd_submit_local (--run is intercepted
# so the run goes through host_cmd_run); NEURICO_HOST_CWD keeps relative
# local_resources paths meaningful; NEURICO_IN_DOCKER is deliberately unset.
host_cmd_submit_local() {
    if [ -z "$1" ]; then
        echo -e "${RED}Usage: $0 submit-local <idea.md> [--submit] [--run] [--provider claude|codex|gemini]${NC}"
        exit 1
    fi
    local host_cwd="$PWD"
    host_prepare
    local idea_file="$1"
    shift
    local do_run=false provider="claude" has_submit=false
    local submit_args=() run_flags=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --run) do_run=true ;;
            --provider)
                if [ -z "${2:-}" ]; then
                    echo -e "${RED}Error: --provider requires a value${NC}"
                    exit 1
                fi
                provider="$2"; submit_args+=("$1" "$2"); shift ;;
            --provider=*)
                provider="${1#*=}"; submit_args+=("$1") ;;
            --full-permissions|--no-full-permissions|--write-paper|--no-write-paper)
                run_flags+=("$1"); submit_args+=("$1") ;;
            --paper-style|--paper-timeout)
                if [ -z "${2:-}" ]; then
                    echo -e "${RED}Error: $1 requires a value${NC}"
                    exit 1
                fi
                run_flags+=("$1" "$2"); submit_args+=("$1" "$2"); shift ;;
            --submit) has_submit=true; submit_args+=("$1") ;;
            *) submit_args+=("$1") ;;
        esac
        shift
    done
    if [ "$do_run" = true ] && [ "$has_submit" = false ]; then
        echo -e "${RED}Error: --run requires --submit${NC}"
        exit 1
    fi
    local idea_abs
    idea_abs=$(host_idea_abs "$idea_file") || exit 1

    echo -e "${BLUE}Converting local idea file...${NC}"
    echo -e "${BLUE}Workspace:${NC} $NEURICO_WORKSPACE"
    local output_file
    output_file=$(mktemp)
    NEURICO_HOST_CWD="$host_cwd" \
        host_run "$HOST_PYTHON" "$PROJECT_ROOT/src/cli/submit_local.py" "$idea_abs" ${submit_args[@]+"${submit_args[@]}"} | tee "$output_file"
    local submit_rc=${PIPESTATUS[0]}
    if [ "$submit_rc" -ne 0 ]; then
        rm -f "$output_file"
        echo -e "${RED}[ERROR]${NC} submit-local failed (exit $submit_rc)"
        exit "$submit_rc"
    fi
    if [ "$do_run" = true ]; then
        local idea_id
        idea_id=$(grep "Idea submitted successfully:" "$output_file" \
                  | tail -1 | sed 's/.*Idea submitted successfully:[[:space:]]*//' | tr -d '[:space:]')
        rm -f "$output_file"
        if [ -n "$idea_id" ]; then
            echo ""
            host_cmd_run "$idea_id" --provider "$provider" ${run_flags[@]+"${run_flags[@]}"}
        else
            echo -e "${RED}[ERROR]${NC} Could not extract idea ID from submit output - run manually with: ./neurico --host run <idea_id>"
        fi
    else
        rm -f "$output_file"
    fi
}

host_cmd_run() {
    if [ -z "$1" ]; then
        echo -e "${RED}Usage: $0 run <idea_id> [--provider claude|codex|gemini] [options]${NC}"
        exit 1
    fi
    host_prepare
    # Validate HITL web flags like the Docker route; no port publishing is
    # needed natively (hitl_web.py binds loopback by default).
    hitl_web_port_from_args "$@" >/dev/null || exit 1
    host_warn_missing_resources "$1"
    [ -n "${NEURICO_HF_CACHE:-}" ] && echo -e "${BLUE}Hugging Face cache:${NC} $HF_HOME"
    host_paper_finder_start
    echo -e "${BLUE}Running research exploration...${NC}"
    echo -e "${BLUE}Workspace:${NC} $NEURICO_WORKSPACE"
    host_run "$HOST_PYTHON" "$PROJECT_ROOT/src/core/runner.py" "$@"
}

host_cmd_baseline() {
    if [ -z "$1" ]; then
        echo -e "${RED}Usage: $0 baseline <idea.yaml> --provider claude|codex [--model <model>] [options]${NC}"
        exit 1
    fi
    host_prepare
    local idea_abs
    idea_abs=$(host_idea_abs "$1") || exit 1
    shift
    host_paper_finder_start
    echo -e "${BLUE}Running zero-shot baseline...${NC}"
    echo -e "${BLUE}Workspace:${NC} $NEURICO_WORKSPACE"
    host_run "$HOST_PYTHON" "$PROJECT_ROOT/baseline/zero_shot.py" "$idea_abs" "$@"
}

# Standalone HITL interfaces. Without NEURICO_HITL_DOCKER_HANDOFF the launcher
# spawns hitl_run_worker.py natively, so no handoff watcher is needed.
host_cmd_hitl() {
    local interface="$1"
    shift
    if [ "$interface" = "cli" ] && [ -z "$1" ]; then
        echo -e "${RED}Usage: $0 hitl-cli <idea_id>${NC}"
        exit 1
    fi
    host_prepare
    if [ "$interface" = "web" ]; then
        hitl_direct_web_port_from_args "$@" >/dev/null || exit 1
    fi
    if [ -n "$1" ] && [[ "$1" != --* ]]; then
        host_warn_missing_resources "$1"
    fi
    host_paper_finder_start
    echo -e "${BLUE}Starting HITL ${interface} interface (host mode)...${NC}"
    echo -e "${BLUE}Workspace:${NC} $NEURICO_WORKSPACE"
    host_run "$HOST_PYTHON" "$PROJECT_ROOT/src/cli/hitl_${interface}.py" "$@"
}

host_cmd_hitl_stop() {
    if [ -z "$1" ]; then
        echo -e "${RED}Usage: $0 hitl-stop <idea_id> [--yes]${NC}"
        exit 1
    fi
    host_load_env
    host_python || exit 1
    cd "$PROJECT_ROOT" && "$HOST_PYTHON" "$PROJECT_ROOT/src/cli/hitl_stop.py" "$@"
}

# Map the container paths the interactive manager may still produce.
host_map_container_path() {
    case "$1" in
        /workspaces) echo "$NEURICO_WORKSPACE" ;;
        /workspaces/*) echo "$NEURICO_WORKSPACE/${1#/workspaces/}" ;;
        /app) echo "$PROJECT_ROOT" ;;
        /app/*) echo "$PROJECT_ROOT/${1#/app/}" ;;
        *) echo "$1" ;;
    esac
}

# _run-agent (interactive manager): agent_runner.py natively, host paths.
host_cmd_run_agent() {
    if [ -z "$1" ]; then
        echo -e "${RED}Usage: $0 _run-agent <agent_name> --workspace <path> --provider <provider> --run-id <id> --idea-file <path>${NC}"
        exit 1
    fi
    host_load_env
    host_python || exit 1
    local -a args=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --workspace|--idea-file)
                args+=("$1" "$(host_map_container_path "${2:-}")"); shift ;;
            *) args+=("$1") ;;
        esac
        shift
    done
    echo -e "${BLUE}Running agent: ${args[0]}${NC}"
    host_run "$HOST_PYTHON" "$PROJECT_ROOT/src/core/agent_runner.py" "${args[@]}"
}

# Interactive manager (already host-side in Docker mode; here with the venv).
host_cmd_interactive() {
    if [ -z "$1" ]; then
        echo -e "${RED}Usage: $0 interactive <idea_id> [--provider claude] [--engagement balanced] [--cli] [--port N] [--no-browser]${NC}"
        exit 1
    fi
    host_load_env
    host_python || exit 1
    echo -e "${BLUE}Starting NeuriCo Interactive Mode (host mode)...${NC}"
    echo ""
    host_run "$HOST_PYTHON" "$PROJECT_ROOT/src/interactive/manager.py" "$@"
}

# Safety engine: same interpreter rule; the daemon inherits NEURICO_MODE=host
# and therefore launches its ./neurico jobs natively too.
host_cmd_safety() {
    host_load_env
    host_python || exit 1
    cd "$PROJECT_ROOT" && exec "$HOST_PYTHON" "$PROJECT_ROOT/src/cli/safety.py" "$@"
}

# Shell with the job environment loaded (docker: bash in /workspaces).
host_cmd_shell() {
    host_prepare
    export PATH="$PROJECT_ROOT/.venv/bin:$PATH"
    echo -e "${BLUE}Starting host-mode shell${NC} (venv on PATH, NEURICO_* exported; exit to leave)"
    echo -e "${BLUE}Workspace:${NC} $NEURICO_WORKSPACE"
    cd "$NEURICO_WORKSPACE" && exec bash
}

# login: the CLIs read $HOME directly, so just run their login flows.
host_cmd_login() {
    local provider="${1:-claude}"
    case "$provider" in
        claude)
            command -v claude >/dev/null || { echo -e "${RED}claude not found on PATH${NC}"; exit 1; }
            echo -e "${BLUE}Starting Claude Code; use /login inside it, then /exit.${NC}"
            exec claude ;;
        codex)
            command -v codex >/dev/null || { echo -e "${RED}codex not found on PATH${NC}"; exit 1; }
            exec codex login ;;
        gemini)
            command -v gemini >/dev/null || { echo -e "${RED}gemini not found on PATH${NC}"; exit 1; }
            echo -e "${BLUE}Starting Gemini CLI; use /auth inside it, then /quit.${NC}"
            exec gemini ;;
        *) echo -e "${RED}Unknown provider: $provider (claude|codex|gemini)${NC}"; exit 1 ;;
    esac
}

# setup: the Docker wizard builds images and login containers; natively the
# steps are plain commands, so print them with the current status.
host_cmd_setup() {
    show_banner
    echo -e "${BOLD}  Host mode setup${NC} ${DIM}(the Docker wizard is not applicable in host mode)${NC}"
    echo ""
    host_status
    echo "  Steps:"
    echo "    1. ./neurico --host build          # project venv (+ paper-finder venv if Python >= 3.12 is available)"
    echo "    2. ./neurico config                # API keys into .env"
    echo "    3. ./neurico --host login claude   # or: codex / gemini"
    echo "    4. ./neurico --host submit ideas/examples/ml_regularization_test.yaml --no-github"
    echo ""
}

# update: git pull (same rule as cmd_update step 1) + venv sync.
host_cmd_update() {
    echo -e "${BLUE}Updating NeuriCo (host mode)...${NC}"
    echo -e "  ${BOLD}Step 1/2: Code${NC}"
    if git -C "$PROJECT_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        if ! git -C "$PROJECT_ROOT" diff --quiet 2>/dev/null || ! git -C "$PROJECT_ROOT" diff --cached --quiet 2>/dev/null; then
            echo -e "    ${YELLOW}[SKIP]${NC} Uncommitted changes detected - pull skipped"
        elif git -C "$PROJECT_ROOT" pull --ff-only 2>/dev/null; then
            echo -e "    ${GREEN}[OK]${NC} Code updated ($(git -C "$PROJECT_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null))"
        else
            echo -e "    ${YELLOW}[WARN]${NC} git pull failed - you may have diverged from upstream"
        fi
    else
        echo -e "    ${YELLOW}[SKIP]${NC} Not a git repository"
    fi
    echo -e "  ${BOLD}Step 2/2: Python environment${NC}"
    host_cmd_build
}

# build: the venvs the Dockerfile bakes (project, then paper-finder; the latter
# needs Python >= 3.12.8 and is optional).
host_cmd_build() {
    if ! command -v uv >/dev/null 2>&1; then
        echo -e "${RED}Error: uv is required (https://docs.astral.sh/uv/)${NC}"
        exit 1
    fi
    echo -e "${BLUE}Syncing project venv (uv sync --frozen)...${NC}"
    host_uv_sync
    echo -e "  ${GREEN}[OK]${NC} $PROJECT_ROOT/.venv"
    local pf="$PROJECT_ROOT/services/paper-finder"
    if [ -f "$pf/pyproject.toml" ]; then
        echo -e "${BLUE}Building paper-finder venv (uv sync --all-packages --dev, Python >= 3.12)...${NC}"
        if (cd "$pf" && uv python install 3.12 >/dev/null 2>&1; uv sync --all-packages --dev); then
            echo -e "  ${GREEN}[OK]${NC} $pf/.venv"
        else
            echo -e "  ${YELLOW}[WARN]${NC} paper-finder venv failed to build; agents fall back to manual search"
        fi
    fi
    echo -e "${GREEN}Build complete.${NC}"
}

# update-tools: the same installers the image uses, into the user's PATH.
host_cmd_update_tools() {
    echo -e "${BLUE}Updating AI CLI tools (user-level installs)...${NC}"
    if command -v curl >/dev/null 2>&1; then
        echo "Updating Claude Code..."
        curl -fsSL https://claude.ai/install.sh | bash 2>&1 | tail -3 || true
    fi
    if command -v npm >/dev/null 2>&1; then
        echo "Updating Codex and Gemini CLI..."
        npm install -g @openai/codex@latest @google/gemini-cli@latest 2>&1 | tail -2 || true
    else
        echo -e "  ${YELLOW}[WARN]${NC} npm not found: Codex/Gemini need Node (https://nodejs.org)"
    fi
    echo "Versions installed:"
    echo "  Claude Code: $(claude --version 2>/dev/null || echo unknown)"
    echo "  Codex:       $(codex --version 2>/dev/null || echo unknown)"
    echo "  Gemini CLI:  $(gemini --version 2>/dev/null || echo unknown)"
}

host_cmd_paper_finder() {
    host_load_env
    case "${1:-status}" in
        start) host_paper_finder_start ;;
        stop) host_paper_finder_stop ;;
        status) host_paper_finder_status ;;
        *) echo -e "${RED}Usage: $0 --host paper-finder start|stop|status${NC}"; exit 1 ;;
    esac
}

# -----------------------------------------------------------------------------
# Status, help, dispatch
# -----------------------------------------------------------------------------

host_status() {
    echo -e "  ${BOLD}Status (host mode):${NC}"
    if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
        echo -e "    Python venv ......... ${GREEN}[OK]${NC} $("$PROJECT_ROOT/.venv/bin/python" --version 2>&1)"
    else
        echo -e "    Python venv ......... ${YELLOW}[MISSING]${NC} run: ./neurico --host build"
    fi
    if command -v uv >/dev/null 2>&1; then
        echo -e "    uv .................. ${GREEN}[OK]${NC} $(uv --version 2>/dev/null)"
    else
        echo -e "    uv .................. ${RED}[MISSING]${NC} https://docs.astral.sh/uv/"
    fi
    local tool pad
    for tool in claude codex gemini; do
        pad=$(printf '%*s' $((20 - ${#tool})) '' | tr ' ' '.')
        if command -v "$tool" >/dev/null 2>&1; then
            echo -e "    $tool $pad ${GREEN}[OK]${NC}"
        else
            echo -e "    $tool $pad ${DIM}[--]${NC} not on PATH"
        fi
    done
    if command -v pdflatex >/dev/null 2>&1 || command -v tectonic >/dev/null 2>&1; then
        echo -e "    LaTeX ............... ${GREEN}[OK]${NC}"
    else
        echo -e "    LaTeX ............... ${YELLOW}[WARN]${NC} no pdflatex/tectonic: papers will not compile"
    fi
    if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
        echo -e "    GPU ................. ${GREEN}[OK]${NC} $(nvidia-smi -L 2>/dev/null | wc -l | tr -d ' ') visible${NEURICO_GPUS:+ (NEURICO_GPUS=$NEURICO_GPUS)}"
    else
        echo -e "    GPU ................. ${DIM}[--]${NC} nvidia-smi not available"
    fi
    if [ -f "$PROJECT_ROOT/.env" ]; then
        echo -e "    .env ................ ${GREEN}[OK]${NC} configured"
    else
        echo -e "    .env ................ ${YELLOW}[MISSING]${NC} run: ./neurico config"
    fi
    host_paper_finder_status
    echo ""
}

host_help() {
    show_banner
    host_status
    echo "Usage: $0 --host <command> [arguments]"
    echo "       (or: ./neurico-host <command>, or NEURICO_MODE=host ./neurico <command>)"
    echo ""
    echo "Commands (run natively, no Docker):"
    echo "  setup                     Show host-mode setup steps and status"
    echo "  config                    Configure API keys and settings (.env)"
    echo "  build                     uv sync the project venv (+ paper-finder venv)"
    echo "  update                    git pull + uv sync"
    echo "  login [provider]          Run the CLI login (claude/codex/gemini)"
    echo "  shell                     Shell with the job environment loaded"
    echo "  fetch <url> [--submit]    Fetch idea from IdeaHub"
    echo "  submit-local <idea.md> [--submit]  Convert a local idea file (markdown/text)"
    echo "  submit <idea.yaml>        Submit a research idea"
    echo "  run <id> [options]        Run research exploration"
    echo "  baseline <idea.yaml>      Run a zero-shot baseline (single agent session)"
    echo "  hitl-web [id]             Open the HITL idea portal"
    echo "  hitl-cli <id>             Open the HITL terminal client"
    echo "  hitl-stop <id> [--yes]    Stop HITL research and preserve saved progress"
    echo "  interactive <id>          Interactive manager"
    echo "  safety <subcommand>       Safety engine (its daemon launches host-mode jobs)"
    echo "  jobs                      List host jobs (logs/host-jobs/*.pid)"
    echo "  kill <job-name>           Stop a job's process group (replaces docker kill)"
    echo "  paper-finder start|stop|status"
    echo "  update-tools              Reinstall Claude/Codex/Gemini CLIs for this user"
    echo "  bump-version <version>    Bump version across all files"
    echo "  help                      Show this help message"
    echo ""
    echo "Not applicable in host mode: up, down, logs (Docker compose)."
    echo ""
    echo "Environment: NEURICO_CONTAINER_NAME names a job; NEURICO_GPUS pins CUDA_VISIBLE_DEVICES;"
    echo "             NEURICO_HF_CACHE sets HF_HOME; NEURICO_DRY_RUN=1 prints the command instead of running it."
    echo ""
}

host_not_applicable() {
    echo -e "${YELLOW}'$1' is not applicable in host mode (it manages the Docker container).${NC}"
    echo "Use the Docker route: ./neurico $1"
    exit 2
}

# Entry point from run.sh: host_dispatch <action> [args...]
host_dispatch() {
    local action="$1"
    shift
    case "$action" in
        setup)          host_cmd_setup "$@" ;;
        config)         cmd_config ;;
        update)         host_cmd_update ;;
        build)          host_cmd_build ;;
        login)          host_cmd_login "$@" ;;
        shell)          host_cmd_shell ;;
        fetch)          host_cmd_fetch "$@" ;;
        submit-local)   host_cmd_submit_local "$@" ;;
        submit)         host_cmd_submit "$@" ;;
        run)            host_cmd_run "$@" ;;
        baseline)       host_cmd_baseline "$@" ;;
        safety)         host_cmd_safety "$@" ;;
        _run-agent)     host_cmd_run_agent "$@" ;;
        interactive)    host_cmd_interactive "$@" ;;
        hitl-web)       host_cmd_hitl web "$@" ;;
        hitl-cli)       host_cmd_hitl cli "$@" ;;
        hitl-stop)      host_cmd_hitl_stop "$@" ;;
        jobs)           host_cmd_jobs ;;
        kill)           host_cmd_kill "$@" ;;
        paper-finder)   host_cmd_paper_finder "$@" ;;
        update-tools)   host_cmd_update_tools ;;
        bump-version)   cmd_bump_version "$@" ;;
        up|down|logs)   host_not_applicable "$action" ;;
        help|--help|-h) host_help ;;
        *)
            echo -e "${RED}Unknown command: $action${NC}"
            host_help
            exit 1
            ;;
    esac
}
