# Host mode (no Docker) assessment

Branch `safety-engine`, 2026-10-20. Read-only investigation of what the Docker route
(`./neurico` -> `docker/run.sh` -> image -> `docker/entrypoint.sh`) provides, what the native
Python entrypoints already do on their own, and the smallest change that lets one switch
(`./neurico --host <cmd>` / `NEURICO_MODE=host ./neurico <cmd>` / `./neurico-host <cmd>`) run every
subcommand natively with the same behaviour.

Verdict: the Python side is almost entirely host-ready (project root, templates, workspace,
`.env`, skills, model forwarding, HITL handoff all resolve from `__file__` or env). What is
missing is (a) the launcher, which hard-exits without Docker, (b) a host-side equivalent of the
entrypoint (env, checks, paper-finder, GPU pinning), (c) two batch tools that kill by
`docker kill`, and (d) three host-package prerequisites (paper-finder venv, texlive, CLIs).

## 1. Summary table

| # | Docker route provides | Where (Docker) | Native status | What host mode must do |
|---|---|---|---|---|
| 1 | Refuses to start without `docker` | `docker/run.sh:161-167`, dispatch `:2509-2511` | blocker | skip `check_docker` when mode is host |
| 2 | `.env` via `--env-file` | `run.sh:528,575,675,805,925,1021,2353` | partial: `submit.py:12-24`, `submit_local.py:17-29`, `fetch_from_ideahub.py:17-29`, `runner.py:1994-2004`, `hitl_run_worker.py:42-49`, `baseline/zero_shot.py:482-486` load it; `hitl_web.py`, `hitl_cli.py`, `hitl_stop.py`, `agent_runner.py` do not | launcher sources `.env.local`/`.env` (`set -a`) once for every subcommand |
| 3 | `/app` project root, `PYTHONPATH=/app` | `entrypoint.sh:18-21`, `Dockerfile:149-158` | done: every entrypoint derives root from `__file__` (`runner.py:35-38,299`, `config_loader.py:29`, `kb.py:20`, `hitl_*.py`, `zero_shot.py:36-37`) and inserts `src` on `sys.path` | nothing; export `NEURICO_PROJECT_ROOT` for the HITL tool wrappers (`hitl.py:4344-4346`) |
| 4 | `/workspaces` + `NEURICO_WORKSPACE=/workspaces` | `run.sh:926-927` | done: `config_loader.py:253-270` falls back to `config/workspace.yaml` `parent_dir` (`config/workspace.yaml:14`) | export `NEURICO_WORKSPACE=$(get_workspace_dir)` for parity; do not pass `/workspaces` |
| 5 | `/input/<idea>` mount for submit/baseline | `run.sh:646,781,1029` | n/a (mount artefact) | pass the absolute host path |
| 6 | `ideas/mounts/<id>.txt` local-resource mounts | `run.sh:937-954`, `:2376-2391`, `:2269-2283` | n/a: paths are already host paths (`local_resources.py:640-660`) | skip; optionally warn when a declared path is missing |
| 7 | `NEURICO_HOST_CWD` / `NEURICO_IN_DOCKER` for submit-local | `run.sh:684-691` | done: `submit_local.py:623` uses cwd when unset; `:732-745` runs `--run` in-process when not in Docker | keep the `--run` interception in the launcher so both modes dispatch through `cmd_run` |
| 8 | HF cache: `-v $NEURICO_HF_CACHE:/hf_cache -e HF_HOME=/hf_cache` | `run.sh:956-961` | missing in launcher; `daemon.py:195,199-200` already exports `HF_HOME` | `export HF_HOME=$NEURICO_HF_CACHE` when set |
| 9 | Safety venv mount `NEURICO_SAFETY_VENV` (+ interpreter home) | `run.sh:964-975` | done: env var only; daemon sets it (`daemon.py:201-203`); skill uses `$NEURICO_SAFETY_VENV/bin/python` (`templates/skills/safety-evals/SKILL.md:21,41`) | pass through unchanged |
| 10 | Safety KB mount `/safety_kb`, `NEURICO_SAFETY_KB=/safety_kb` | `run.sh:971-974` | done: `kb.py:28` reads env or `PROJECT_ROOT/safety_kb`; daemon exports host path (`daemon.py:194`) | pass through; never rewrite to `/safety_kb` |
| 11 | Skill fallbacks `/app/src`, `/app/.env` | `templates/skills/safety-evals/scripts/_common.py:14`, `run_eval.py:70` | partial: overridable via `NEURICO_SRC` (`_common.py:12`) and `NEURICO_ENV_FILE` (`run_eval.py:70`); the parent walk from a workspace copy never finds `src/safety` | launcher exports `NEURICO_SRC=$PROJECT_ROOT/src`, `NEURICO_ENV_FILE=$PROJECT_ROOT/.env` |
| 12 | paper-finder service at `localhost:8000` | `entrypoint.sh:160-205` (`make start-dev` -> `dev.sh` gunicorn `0.0.0.0:8000`), venv built in `Dockerfile:85-88` | missing on host: no `services/paper-finder/.venv`; needs Python >= 3.12.8 (`services/paper-finder/pyproject.toml:4`); keys `S2_API_KEY` + `OPENROUTER_KEY`/`OPENROUTER_API_KEY`/`OPENAI_API_KEY` (`libs/chain/ai2i/chain/endpoints.py:145,185`), optional `COHERE_API_KEY`. Client hard-codes `http://localhost:8000` (`templates/skills/paper-finder/scripts/find_papers.py:23,114`) but degrades gracefully (`:47-52`) | `host_paper_finder_start`: reuse if `/health` answers, else start one shared instance (pid file + `logs/paper-finder.log`); `./neurico --host build` runs `uv python install 3.12 && uv sync --all-packages --dev` there |
| 13 | texlive (`pdflatex`, `bibtex`, `latexmk`, `biber`) | `Dockerfile:109-124`; used by agent prompts `templates/agents/paper_writer.txt:157`, `templates/skills/paper-writer/SKILL.md:316` | host package; present on this dev box (`/usr/bin/pdflatex`), unknown on the target server | check and warn; non-root fallback: TinyTeX/`tectonic` in `~/.local/bin` |
| 14 | CLIs `claude`, `codex`, `gemini`, `node`, `uv` on PATH | `Dockerfile:62-68,142-150` | done: `agent_cli.py:13-17` uses bare command names, PATH lookup; host has claude 2.1.303, codex 0.155.1, gemini 0.37.1, uv 0.9.17 | check and warn (`command -v`) |
| 15 | `GEMINI_CLI_TRUST_WORKSPACE=true` | `Dockerfile:185` (only place) | missing natively; `agent_cli.py:85-87` adds `--skip-trust` which may suffice | export it in host mode |
| 16 | Credential mounts `~/.claude`, `~/.codex` (ro -> `CODEX_HOME` copy), `~/.gemini`, `~/.modal.toml`, `CLAUDE_CONFIG_DIR` | `run.sh:211-302`, `entrypoint.sh:38-53` | not needed: all are uid-1000 workarounds; natively the CLIs read `$HOME` directly | nothing; must NOT run `ensure_directories` chmods (`run.sh:356-357`), `scripts/keep_credentials_readable.sh`, or `daemon._make_readable` (`daemon.py:548-557`, harmless) |
| 17 | `umask 000`, world-writable outputs | `entrypoint.sh:14` | not needed; native files are owned by the user. Mixed use (Docker resumes a host-created workspace) needs `a+rwX` | document; optional `umask 002` |
| 18 | Git credentials + `gh auth login` from `GITHUB_TOKEN` | `entrypoint.sh:117-137` | done for the pipeline: `github_manager.py:74,403` embeds the token in the push URL; agent env strips the token anyway (`agent_cli.py:110`) | optional: `gh auth login --with-token` if `gh` present; otherwise nothing |
| 19 | GPU: `--gpus all` / `--gpus device=$NEURICO_GPUS` | `run.sh:191-208` | partial: `daemon.py:196-198` sets both `NEURICO_GPUS` and `CUDA_VISIBLE_DEVICES`; `scripts/run_methods.py:255-256` sets only `NEURICO_GPUS` | launcher: `[ -n "$NEURICO_GPUS" ] && export CUDA_VISIBLE_DEVICES=$NEURICO_GPUS`. Caveat: `nvidia-smi` ignores it, so agents following `templates/agents/session_instructions.txt:91` list every GPU |
| 20 | GPU listing / version / env check banner (plus the new Azure status line, `NEURICO_AZURE=1` + `AZURE_OPENAI_API_KEY`, `entrypoint.sh:160-163`, env-only) | `entrypoint.sh:72-163` | missing | port `show_version`, `validate_env`, `check_gpu` and the Azure line (~45 lines bash) |
| 21 | Container name `NEURICO_CONTAINER_NAME`, `docker kill` | `run.sh:921,1013`; `src/safety/daemon.py:325`; `scripts/run_methods.py:260,404`; `scripts/batch_status.sh:19-36`, `batch_watch.sh:11-15` | partial: daemon spawns with `start_new_session=True` and `os.killpg` (`daemon.py:260,328-336`) so the group kill already works; but `subprocess.run(["docker","kill",...])` raises `FileNotFoundError` when `docker` is absent (not caught). `run_methods.py:267` has no new session and `stop()` only `terminate()`s the bash wrapper, orphaning `python`/agent children | daemon: guard with `shutil.which("docker")`; run_methods: `start_new_session=True` + `killpg`; launcher writes `logs/host-jobs/<name>.pid` so status scripts can list jobs |
| 22 | Skills copied to workspace | done in Python: `runner.py:1768-1824` from `project_root/templates/skills` | done | nothing |
| 23 | `--model` forwarding | `run.sh:755-760,836-839` (submit/run); `runner.py:2260-2262` -> `NEURICO_AGENT_MODEL` (`agent_cli.py:26,41-54`) | done | pass args through unchanged |
| 24 | `baseline` command | `run.sh:991-1040` -> `baseline/zero_shot.py /input/<idea>` | done: `zero_shot.py:36-37,482-486` | `python baseline/zero_shot.py <abs idea> "$@"` |
| 25 | HITL web port publish `127.0.0.1:PORT`, `NEURICO_HITL_WEB_HOST=0.0.0.0`, `NEURICO_HITL_WEB_CONTAINER_MODE=1`, `NEURICO_HITL_BROWSER_URL` | `run.sh:905-912`, `:2362-2370` | done: `hitl_web.py:35-41` and `hitl_manager_host.py:1572-1577` default to loopback when the vars are unset | do not set those three vars; honour `--port`/`--hitl-manager-port` only |
| 26 | HITL launch handoff watcher (`NEURICO_HITL_DOCKER_HANDOFF=1`, polls `.neurico/hitl-launch-requests`, `docker run -d`) | `run.sh:2219-2328,2354,2397-2399` | done: without the var `hitl_launcher.py:236-253` spawns `hitl_run_worker.py` natively with `sys.executable` and `start_new_session=True`; worker loads `.env` (`hitl_run_worker.py:42-49`) and checks the checkout (`:125-127`) | run `hitl_web.py`/`hitl_cli.py` directly; no watcher |
| 27 | `hitl-stop` | `run.sh:2432-2449` | done: `hitl_stop.py:10-11` | `python src/cli/hitl_stop.py "$@"` |
| 28 | `_run-agent` (interactive manager) | `run.sh:2024-2069`; manager already runs on host (`run.sh:2074-2102`) | partial: `src/interactive/tools.py:105-121` rewrites host paths to `/workspaces/...` and `/app/...` before calling `./neurico _run-agent`; `agent_runner.py:790-792` then fails natively | `tools.py`: skip translation when `NEURICO_MODE=host` (or `_run-agent` host branch maps `/workspaces/x` -> `$workspace_dir/x`, `/app/rel` -> `$PROJECT_ROOT/rel`) |
| 29 | `login` (shell in container) | `run.sh:1106-1149`, `setup_login_provider:1453-1517` | n/a | run `claude` / `codex login` / `gemini` directly |
| 30 | `setup`, `config`, `update`, `build`, `update-tools`, `up/down/logs`, `shell` | `run.sh:1151-1238,1518-1560,381-452,1044-1083,1085-1103,520-550` | `config` is already Docker-free; `check_prerequisites:1151-1189` exits without docker | host variants: setup skips image steps; update = `git pull` + `uv sync`; build = `uv sync` + paper-finder sync; update-tools = installers; shell = `bash` with env loaded |
| 31 | Python 3.12 (uv-managed), `.venv` baked | `Dockerfile:58,76-78` | host `.venv` is 3.10 (`pyproject.toml:6` allows >=3.10); `uv run --no-sync python -c 'import dotenv, httpx, yaml, github'` works | recommend `uv sync --python 3.12` for parity; call `.venv/bin/python` (or `uv run --frozen`) to avoid concurrent auto-sync races between parallel jobs |
| 32 | Output parsing of `/workspaces/<name>` | `scripts/results_manifest.py:49` (regex `Local: /workspaces/`), `src/safety/ingest.py:26-35` (handles both) | ingest fine; manifest regex misses host paths (falls back to `Generated repo name:`) | widen regex to `Local: (\S+)` and take `basename` |

