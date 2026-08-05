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
./neurico setup
```

The setup wizard checks Docker, prepares the current image, and asks whether to
use quick or full setup. Quick setup creates the minimal configuration and
guides you through Claude login. Full setup can also configure Codex, Gemini,
GitHub, API keys, and a custom workspace.

Use `./neurico setup --quick` only when the quick path should be selected
without showing the choice.

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

### 2. Prepare and submit an idea

Submission records and validates the research idea; it does not choose or start
a research mode. After submission, NeuriCo prints an `<idea_id>` used by
Standard, AutoResearch, or HITL AutoResearch.

Choose one of the following input methods.

#### A. Write a YAML idea

Both Docker and local `uv` accept relative or absolute paths visible to the
host. Keeping project ideas under `ideas/` is recommended for organization,
but it is not required.

Only three fields are required:

```yaml
# ideas/my_idea.yaml
idea:
  title: "Do LLMs distinguish causation from correlation?"
  domain: artificial_intelligence
  hypothesis: >
    Explicit causal prompts improve causal-reasoning accuracy compared with
    otherwise equivalent direct prompts.
```

A useful idea can also specify information NeuriCo should preserve rather than
discover independently:

| Section | Use it for |
| --- | --- |
| `max_directions` | Limit how many research directions enter experimentation; default `3` |
| `background` | Context, papers, datasets, and code references |
| `methodology` | Required approach, steps, baselines, or metrics |
| `constraints` | Compute, time, memory, or budget limits |
| `local_resources` | Host datasets or Python functions that must be staged into the workspace |
| `evaluation` | User-defined metrics, targets, and required evaluator functions |
| `evaluation_criteria` | Free-form validity, reproducibility, or quality requirements |
| `expected_outputs` | Artifacts the completed research should produce |

See [`ideas/examples/`](ideas/examples/) for complete examples and
[`ideas/schema.yaml`](ideas/schema.yaml) for the authoritative schema. New users
can follow the [Idea Quickstart](docs/IDEA_QUICKSTART.md); the
[complete Idea Guide](docs/IDEA_GUIDE.md) explains every supported field.

Submit the idea with the basic command:

```bash
# Docker
./neurico submit ideas/my_idea.yaml

# Local uv
uv run python src/cli/submit.py ideas/my_idea.yaml
```

NeuriCo validates the YAML, stores a submitted copy, and prints the
`<idea_id>`. Submission does not start research. When `GITHUB_TOKEN` is
configured, NeuriCo also creates and prepares the research repository;
otherwise submission completes in the local workspace.

Submission options:

| Flag | Meaning |
| --- | --- |
| `--no-validate` | Skip schema validation; use only when diagnosing a malformed or experimental schema |
| `--no-github` | Do not create a research repository, even when `GITHUB_TOKEN` is configured |
| `--github-org ORG` | Create the research repository in the specified organization when `GITHUB_TOKEN` is configured |
| `--private` | Make the generated research repository private |
| `--no-hash` | Omit the random hash from the generated repository name |

#### B. Convert a Markdown or text idea

Use `submit-local` when the idea is prose or mentions datasets and functions on
your machine. Start with conversion only:

```bash
# Docker
./neurico submit-local idea.md

# Local uv
uv run python src/cli/submit_local.py idea.md
```

NeuriCo converts the prose into a YAML idea under `ideas/` and stops so it can
be reviewed. It does not submit the idea or start research.

Add `--submit` after reviewing the conversion to convert and submit in one
command. Add `--run` as well only when research should start immediately;
`--run` requires `--submit`.

Conversion options:

| Flag | Meaning |
| --- | --- |
| `--output PATH` | Write the converted YAML to a specific location |
| `--submit` | Submit immediately after conversion |
| `--run` | Start Standard research after submission; requires `--submit` |

The common submission options above also apply. Declared local resources are
recorded during submission and staged when research starts. Docker mounts only
those declared host paths and mounts them read-only. See
[`docs/LOCAL_IDEA_SUBMISSION.md`](docs/LOCAL_IDEA_SUBMISSION.md).

#### C. Import from IdeaHub

Start with fetch and conversion only:

```bash
# Docker
./neurico fetch <ideahub_url>

