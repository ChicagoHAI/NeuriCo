#!/usr/bin/env bash
set -euo pipefail

RUN_NAME="logit-lens-implicit-fbb4-codex"
REMOTE_HOST="bellahe@indigo.cs.uchicago.edu"
REMOTE_APP="/home/bellahe/NeuriCo/services/log-visualizer"
REMOTE_SOURCE_RUN="${REMOTE_APP}/test-runs/${RUN_NAME}"
REMOTE_DATA_RUN="${REMOTE_APP}/data/runs/${RUN_NAME}"
REMOTE_LAUNCHER="/home/bellahe/start-neurico-user-test.sh"
REMOTE_PORT="5174"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd -P)"
LOCAL_SOURCE_RUN="${REPO_ROOT}/services/log-visualizer/data/runs/${RUN_NAME}"
LOCAL_DATA_RUN="${LOCAL_SOURCE_RUN}"

shell_quote() {
  local value=${1//\'/\'\\\'\'}
  printf "'%s'" "${value}"
}

ssh_options=(-o IdentitiesOnly=yes)
if [[ -n "${SSH_IDENTITY_FILE:-}" ]]; then
  ssh_options+=(-i "${SSH_IDENTITY_FILE}")
fi

rsync_rsh="ssh -o IdentitiesOnly=yes"
if [[ -n "${SSH_IDENTITY_FILE:-}" ]]; then
  rsync_rsh+=" -i $(shell_quote "${SSH_IDENTITY_FILE}")"
fi

ssh_remote() {
  ssh "${ssh_options[@]}" "${REMOTE_HOST}" "$@"
}

rsync_remote_path() {
  local path=$1
  printf "%s:%s/" "${REMOTE_HOST}" "$(shell_quote "${path}")"
}

require_command() {
  local name=$1
  if ! command -v "${name}" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "${name}" >&2
    exit 1
  fi
}

require_local_path() {
  local path=$1
  if [[ ! -e "${path}" ]]; then
    printf 'Required local path is missing: %s\n' "${path}" >&2
    exit 1
  fi
}

require_command ssh
require_command rsync

if [[ -n "${SSH_IDENTITY_FILE:-}" && ! -f "${SSH_IDENTITY_FILE}" ]]; then
  printf 'SSH identity file does not exist: %s\n' "${SSH_IDENTITY_FILE}" >&2
  exit 1
fi

required_run_paths=(
  "paper_draft/main.pdf"
  ".neurico"
  "logs"
  "results"
  "figures"
  "canonical_trajectory.json"
  "world_model.json"
  "annotations.json"
  "processing-status.json"
)

for rel in "${required_run_paths[@]}"; do
  require_local_path "${LOCAL_SOURCE_RUN}/${rel}"
done

require_local_path "${SCRIPT_DIR}/server.js"
require_local_path "${SCRIPT_DIR}/server_autoresearch.js"
require_local_path "${SCRIPT_DIR}/platform_core.js"
require_local_path "${SCRIPT_DIR}/package.json"
require_local_path "${SCRIPT_DIR}/public/app.js"
require_local_path "${SCRIPT_DIR}/public/vendor/pdfjs/pdf.min.mjs"
require_local_path "${SCRIPT_DIR}/public/vendor/pdfjs/pdf.worker.min.mjs"

printf 'Creating remote directories on %s\n' "${REMOTE_HOST}"
ssh_remote "mkdir -p -- $(shell_quote "${REMOTE_APP}") $(shell_quote "${REMOTE_APP}/public") $(shell_quote "${REMOTE_APP}/data/runs") $(shell_quote "${REMOTE_APP}/test-runs") $(shell_quote "${REMOTE_SOURCE_RUN}") $(shell_quote "${REMOTE_DATA_RUN}")"

printf 'Syncing application files to %s:%s\n' "${REMOTE_HOST}" "${REMOTE_APP}"
rsync -a -e "${rsync_rsh}" -- \
  "${SCRIPT_DIR}/server.js" \
  "${SCRIPT_DIR}/server_autoresearch.js" \
  "${SCRIPT_DIR}/platform_core.js" \
  "${SCRIPT_DIR}/package.json" \
  "${SCRIPT_DIR}/package-lock.json" \
  "$(rsync_remote_path "${REMOTE_APP}")"
rsync -a -e "${rsync_rsh}" -- "${SCRIPT_DIR}/public/" "$(rsync_remote_path "${REMOTE_APP}/public")"

printf 'Syncing source run to %s:%s\n' "${REMOTE_HOST}" "${REMOTE_SOURCE_RUN}"
rsync -a -e "${rsync_rsh}" -- "${LOCAL_SOURCE_RUN}/" "$(rsync_remote_path "${REMOTE_SOURCE_RUN}")"

printf 'Syncing processed visualizer data to %s:%s\n' "${REMOTE_HOST}" "${REMOTE_DATA_RUN}"
rsync -a -e "${rsync_rsh}" -- "${LOCAL_DATA_RUN}/" "$(rsync_remote_path "${REMOTE_DATA_RUN}")"

printf 'Verifying required remote files\n'
remote_verify='set -euo pipefail'
for rel in "${required_run_paths[@]}"; do
  remote_verify+="
test -e $(shell_quote "${REMOTE_SOURCE_RUN}/${rel}")
test -e $(shell_quote "${REMOTE_DATA_RUN}/${rel}")"
done
remote_verify+="
test -f $(shell_quote "${REMOTE_APP}/server.js")
test -f $(shell_quote "${REMOTE_APP}/public/app.js")
test -f $(shell_quote "${REMOTE_APP}/public/vendor/pdfjs/pdf.min.mjs")
test -f $(shell_quote "${REMOTE_APP}/public/vendor/pdfjs/pdf.worker.min.mjs")"
ssh_remote "${remote_verify}"

printf 'Installing remote launcher at %s:%s\n' "${REMOTE_HOST}" "${REMOTE_LAUNCHER}"
ssh_remote "cat > $(shell_quote "${REMOTE_LAUNCHER}")" <<'REMOTE_LAUNCHER_EOF'
#!/usr/bin/env bash
set -euo pipefail

export NVM_DIR="${HOME}/.nvm"
if [[ -s "${NVM_DIR}/nvm.sh" ]]; then
  # shellcheck source=/dev/null
  . "${NVM_DIR}/nvm.sh"
else
  printf 'nvm not found at %s\n' "${NVM_DIR}/nvm.sh" >&2
  exit 1
fi

nvm use 20
cd "/home/bellahe/NeuriCo/services/log-visualizer"

NEURICO_RUNS_ROOT="/home/bellahe/NeuriCo/services/log-visualizer/test-runs" \
NEURICO_DATA_DIR="/home/bellahe/NeuriCo/services/log-visualizer/data" \
NEURICO_RUN_DIR="/home/bellahe/NeuriCo/services/log-visualizer/test-runs/logit-lens-implicit-fbb4-codex" \
NEURICO_AUTOBUILD=0 \
NEURICO_AUTOSPAWN_WORKER=0 \
HOST=127.0.0.1 \
PORT=5174 \
node "server.js"
REMOTE_LAUNCHER_EOF
ssh_remote "chmod +x -- $(shell_quote "${REMOTE_LAUNCHER}")"

printf 'Checking HTTP endpoints if the remote server is already running\n'
ssh_remote "if command -v curl >/dev/null 2>&1; then
  curl -fsS --max-time 2 $(shell_quote "http://127.0.0.1:${REMOTE_PORT}/api/runs") >/dev/null && printf 'ok /api/runs\n' || printf 'skip/fail /api/runs (start launcher before final verification)\n'
  curl -fsS --max-time 2 $(shell_quote "http://127.0.0.1:${REMOTE_PORT}/api/run?runId=${RUN_NAME}") >/dev/null && printf 'ok /api/run\n' || printf 'skip/fail /api/run (start launcher before final verification)\n'
  curl -fsSI --max-time 2 $(shell_quote "http://127.0.0.1:${REMOTE_PORT}/api/file?path=paper_draft%2Fmain.pdf&runId=${RUN_NAME}") >/dev/null && printf 'ok paper /api/file\n' || printf 'skip/fail paper /api/file (start launcher before final verification)\n'
else
  printf 'curl not available on remote; run endpoint verification from the tunnel.\n'
fi"

printf '\nServer command:\n'
printf "ssh bellahe@indigo.cs.uchicago.edu '~/start-neurico-user-test.sh'\n"
printf '\nTunnel command:\n'
printf 'ssh -N -L 5200:127.0.0.1:5174 bellahe@indigo.cs.uchicago.edu\n'
printf '\nEndpoint verification after starting the server:\n'
printf 'curl -fsS http://localhost:5200/api/runs >/dev/null\n'
printf 'curl -fsS "http://localhost:5200/api/run?runId=logit-lens-implicit-fbb4-codex" >/dev/null\n'
printf 'curl -fsSI "http://localhost:5200/api/file?path=paper_draft%%2Fmain.pdf&runId=logit-lens-implicit-fbb4-codex"\n'