## 2. Where the Python entrypoints locate things (item 3 of the brief)

- `src/core/runner.py:35-38` sets `_SRC_ROOT`/`_PROJECT_ROOT` from `__file__`; `ResearchRunner` default `project_root` at `:299-301`; templates at `self.project_root / "templates"` (`:999,1061,1082,1141,1224,1668`); skills copied at `:1777`.
- `src/cli/submit.py:15-24` same pattern (`sys.path`, `.env.local` then `.env`); schema/examples resolved relative to the file in `submit_local.py:244-249,472` and `fetch_from_ideahub.py:267-272,478`.
- `src/core/config_loader.py:29-30` project root and `config/`; workspace parent: `NEURICO_WORKSPACE` env > `workspace.yaml` > `workspaces/` (`:253-270`). `docker/run.sh:305-328` and `scripts/run_methods.py:466-475` re-implement the same rule in bash/regex.
- `src/core/research_environment.py` is workspace-relative only (no absolute paths; `:196-233`).
- `src/core/agent_cli.py:13-17` bare CLI names (PATH); `build_agent_environment` copies `os.environ` (`:99-111`).
- `src/core/pipeline_orchestrator.py:394-395` templates from `__file__`; no Docker, GPU or LaTeX references.
- paper-finder skill: `templates/skills/paper-finder/scripts/find_papers.py:23,114` hard-codes `http://localhost:8000/api/2/rounds` (overridable `--url`, never passed by `SKILL.md:21-37`).
- Remaining literal container paths: `src/interactive/tools.py:111,121` (`/workspaces`, `/app`), `src/core/agent_runner.py:792` (message only), `templates/skills/safety-evals/scripts/_common.py:14`, `run_eval.py:70`, `src/safety/ingest.py:26` (docstring; code handles both), `scripts/results_manifest.py:49`. No `localhost:8000` outside the skill and `config/paper_finder.md:44,75`.

