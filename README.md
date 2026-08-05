<div align="center">

<img src="assets/banner.png" alt="NeuriCo - AI-Powered Research Acceleration" width="600"/>

[![GitHub Stars](https://img.shields.io/github/stars/ChicagoHAI/neurico?style=flat-square)](https://github.com/ChicagoHAI/neurico)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg?style=flat-square)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](docker/)
[![License](https://img.shields.io/badge/License-Apache%202.0-green.svg?style=flat-square)](LICENSE)
[![Discord](https://img.shields.io/badge/Discord-Join-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/n65caV7NhC)

</div>

<!-- agent-summary: NeuriCo is an autonomous and human-in-the-loop research framework. Users choose either Docker through ./neurico or a local uv installation, submit a structured research idea, then run Standard, AutoResearch, or HITL AutoResearch. Providers: Claude Code, Codex, Gemini. License: Apache 2.0. -->

**NeuriCo** (**Neur**al **Co**-Scientist, inspired by Enrico Fermi) turns a
structured research idea into experiments, results, documentation, and an
optional paper. It supports Claude Code, Codex, and Gemini.

NeuriCo has three user-facing research modes:

| Mode | What it does |
| --- | --- |
| **Standard** | Runs the research pipeline once |
| **AutoResearch** | Scores a baseline, then iteratively proposes and keeps improvements |
| **HITL AutoResearch** | Adds a durable manager, human decisions, and a retained research frontier |

## Start here

There are two supported ways to run NeuriCo. They provide the same research
modes, but their commands are intentionally different:

| Docker route | Local `uv` route |
| --- | --- |
| Runs NeuriCo and provider CLIs in containers | Runs NeuriCo and provider CLIs on your machine |
| Use commands beginning with `./neurico` | Use commands beginning with `uv run python` |
| Requires Git and Docker | Requires Git, `uv`, and a locally installed provider CLI |

Choose one route and stay in that route's command column.

### 1. Set up NeuriCo

#### Docker

Make sure Docker is installed and running, then:

```bash
git clone https://github.com/ChicagoHAI/neurico.git
cd neurico
./neurico setup --quick
```

Quick setup pulls the current image, creates the minimal configuration, and
guides you through Claude login. To configure Codex, Gemini, GitHub, API keys,
or a custom workspace during setup, use `./neurico setup` and select full
setup instead.

The one-line installer is an equivalent Docker shortcut:

```bash
curl -fsSL https://raw.githubusercontent.com/ChicagoHAI/neurico/main/install.sh | bash
```

#### Local `uv`

Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/) and one
provider CLI ([Claude Code](https://docs.anthropic.com/en/docs/claude-code),
[Codex](https://github.com/openai/codex), or
[Gemini CLI](https://github.com/google-gemini/gemini-cli)), then:

```bash
git clone https://github.com/ChicagoHAI/neurico.git
cd neurico
uv sync
cp .env.example .env
claude  # or: codex, gemini
```

The final command performs the provider's OAuth login on your machine. API keys
in `.env` are optional for the basic local-only workflow.

### 2. Write and submit an idea

Start with an example or create `ideas/my_idea.yaml` using this minimal
structure:

```yaml
idea:
  title: "Do LLMs distinguish causation from correlation?"
  domain: artificial_intelligence
  hypothesis: "Explicit causal prompts improve causal-reasoning accuracy."
```

Submit it and keep the printed `<idea_id>` for the next step. The commands below
use `--no-github`, so no GitHub token is required.

| Docker | Local `uv` |
| --- | --- |
| `./neurico submit ideas/my_idea.yaml --no-github` | `uv run python src/cli/submit.py ideas/my_idea.yaml --no-github` |

The provider is selected when you start the research mode. See
[`ideas/examples/`](ideas/examples/) and [`ideas/schema.yaml`](ideas/schema.yaml)
for larger idea specifications.

### 3. Choose a research mode

Replace `<idea_id>` with the ID printed during submission.

| Mode | Docker | Local `uv` |
| --- | --- | --- |
| **Standard** | `./neurico run <idea_id> --provider claude --no-github --full-permissions` | `uv run python src/core/runner.py <idea_id> --provider claude --no-github --full-permissions` |
| **AutoResearch** | `./neurico run <idea_id> --provider claude --no-github --full-permissions --autoresearch --autoresearch-iterations 3` | `uv run python src/core/runner.py <idea_id> --provider claude --no-github --full-permissions --autoresearch --autoresearch-iterations 3` |
| **HITL AutoResearch — web** | `./neurico hitl-web <idea_id>` | `uv run python src/cli/hitl_web.py <idea_id>` |
| **HITL AutoResearch — terminal** | `./neurico hitl-cli <idea_id>` | `uv run python src/cli/hitl_cli.py <idea_id>` |

The web and terminal commands are two interfaces for the same HITL AutoResearch
mode. In either interface, start the research run with `/run`; NeuriCo detects
whether the workspace needs a fresh run or a continuation.

The Docker web command publishes the selected port only on host loopback. The
default is `http://localhost:7890`; choose another port with:

```bash
./neurico hitl-web <idea_id> --port 8123
```

The local equivalent is:

```bash
uv run python src/cli/hitl_web.py <idea_id> --port 8123
```

## Other ways to provide an idea

### IdeaHub

| Docker | Local `uv` |
| --- | --- |
| `./neurico fetch <ideahub_url> --submit --no-github` | `uv run python src/cli/fetch_from_ideahub.py <ideahub_url> --submit --no-github` |

### Markdown or text file

| Docker | Local `uv` |
| --- | --- |
| `./neurico submit-local idea.md --submit --no-github` | `uv run python src/cli/submit_local.py idea.md --submit --no-github` |

Declared local datasets and functions are recorded during submission and staged
into the research workspace. Docker mounts only those declared host paths and
mounts them read-only. See
[`docs/LOCAL_IDEA_SUBMISSION.md`](docs/LOCAL_IDEA_SUBMISSION.md).

## Configuration

### Provider authentication

Provider CLIs use OAuth rather than API keys.

- **Docker:** credentials created by the setup or login flow are persisted on
  the host and mounted into each container.
- **Local `uv`:** run `claude`, `codex`, or `gemini` on the host and complete
  that CLI's login flow.

### GitHub integration

GitHub is optional. The starter commands use `--no-github`. To create and push
research repositories automatically, add a classic GitHub token with `repo`
scope to `.env`:

```dotenv
GITHUB_TOKEN=your_token
GITHUB_ORG=
```

Then omit `--no-github`. See
[`docs/GITHUB_INTEGRATION.md`](docs/GITHUB_INTEGRATION.md).

### Optional API keys

These enhance specific features but are not required for the basic workflow:

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | IdeaHub conversion, repository naming, and paper-finder |
| `S2_API_KEY` | Semantic Scholar literature search |
| `COHERE_API_KEY` | Paper-finder reranking |
| `OPENROUTER_KEY` | OpenRouter access during experiments |
| `HF_TOKEN` | Private Hugging Face models or datasets |
| `WANDB_API_KEY` | Weights & Biases tracking |

Docker users can edit these with `./neurico config` or edit `.env` directly.
Local users edit `.env` directly.

### Workspace location

Research workspaces default to `workspaces/`. To choose another location, copy
`config/workspace.yaml.example` to `config/workspace.yaml` and change
`parent_dir`:

```yaml
workspace:
  parent_dir: "/path/to/your/workspaces"
  auto_create: true
```

The same workspace configuration is used by Docker and local `uv`. Docker
mounts the configured directory at `/workspaces` inside the container.

## Continuing AutoResearch

Continue a workspace that already has a scored best result:

| Docker | Local `uv` |
| --- | --- |
| `./neurico run <idea_id> --provider claude --no-github --full-permissions --continue-autoresearch --autoresearch-iterations 3` | `uv run python src/core/runner.py <idea_id> --provider claude --no-github --full-permissions --continue-autoresearch --autoresearch-iterations 3` |

See [`docs/AUTORESEARCH.md`](docs/AUTORESEARCH.md) for recovery, bootstrap, and
scoring details.

## Outputs

Each submitted idea receives a workspace under the configured workspace root.
A completed run can contain:

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

The exact artifacts depend on the selected mode and flags such as
`--write-paper`.

## ClawHub distribution

This repository includes a packaged [ClawHub skill](clawskill/SKILL.md) for
people who discover NeuriCo through ClawHub. The skill is a discovery and
onboarding layer, not a third execution route. After obtaining NeuriCo through
ClawHub, choose either the Docker or local `uv` route above and use Standard,
AutoResearch, or HITL AutoResearch.

## Documentation

The links below are the supported user documentation:

- [`docs/WORKFLOW.md`](docs/WORKFLOW.md) — the complete setup, submission, and mode workflow
- [`docs/AUTORESEARCH.md`](docs/AUTORESEARCH.md) — scoring and iterative AutoResearch
- [`docs/HITL_AUTORESEARCH.md`](docs/HITL_AUTORESEARCH.md) — HITL manager, human decisions, frontier, and recovery
- [`docs/LOCAL_IDEA_SUBMISSION.md`](docs/LOCAL_IDEA_SUBMISSION.md) — local data, functions, and evaluation contracts
- [`docs/IDEAHUB_INTEGRATION.md`](docs/IDEAHUB_INTEGRATION.md) — importing IdeaHub ideas
- [`docs/GITHUB_INTEGRATION.md`](docs/GITHUB_INTEGRATION.md) — optional repository creation and publishing

See the [documentation index](docs/README.md) for developer, internal, and
legacy documents. Those documents are not required for setup or normal use.

## Citation

```bibtex
@software{neurico_2025,
  title={NeuriCo: Autonomous Research Framework},
  author={Haokun Liu, Chenhao Tan},
  year={2025},
  url={https://github.com/ChicagoHAI/neurico}
}
```

## License

Apache 2.0. See [`LICENSE`](LICENSE).

For questions and feedback, [open an issue](https://github.com/ChicagoHAI/neurico/issues)
or join the [NeuriCo Discord](https://discord.gg/BgkfTvBdbV).