# Local uv
uv run python src/cli/fetch_from_ideahub.py <ideahub_url>
```

NeuriCo fetches the IdeaHub page, converts it into a YAML idea under `ideas/`,
and stops for review. It does not submit the idea or start research.

Add `--submit` to fetch, convert, and submit in one command. Add `--run` as
well only when research should start immediately; `--run` requires `--submit`.

Import options:

| Flag | Meaning |
| --- | --- |
| `--output PATH` | Write the converted YAML to a specific location |
| `--submit` | Submit immediately after conversion |
| `--run` | Start Standard research after submission; requires `--submit` |

The common submission options above also apply. IdeaHub has a template-based
conversion fallback; `OPENROUTER_KEY` or `OPENAI_API_KEY` enables LLM-assisted
conversion. See
[`docs/IDEAHUB_INTEGRATION.md`](docs/IDEAHUB_INTEGRATION.md).

### 3. Choose a research mode

Replace `<idea_id>` below with the ID printed during submission.

#### Standard

Start a basic Standard run:

```bash
# Docker
./neurico run <idea_id>

# Local uv
uv run python src/core/runner.py <idea_id>
```

NeuriCo uses Claude and the local compute backend by default. It runs resource
discovery, experiment planning and execution, analysis, and paper generation
once, with provider permission prompts disabled. It does not perform iterative
AutoResearch. If GitHub integration is configured, the workspace is connected
and published there; otherwise it remains local.

Standard options:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--provider claude\|codex\|gemini` | `claude` | Provider CLI used by research workers |
| `--compute-backend local\|dsi-slurm\|modal` | `local` | Where experiment and comment execution runs |
| `--timeout SECONDS` | `3600` | Experiment-runner timeout |
| `--no-github` | GitHub enabled | Keep execution local instead of publishing |
| `--github-org ORG` | `GITHUB_ORG` | GitHub organization for publication |
| `--private` | public repository | Create a private repository |
| `--no-full-permissions` | full permissions enabled | Require normal provider permission prompts |
| `--no-write-paper` | paper enabled | Skip paper generation |
| `--paper-style neurips\|icml\|acl\|ams` | domain default | Select the paper template |
| `--paper-timeout SECONDS` | `3600` | Paper-writer timeout |
| `--force-fresh` | reuse workspace | Ignore an existing workspace and start fresh |

Pipeline-control flags:

| Flag | Meaning |
| --- | --- |
| `--pause-after-resources` | Pause after resource discovery for manual review |
| `--skip-resource-finder` | Skip resource discovery when the workspace is already prepared |
| `--resource-finder-timeout SECONDS` | Change the resource-finder timeout; default `2700` |
| `--use-scribe` | Use the optional notebook-oriented Scribe execution path |
| `--enable-scoring` | Add a sealed rule-maker/scorer stage to a one-pass Standard run |
| `--comment-mode` | Apply targeted changes described by comments in the submitted idea |

#### AutoResearch

AutoResearch is NeuriCo's automated iterative mode. It establishes a scored
best checkpoint, proposes one change per iteration, runs and scores the
candidate, and accepts it only when it improves the current best.

##### Fresh AutoResearch

Start with the basic fresh command:

```bash
# Docker
./neurico run <idea_id> --autoresearch

# Local uv
uv run python src/core/runner.py <idea_id> --autoresearch
```

NeuriCo runs the full scored research pipeline to establish the initial best
checkpoint, then performs one proposal/run/score iteration. The candidate is
kept only if it improves the score.

##### Continue AutoResearch

When a scored best checkpoint already exists, use the basic continuation
command:

```bash
# Docker
./neurico run <idea_id> --continue-autoresearch

# Local uv
uv run python src/core/runner.py <idea_id> --continue-autoresearch
```

NeuriCo skips resource discovery and the initial experiment pipeline, restores
the existing best checkpoint, and performs one additional iteration.

##### Bootstrap an existing Standard workspace

When Standard research already produced useful outputs but no AutoResearch
baseline exists, start with:

```bash
# Docker
./neurico run <idea_id> --bootstrap-autoresearch-baseline

# Local uv
uv run python src/core/runner.py <idea_id> --bootstrap-autoresearch-baseline
```