## 3. What the safety daemon needs to launch natively (item 4)

`src/safety/daemon.py` already runs on the host and only shells out to `./neurico` (`:38,163-177`), so with a host-mode launcher it needs:

1. `kill_job` (`:321-336`): `docker kill` raises `FileNotFoundError` without a docker binary; wrap in `if rt.container and shutil.which("docker")` (or skip when `os.environ.get("NEURICO_MODE") == "host"`). The `os.killpg(SIGTERM)` fallback already kills the whole tree because `spawn` uses `start_new_session=True` (`:260`). Consider `SIGKILL` after a grace period, since a stalled `claude` process may ignore `SIGTERM`.
2. `spawn` (`:191-207`): already exports `NEURICO_SAFETY_KB`, `HF_HOME`, `NEURICO_GPUS`, `CUDA_VISIBLE_DEVICES`, `NEURICO_HF_CACHE`, `NEURICO_SAFETY_VENV`, `NEURICO_CONTAINER_NAME`. Add `NEURICO_MODE=host` passthrough (inherited from `os.environ.copy()` at `:192`, so nothing to add if the daemon is started with it).
3. `_make_readable` (`:548-557`) and the `uid 1000` comment at `:291` become no-ops; harmless.
4. `adopt`/`_pid_alive` (`:453-462,560-567`) are pid based: unchanged. `record_outputs` regex (`:280-287`) accepts host paths.
5. `docs/SAFETY_ENGINE.md:40-47` ("Host requirements") must drop the "interpreter readable by uid 1000" and "Docker route with the local image" lines for host mode.
6. `eval_python` / `hf_cache` defaults (`daemon.py:55-56`, `src/cli/safety.py:32-33`, `src/safety/suites.py:226`) are absolute `/data/hypogenicai/...` paths; on another server they need `safety_kb/engine.yaml` overrides (already supported).

