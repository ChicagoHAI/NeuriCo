# NeuriCo Workflow Guide

NeuriCo has one user journey and two supported execution routes:

1. set up NeuriCo;
2. write and submit an idea;
3. run the idea in Standard, AutoResearch, or HITL AutoResearch mode.

Docker and local `uv` are equal routes. Docker commands begin with
`./neurico`; local commands run the corresponding Python entrypoint with
`uv run python`. Do not mix the two command columns within one run.

## 1. Set up NeuriCo

### Docker route

Prerequisites: Git and a running Docker installation.

```bash
git clone https://github.com/ChicagoHAI/neurico.git
cd neurico
./neurico setup --quick
```

Quick setup pulls the current image, creates minimal configuration, and guides
you through Claude OAuth login. Run `./neurico setup` instead when you want to
choose Codex or Gemini during setup, configure GitHub, add API keys, or change
the workspace location.

You can change configuration later:

```bash
./neurico config
./neurico login
./neurico update
```

The repository is still required with the prebuilt image. It supplies the
`./neurico` launcher, idea records, configuration, and templates. The launcher
mounts those files and the configured workspace into each container.

### Local `uv` route

Prerequisites: Git, [`uv`](https://docs.astral.sh/uv/), and one locally installed
provider CLI.

```bash
git clone https://github.com/ChicagoHAI/neurico.git
cd neurico
uv sync
cp .env.example .env
claude  # or: codex, gemini
```

The final command performs provider OAuth login. Edit `.env` only for optional
integrations such as GitHub, IdeaHub conversion, or paper-finder.

### Optional configuration shared by both routes

- `.env` stores optional GitHub and service credentials.
- `config/workspace.yaml` selects the workspace parent directory.
- `templates/` controls agent instructions and skills.

GitHub is not required. Use `--no-github` during submission and execution for a
fully local research workspace.

## 2. Write and submit an idea

### Write the idea

Create `ideas/my_experiment.yaml`. Only a title, domain, and testable hypothesis
are needed:

```yaml
idea:
  title: "Impact of chain-of-thought on math reasoning"
  domain: artificial_intelligence
  hypothesis: >
    Chain-of-thought prompting improves accuracy on multi-step math problems
    compared with direct prompting.
```

Optional sections can provide papers, datasets, methods, constraints, expected
outputs, local resources, and evaluation metrics. See
[`../ideas/schema.yaml`](../ideas/schema.yaml) and
[`../ideas/examples/`](../ideas/examples/). For guided authoring, use the
[`Idea Quickstart`](IDEA_QUICKSTART.md) or the complete
[`Idea Guide`](IDEA_GUIDE.md).

### Submit the idea

The following commands do not require GitHub:

| Docker | Local `uv` |
| --- | --- |
| `./neurico submit ideas/my_experiment.yaml --no-github` | `uv run python src/cli/submit.py ideas/my_experiment.yaml --no-github` |

Submission validates the idea, assigns an idea ID, records it under `ideas/`,
and prepares its workspace. Keep the printed `<idea_id>`.

To use GitHub, set `GITHUB_TOKEN` in `.env` and omit `--no-github`. Submission
then creates or connects the research repository and prepares its local clone.

### Alternative input: IdeaHub

| Docker | Local `uv` |
| --- | --- |
| `./neurico fetch <ideahub_url> --submit --no-github` | `uv run python src/cli/fetch_from_ideahub.py <ideahub_url> --submit --no-github` |

### Alternative input: Markdown or text

| Docker | Local `uv` |
| --- | --- |
| `./neurico submit-local idea.md --submit --no-github` | `uv run python src/cli/submit_local.py idea.md --submit --no-github` |

Use the local-file route when the idea refers to datasets or functions already
on your machine. Declare those paths in the idea so NeuriCo can validate and
stage them. See [`LOCAL_IDEA_SUBMISSION.md`](LOCAL_IDEA_SUBMISSION.md).

## 3. Choose a research mode

### Standard

Standard mode runs the multi-agent research pipeline once.

| Docker | Local `uv` |
| --- | --- |
| `./neurico run <idea_id> --provider claude --no-github --full-permissions` | `uv run python src/core/runner.py <idea_id> --provider claude --no-github --full-permissions` |

Use it when one complete pass is sufficient or when you want to inspect a
baseline before starting iterative work.

### AutoResearch

AutoResearch builds and scores a baseline, then proposes, executes, scores, and
accepts or rejects iterative improvements.

| Docker | Local `uv` |
| --- | --- |
| `./neurico run <idea_id> --provider claude --no-github --full-permissions --autoresearch --autoresearch-iterations 3` | `uv run python src/core/runner.py <idea_id> --provider claude --no-github --full-permissions --autoresearch --autoresearch-iterations 3` |

To continue an already scored workspace:

| Docker | Local `uv` |
| --- | --- |
| `./neurico run <idea_id> --provider claude --no-github --full-permissions --continue-autoresearch --autoresearch-iterations 3` | `uv run python src/core/runner.py <idea_id> --provider claude --no-github --full-permissions --continue-autoresearch --autoresearch-iterations 3` |

To convert an existing unscored Standard workspace into a continuation-ready
AutoResearch baseline, run `--bootstrap-autoresearch-baseline`, then use the
continuation command above:

| Docker | Local `uv` |
| --- | --- |
| `./neurico run <idea_id> --provider claude --no-github --bootstrap-autoresearch-baseline` | `uv run python src/core/runner.py <idea_id> --provider claude --no-github --bootstrap-autoresearch-baseline` |

See [`AUTORESEARCH.md`](AUTORESEARCH.md) for scoring, checkpoints, recovery, and
bootstrap behavior.

### HITL AutoResearch

HITL AutoResearch has two interfaces backed by the same durable manager and
workspace state. Starting either interface does not immediately start the
research run; enter `/run` in the interface to configure and launch it.

#### Web interface

| Docker | Local `uv` |
| --- | --- |
| `./neurico hitl-web <idea_id>` | `uv run python src/cli/hitl_web.py <idea_id>` |

The default page is `http://localhost:7890`. The printed bootstrap URL includes
the session token. To choose another port:

| Docker | Local `uv` |
| --- | --- |
| `./neurico hitl-web <idea_id> --port 8123` | `uv run python src/cli/hitl_web.py <idea_id> --port 8123` |

The Docker route runs the manager inside the container and publishes the port
only to `127.0.0.1` on the host.

#### Terminal interface

| Docker | Local `uv` |
| --- | --- |
| `./neurico hitl-cli <idea_id>` | `uv run python src/cli/hitl_cli.py <idea_id>` |

Useful terminal commands:

| Command | Purpose |
| --- | --- |
| `/run` | Configure and start a fresh or continuing HITL run |
| `/reply <number>` | Choose an option for the active human request |
| `/reply <feedback>` | Resolve the request with free-form feedback |
| `/help` | Show available commands |
| `/quit` | Close the terminal client |

NeuriCo detects existing HITL frontier state and chooses fresh or continue
behavior automatically. See [`HITL_AUTORESEARCH.md`](HITL_AUTORESEARCH.md) for
the manager, human, worker, frontier, and recovery model.

## Review the results

Workspaces live under the parent configured in `config/workspace.yaml` (default:
`workspaces/`). Typical artifacts include:

```text
workspaces/<research-workspace>/
├── README.md
├── REPORT.md
├── STATE.md
├── results/
├── logs/
├── artifacts/
├── scoring/
└── paper_draft/
```

AutoResearch attempt history is stored under
`logs/experiment-autoresearch/`. HITL control state is stored under
`.neurico/hitl/` inside the workspace. GitHub-enabled runs can also publish the
research artifacts to their connected repository.

## Common decisions

| Situation | Choice |
| --- | --- |
| No GitHub token | Add `--no-github` to submission and run commands |
| Use Codex or Gemini | Replace `--provider claude` with `codex` or `gemini` and log in to that CLI |
| Write a paper | Add `--write-paper` and optionally `--paper-style neurips\|icml\|acl` |
| Run without unrestricted provider permissions | Omit `--full-permissions` |
| Continue ordinary AutoResearch | Use `--continue-autoresearch` |
| Continue HITL AutoResearch | Reopen `hitl-web` or `hitl-cli`, then use `/run`; continuation is detected automatically |

Run help for the route you selected:

```bash
# Docker
./neurico help

# Local uv
uv run python src/core/runner.py --help
```