NeuriCo constructs the scoring protocol, scores the existing work, checkpoints
it as the initial best, and writes continuation state. Bootstrap does not run
an improvement iteration; afterward, use the continuation command above.

AutoResearch options:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--autoresearch` | off | Create a fresh scored baseline and iterate |
| `--continue-autoresearch` | off | Continue from the existing best checkpoint |
| `--bootstrap-autoresearch-baseline` | off | Convert an existing unscored workspace into a continuation-ready baseline |
| `--autoresearch-iterations N` | `1` | Number of proposal/run/score iterations |
| `--continue-recover` | off | Before continuation, discard changes left by an interrupted attempt and restore the current best |
| `--autoresearch-history-dir PATH` | `logs/experiment-autoresearch` | Override attempt-history storage |
| `--proposer-timeout SECONDS` | `900` | Timeout for each proposal-generation stage |
| `--rule-maker-timeout SECONDS` | `1800` | Timeout while constructing the scoring contract |
| `--scorer-timeout SECONDS` | `600` | Timeout for each scoring stage |
| `--manifest-trimmer-timeout SECONDS` | `300` | Timeout for each manifest-trimmer call during bootstrap |
| `--bootstrap-rule-maker` | off | Lower-level scoring-only retrofit; prefer `--bootstrap-autoresearch-baseline` when the goal is AutoResearch continuation |

Fresh, continue, and bootstrap-baseline are mutually exclusive entry paths.
Common provider, compute, GitHub, permission, and paper flags from Standard also
apply. See [`docs/AUTORESEARCH.md`](docs/AUTORESEARCH.md) for checkpoint and
recovery details.

#### HITL AutoResearch

HITL AutoResearch adds a durable manager conversation, explicit human decision
points, isolated scoring, and a retained research frontier. Web and terminal
are two interfaces for the same HITL mode and share the same workspace state.

##### Web interface

Start the basic web interface:

```bash
# Docker
./neurico hitl-web <idea_id>

# Local uv
uv run python src/cli/hitl_web.py <idea_id>
```

NeuriCo opens the durable manager workspace without starting research. The
default URL is `http://localhost:7890`. Docker publishes the page only to
`127.0.0.1` and prints the host URL; local `uv` also opens that URL in the
default browser.

Web options:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--port N` | `7890` | Use a different local web port |
| `--no-browser` | browser opens for local `uv` | Print the URL without opening a browser |

##### Terminal interface

Start the basic terminal interface:

```bash
# Docker
./neurico hitl-cli <idea_id>

# Local uv
uv run python src/cli/hitl_cli.py <idea_id>
```

NeuriCo opens the same durable manager conversation directly in the terminal.
It does not start research automatically.

In either interface, use `/run` to select the worker provider, iteration count,
paper options, and GitHub preference. NeuriCo detects whether the workspace
needs a fresh HITL run or continuation.

HITL controls:

| Control | Meaning |
| --- | --- |
| `/run` | Configure and start a fresh or continuing HITL run |
| `/reply <number>` | Select an option for the active human request |
| `/reply <feedback>` | Resolve the active request with free-form feedback |
| `/help` | Display interface commands |
| `/quit` | Close the terminal interface without resolving a pending request |

See [`docs/HITL_AUTORESEARCH.md`](docs/HITL_AUTORESEARCH.md) for the manager,
worker, scoring, frontier, and recovery model.

## Configuration

### Provider authentication

Provider CLIs use OAuth rather than API keys.

- **Docker:** credentials created by the setup or login flow are persisted on
  the host and mounted into each container.
- **Local `uv`:** run `claude`, `codex`, or `gemini` on the host and complete
  that CLI's login flow.

### GitHub integration

GitHub integration is optional. To create and push research repositories
automatically, add a classic GitHub token with `repo` scope to `.env`:

```dotenv
GITHUB_TOKEN=your_token
GITHUB_ORG=
```

Use `--no-github` on an individual submission or run when repository creation
and publishing should be disabled. See
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
- [`docs/IDEA_QUICKSTART.md`](docs/IDEA_QUICKSTART.md) — writing and submitting a first idea
- [`docs/IDEA_GUIDE.md`](docs/IDEA_GUIDE.md) — complete idea fields, domains, and examples
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