`scripts/run_methods.py` (same pattern, `:251-274,397-405`) needs `start_new_session=True` and `os.killpg` instead of `docker kill` + `terminate()`; `scripts/batch_status.sh:19-36` and `batch_watch.sh:11-15` enumerate `docker ps` and need a pid-file listing in host mode.

## 4. Existing partial support (item 6)

- `cmd_interactive` already runs the manager natively (`run.sh:2074-2102`) and `src/interactive/manager.py:36,193` honours `NEURICO_PROJECT_ROOT` / `NEURICO_WORKSPACE_DIR`.
- HITL launcher has a native branch when `NEURICO_HITL_DOCKER_HANDOFF` is unset (`src/cli/hitl_launcher.py:236-253`); web binding is loopback by default (`hitl_web.py:35-41`).
- `submit_local.py:732-745` distinguishes `NEURICO_IN_DOCKER` / `/.dockerenv`.
- Safety skill honours `NEURICO_SRC` and `NEURICO_ENV_FILE` (`_common.py:12`, `run_eval.py:70`).
- `src/safety/planner.py:140-167` runs the planner agent natively via `run_prebuilt_cli_agent`; suites run with the host venv (`daemon.py:179-185`).
- README documents the "Local `uv` (native)" column for submit/run/hitl (`README.md:81-88,109-125,231-235`), and `config/paper_finder.md:30-44,75` documents native paper-finder start.
- No `NEURICO_MODE`, `NEURICO_LOCAL`, `host mode` or `no-docker` strings exist anywhere in `docker/`, `src/`, `docs/`; git history has no host-mode work (only "native HITL terminal rendering", 4ad42bb).

