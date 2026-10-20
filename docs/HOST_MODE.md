# Host mode (no Docker)

Host mode runs every `./neurico` subcommand natively on the machine you are on,
with the same Python entrypoints, the same argument forwarding and (as far as a
process can imitate a container) the same environment as the Docker route. It is
meant for compute servers where Docker is unavailable or undesirable, and for
batch tools (the safety daemon, `scripts/run_methods.py`) that launch many jobs.

## Switching it on

`NEURICO_MODE=host` is the single source of truth. Three equivalent spellings:

```bash
./neurico --host run <idea_id> --provider claude --no-github     # flag before the subcommand
./neurico-host run <idea_id> --provider claude --no-github       # wrapper at the repo root
NEURICO_MODE=host ./neurico run <idea_id> ...                    # environment (inherited by batch tools)
```

Without the switch nothing changes: the Docker route is untouched. The host
implementation lives in `docker/host.sh`, sourced by `docker/run.sh`, which only
contains two small hooks (`--host` parsing and `host_dispatch` before
`check_docker`).

## Requirements on the compute server

| Need | Why | Check |
| --- | --- | --- |
| Linux with `bash`, `setsid`, `pgrep`, `curl` | job control (process groups) and the paper-finder health check | `./neurico --host help` |
| [`uv`](https://docs.astral.sh/uv/) | builds `.venv` once (`./neurico --host build`); jobs then call `.venv/bin/python` directly, so parallel jobs never race on uv's auto-sync | status line `uv` |
| `claude` / `codex` / `gemini` on `PATH`, logged in as *this* user | agents run as you; no credential mounts or chmod workarounds | `./neurico --host login claude` (or `codex`, `gemini`) |
| `.env` in the checkout | loaded like `docker --env-file`; keys are reported by name only | `./neurico config` |
| Optional: texlive (`pdflatex`, `bibtex`, `latexmk`) or `tectonic` | paper compilation; without it `main.tex` is written but `main.pdf` is not produced | env check warns |
| Optional: NVIDIA driver + `nvidia-smi` | GPUs; `NEURICO_GPUS=0,2` exports `CUDA_VISIBLE_DEVICES=0,2` (Docker used `--gpus device=`) | env check lists GPUs |
| Optional: Python >= 3.12.8 via uv | the paper-finder service venv (`./neurico --host build`) | `./neurico --host paper-finder status` |

Nothing is installed system-wide by host mode.

Setup on a fresh server:

```bash
git clone https://github.com/ChicagoHAI/neurico.git && cd neurico
./neurico --host build            # uv sync --frozen (+ paper-finder venv when Python 3.12 is available)
./neurico config                  # API keys into .env
./neurico --host login claude     # or codex / gemini
./neurico --host submit ideas/examples/ml_regularization_test.yaml --no-github
./neurico --host run <idea_id> --provider claude --no-github --full-permissions
```

## What each subcommand does in host mode

| Command | Host mode |
| --- | --- |
| `submit`, `submit-local`, `fetch` | `src/cli/submit.py` / `submit_local.py` / `fetch_from_ideahub.py` with the absolute idea path (no `/input` mount). `--run`, `--provider`, `--model`, `--full-permissions` are intercepted exactly as in Docker and the run goes through the host `run`. |
| `run` | `src/core/runner.py "$@"`: all flags pass through unchanged (`--provider`, `--model`, `--agent-auth`, `--no-github`, timeouts, `--autoresearch`, `--hitl-autoresearch web|cli`, ...). Declared local resources (`ideas/mounts/<id>.txt`) are used in place; missing paths are reported. Starts or reuses the paper-finder. |
| `baseline` | `baseline/zero_shot.py <abs idea> "$@"` |
| `hitl-web`, `hitl-cli`, `hitl-stop` | `src/cli/hitl_web.py` / `hitl_cli.py` / `hitl_stop.py`; the web client binds loopback as before, workers are spawned natively (no Docker handoff watcher). |
| `interactive`, `_run-agent` | manager and `agent_runner.py` natively; `/workspaces/...` and `/app/...` paths are mapped to host paths, and `src/interactive/tools.py` skips the container-path translation. |
| `safety ...` | `src/cli/safety.py` with the venv interpreter; the daemon inherits `NEURICO_MODE=host` and launches its `./neurico` jobs natively. |
| `shell` | `bash` in the workspace directory with `.venv/bin` on `PATH` and every `NEURICO_*` variable exported. |
| `login [provider]` | runs the CLI's own login flow (`claude`, `codex login`, `gemini`). |
| `config`, `bump-version` | already Docker-free; unchanged. |
| `setup` | prints the host checklist and status (the Docker wizard is not applicable). |
| `build`, `update` | `uv sync --frozen` (+ paper-finder venv); `update` first does `git pull --ff-only` when the tree is clean. |
| `update-tools` | user-level reinstall of Claude Code (`claude.ai/install.sh`) and `npm i -g` Codex/Gemini. |
| `jobs`, `kill <name>` | list / stop host jobs (see below). |
| `paper-finder start|stop|status` | manage the shared paper-finder service. |
| `up`, `down`, `logs` | **not applicable** (Docker compose); exit 2 with a message. |

`NEURICO_DRY_RUN=1` prints the resolved command instead of running it (used by
`tests/test_host_mode.py`).

## Environment (what the container used to provide)

`host_load_env` exports, before any Python runs:

- `.env.local` then `.env` (`set -a; . file; set +a`), without overriding
  variables already in the environment (python-dotenv semantics, so a batch
  tool's `NEURICO_GPUS`, `HF_HOME`, `NEURICO_CONTAINER_NAME` win);
- `NEURICO_MODE=host`, `NEURICO_PROJECT_ROOT`, `NEURICO_SRC=<root>/src`,
  `NEURICO_ENV_FILE=<root>/.env` (the safety-evals skill reads the last two),
  `NEURICO_WORKSPACE` / `NEURICO_WORKSPACE_DIR` (environment, else
  `config/workspace.yaml`), `PYTHONPATH=<root>`, `PYTHONUNBUFFERED=1`,
  `GEMINI_CLI_TRUST_WORKSPACE=true` (the image's ENV);
- `HF_HOME=$NEURICO_HF_CACHE` when set; `CUDA_VISIBLE_DEVICES=$NEURICO_GPUS` when set.

Then the environment check prints what `docker/entrypoint.sh` printed: version,
which keys are configured (names only), the GPU list (`nvidia-smi`), the CLI
tools with versions, and a LaTeX warning when neither `pdflatex` nor `tectonic`
is on `PATH`. `NEURICO_HOST_QUIET=1` suppresses it.

## Job control (replacement for `docker kill`)

Each `run`/`baseline`/`submit`/... is started by `host_run`:

- `NEURICO_CONTAINER_NAME` names the job (default `neurico-host-<launcher pid>`);
- the job runs with cwd = project root (Docker's `-w /app`) and, when stdin is
  not a TTY or the job is named, in its own session (`setsid`), so every agent
  child shares one process group;
- `logs/host-jobs/<name>.pid` holds that group id and is removed on exit;
- SIGINT/SIGTERM/SIGHUP sent to the launcher are forwarded to the group (like
  `docker run`'s signal proxy); the launcher exits with the job's status.

```bash
./neurico --host jobs              # RUNNING / STALE per pid file
./neurico --host kill <name>       # SIGTERM the group, SIGKILL after NEURICO_HOST_KILL_GRACE (15 s)
```

Only groups recorded in those pid files are ever signalled; nothing is matched
by process name. The safety daemon (`src/safety/daemon.py`) and
`scripts/run_methods.py` do the same: in host mode (or when no `docker` binary
exists) they skip `docker kill`, SIGTERM the pid-file group and their own
child's group (`start_new_session=True`), and SIGKILL both after 15 s.

A plain interactive call from a terminal (TTY, no job name) stays in the
terminal's foreground process group so prompts and Ctrl-C work as usual.

## Paper-finder

`run`, `baseline`, `hitl-*` and `_run-agent` call `host_paper_finder_start`,
which:

1. does nothing unless `S2_API_KEY` and one of `OPENROUTER_KEY` /
   `OPENROUTER_API_KEY` / `OPENAI_API_KEY` are set;
2. reuses a server that answers `http://localhost:8000/health` (one shared
   instance per host, port fixed by `services/paper-finder/agents/mabool/api/dev.sh`);
3. otherwise starts it with the repo's own mechanism (`uv run --no-sync sh dev.sh`)
   under `nohup`/`setsid`, pid file `logs/paper-finder.pid`, log
   `logs/paper-finder.log`, and waits up to 60 s;
4. only warns when the venv is missing or the start fails: the paper-finder
   skill falls back to manual search, and the run is never failed because of it.

`./neurico --host build` creates the service venv (`uv python install 3.12 &&
uv sync --all-packages --dev`), `./neurico --host paper-finder stop` stops the
instance this checkout started.

## Differences from Docker

- Files are owned by you with your umask (Docker produced uid-1000, mode-777
  trees via `umask 000`). Resuming a Docker-made workspace natively works;
  resuming a host-made workspace in Docker later may need `chmod -R a+rwX`.
- No credential copies/chmods (`ensure_directories`, `scripts/keep_credentials_readable.sh`
  exits early in host mode); the CLIs read `$HOME` directly.
- `CUDA_VISIBLE_DEVICES` hides GPUs from torch/vLLM but `nvidia-smi` still
  lists all of them, so agents may see busy GPUs. Docker's `--gpus device=`
  hid them completely.
- Python is whatever `uv sync` picked for `.venv` (the image uses 3.12);
  `NEURICO_HOST_UV_PYTHON=3.12 ./neurico --host build` pins it.
- CLI versions are the ones installed for your user; `update-tools` updates
  them in place instead of committing a new image.
- HITL web ports are bound directly (default 7890); there is no `-p` publish
  step and therefore no port-conflict guard.
- `up`/`down`/`logs` (compose) do not exist; `setup` is a checklist.
- One paper-finder per host instead of one per container.