## 5. Proposed minimal design: one switch

### Switch

- `NEURICO_MODE=host` env var is the single source of truth; `./neurico --host <cmd>` strips the flag and sets it; `./neurico-host` is a 3-line wrapper (`NEURICO_MODE=host exec "$dir/docker/run.sh" "$@"`). `NEURICO_MODE` defaults to `docker`, so nothing changes for existing users. The daemon and `run_methods.py` inherit it from the environment and pass it to the launcher unchanged.

### Changes in `docker/run.sh` (approx. 300-350 lines added, no existing lines removed)

| Function | Purpose | Size |
|---|---|---|
| dispatch block (`:2500-2511`) | parse `--host`; `is_host_mode()`; skip `check_docker` in host mode; route to `host_dispatch` | ~15 |
| `host_python()` | `$PROJECT_ROOT/.venv/bin/python` if present, else `uv run --frozen python`; error if neither | ~10 |
| `host_load_env()` | `set -a; . .env.local` or `.env`; `set +a`; export `NEURICO_MODE=host`, `NEURICO_PROJECT_ROOT`, `NEURICO_SRC`, `NEURICO_ENV_FILE`, `NEURICO_WORKSPACE=$(get_workspace_dir)`, `NEURICO_WORKSPACE_DIR`, `PYTHONUNBUFFERED=1`, `GEMINI_CLI_TRUST_WORKSPACE=true`; `HF_HOME` from `NEURICO_HF_CACHE`; `CUDA_VISIBLE_DEVICES` from `NEURICO_GPUS`; `mkdir -p` workspace/logs/ideas (the non-chmod half of `ensure_directories`) | ~35 |
| `host_check_env()` | port of `entrypoint.sh` `show_version`, `validate_env`, `check_gpu` plus `command -v` for `claude codex gemini uv node pdflatex bibtex git curl`; warnings only, never exit | ~45 |
| `host_paper_finder_start()` / `_stop()` / `_status()` | if `S2_API_KEY` and an LLM key: `curl localhost:8000/health` -> reuse; else `(cd services/paper-finder/agents/mabool/api && nohup uv run sh dev.sh >> logs/paper-finder.log 2>&1 & echo $! > logs/paper-finder.pid)`; wait up to 60 s; new subcommand `paper-finder start|stop|status`. Leave the service running between jobs (shared, port 8000 is fixed in `dev.sh`) | ~60 |
| `host_run()` | run `<python> <script> args...` in its own session (`setsid`), write `logs/host-jobs/${NEURICO_CONTAINER_NAME:-$$}.pid`, trap `INT TERM` and `kill -- -$pid` so a signal to the launcher kills the whole tree like `docker kill` did; remove the pid file on exit; propagate exit status | ~35 |
| `host_dispatch()` | `case` over every action: `submit`, `submit-local` (reuse existing flag parsing by factoring the arg-parse loops out of `cmd_submit`/`cmd_submit_local`, then call `host_run src/cli/submit*.py "$idea_abs" ...`; keep `--run` -> `cmd_run`), `run` (`host_run src/core/runner.py "$@"`, HITL web vars not set), `baseline`, `fetch`, `hitl-web`, `hitl-cli`, `hitl-stop`, `_run-agent` (map `/workspaces/` and `/app/` prefixes), `interactive` (existing), `login` (exec the CLI), `shell` (`bash`), `setup` (skip `check_prerequisites` docker lines and `check_image`), `config` (existing), `update` (`git pull` + `uv sync --frozen`), `build` (`uv sync --frozen`; `cd services/paper-finder && uv python install 3.12 && uv sync --all-packages --dev`), `update-tools` (`claude.ai/install.sh`, `npm i -g`), `help`; `up/down/logs` print "Docker only" | ~120 |
| `show_status()` | add a "Mode: host" line and host tool status | ~15 |

### Python / script changes (approx. 40 lines)

| File | Change | Size |
|---|---|---|
| `src/safety/daemon.py:321-326` | guard `docker kill` with `shutil.which("docker")` / `NEURICO_MODE != "host"`; optional `SIGKILL` escalation | ~8 |
| `scripts/run_methods.py:267,397-405` | `start_new_session=True`; `stop()` uses `os.killpg` and skips `docker kill` in host mode | ~8 |
| `src/interactive/tools.py:105-121` | no container-path translation when `NEURICO_MODE == "host"` | ~6 |
| `src/core/agent_runner.py:790-792` | neutral error message | ~2 |
| `scripts/results_manifest.py:49` | regex `Local: (\S+)` + basename | ~2 |
| `scripts/batch_status.sh`, `batch_watch.sh` | list `logs/host-jobs/*.pid` when docker is absent | ~15 (optional) |
| `scripts/keep_credentials_readable.sh` | exit immediately when `NEURICO_MODE=host` (do not chmod 666 credentials) | ~2 |
| `README.md`, `docs/SAFETY_ENGINE.md:40-47`, `config/paper_finder.md` | document `./neurico --host` as the third column instead of raw `uv run` lines | docs |

### Blockers and risks

1. `docker/run.sh:161-167,2509-2511`: hard exit without docker; trivial but mandatory.
2. paper-finder: no host venv (`services/paper-finder/.venv` absent), needs uv-managed Python >= 3.12.8, a fixed port 8000, and `make sync-dev`-level dependencies (pulls torch-free but large deps). One shared instance per host serves all concurrent jobs (Docker gave one per container). Without it agents fall back to manual search (`find_papers.py:47-52`), so it is degradation, not failure.
3. texlive: cannot be installed without root; the paper stage then leaves `main.tex` without `main.pdf`. Mitigation: TinyTeX or `tectonic` in `~/.local/bin` (both user-installable), and `host_check_env` warning.
4. Process-kill semantics: `docker kill` was unconditional; natively everything depends on process groups. Daemon is fine (`daemon.py:260,328`), `run_methods.py` is not; a `claude`/`codex` child that ignores `SIGTERM` needs `SIGKILL` escalation (`agent_runner.py:403-437` already does this for agents it owns).
5. Permissions: Docker produced uid-1000, mode-777 trees under `/data/hypogenicai/workspaces`; host mode writes as the real user with the normal umask. Resuming a Docker-created workspace natively works (777); resuming a host-created workspace in Docker later requires `chmod -R a+rwX` (slow on large trees, `run.sh:343-346`). Do not run the credential chmods (`run.sh:356-357`) or `keep_credentials_readable.sh` in host mode.
6. GPU pinning: `CUDA_VISIBLE_DEVICES` is honoured by torch/vLLM but not by `nvidia-smi`; agents instructed at `templates/agents/session_instructions.txt:91` will see all GPUs and may pick a busy one. Docker's `--gpus device=` hid them. Option: a `nvidia-smi` shim on PATH that passes `-i $CUDA_VISIBLE_DEVICES`, or a prompt note.
7. Python parity: host `.venv` is 3.10 (Docker 3.12). `uv sync --python 3.12` fixes it; `uv run` auto-sync must be avoided for parallel jobs (`--frozen`/`--no-sync` or direct `.venv/bin/python`).
8. CLI versions drift between host and image (`update-tools` is a `docker commit`); on the host they are whatever the user installed, and Codex/Gemini need Node (image: 22; this host: 20 works).
9. Port conflicts: HITL web default 7890 per idea (same as Docker, now without the `-p` publish guard); vLLM judge ports in `src/safety/serving.py` unchanged.
10. `_run-agent`/interactive path mapping (`tools.py:105-121`) is the only place where Docker paths are generated in Python; forgetting it breaks interactive mode in host mode silently.

## 6. Prioritised implementation list

1. `run.sh`: `--host`/`NEURICO_MODE` switch, skip `check_docker`, `host_python`, `host_load_env`, `host_run`, `host_dispatch` for `submit`, `run`, `baseline`, `hitl-stop`, `fetch`, `submit-local` (unblocks the batch tools and the daemon).
2. `daemon.py` docker-kill guard; `run_methods.py` process-group kill; `keep_credentials_readable.sh` guard.
3. `host_check_env` + `host_paper_finder_*` + `build` (paper-finder venv) + `paper-finder` subcommand.
4. `hitl-web`, `hitl-cli`, `_run-agent` + `tools.py` guard, `login`, `shell`, `setup`/`update`/`update-tools` host branches, `show_status`.
5. `results_manifest.py` regex, `batch_status.sh`/`batch_watch.sh` pid listing, docs (README third column, SAFETY_ENGINE host requirements, paper_finder.md).
6. Optional parity items: `uv sync --python 3.12`, `nvidia-smi` shim, TinyTeX/tectonic bootstrap in `build`.
