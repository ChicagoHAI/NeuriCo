<div align="center">

<img src="assets/banner.png" alt="NeuriCo - AI-Powered Research Acceleration" width="600"/>

[![GitHub Stars](https://img.shields.io/github/stars/ChicagoHAI/neurico?style=flat-square)](https://github.com/ChicagoHAI/neurico)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg?style=flat-square)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](docker/)
[![License](https://img.shields.io/badge/License-Apache%202.0-green.svg?style=flat-square)](LICENSE)
[![X Follow](https://img.shields.io/badge/X-Follow-black?style=flat-square&logo=x)](https://x.com/ChicagoHAI)
[![Discord](https://img.shields.io/badge/Discord-Join-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/n65caV7NhC)

</div>

<!-- agent-summary: NeuriCo is an autonomous and human-in-the-loop research framework. Users install it with Docker or uv, submit a research idea, then choose Standard, AutoResearch, or HITL AutoResearch. Providers: Claude Code, Codex, Gemini. License: Apache 2.0. -->

**NeuriCo** (**Neur**al **Co**-Scientist, inspired by Enrico Fermi) turns a
testable research idea into a reproducible workspace with code, experiments,
results, and documentation.

Bring a title, a research domain, and a hypothesis. Add papers, datasets,
methods, or evaluation rules when they matter; otherwise, let the research
agents find a reasonable path. Research workers can use Claude Code, Codex, or
Gemini.

| Mode | Best for |
| --- | --- |
| **Standard** | One complete research pass |
| **AutoResearch** | Scored, iterative improvement |
| **HITL AutoResearch** | Iterative research with a durable manager and human decisions |

## Quick start

### 1. Install

Docker and local `uv` are equal routes. Pick one route and use its commands
throughout the workflow.

#### Docker

Requires [Git](https://git-scm.com/) and
[Docker](https://docs.docker.com/get-docker/).

```bash
git clone https://github.com/ChicagoHAI/neurico.git
cd neurico
./neurico setup
```

The setup wizard prepares the image and provider login. It offers a quick path
and a full configuration path.

<details>
<summary>Docker setup alternatives</summary>

Skip the setup choice and use the quick path directly:

```bash
./neurico setup --quick
```

Or use the one-line installer:

```bash
curl -fsSL https://raw.githubusercontent.com/ChicagoHAI/neurico/main/install.sh | bash
```

The repository is required even with the prebuilt image because it supplies
the launcher, configuration, templates, idea records, and workspace mounts.
To build the image from the current checkout, run `./neurico build`.

Useful maintenance commands:

```bash
./neurico config   # Edit settings and optional integrations
./neurico login    # Repeat provider login
./neurico update   # Update the checkout and image
./neurico help     # List available commands
```

</details>

#### Local `uv`

Requires [Git](https://git-scm.com/),
[`uv`](https://docs.astral.sh/uv/getting-started/installation/), and one
provider CLI: [Claude Code](https://docs.anthropic.com/en/docs/claude-code),
[Codex](https://github.com/openai/codex), or
[Gemini CLI](https://github.com/google-gemini/gemini-cli).

```bash
git clone https://github.com/ChicagoHAI/neurico.git
cd neurico
uv sync
cp .env.example .env
claude  # or: codex, gemini
```

The last command completes the provider's OAuth login. The local route uses
the same ideas, configuration, templates, and workspace layout as Docker.

If you discovered NeuriCo through the packaged [ClawHub skill](clawskill/SKILL.md),
choose either Docker or local `uv` here; ClawHub is not a third execution route.

### 2. Write and submit an idea

Create `ideas/my_idea.yaml`:

```yaml
idea:
  title: "Do LLMs distinguish causation from correlation?"
  domain: artificial_intelligence
  hypothesis: >
    Explicit causal prompts improve causal-reasoning accuracy compared with
    otherwise equivalent direct prompts.
```

Only `title`, `domain`, and a testable `hypothesis` are required. Optional
sections let you keep important choices under your control:

| Section | Purpose |
| --- | --- |
| `background` | Context, papers, datasets, and code references |
| `methodology` | Required approach, steps, baselines, or metrics |
| `constraints` | Compute, time, memory, or budget limits |
| `local_resources` | Host datasets or Python functions to stage into the workspace |
| `evaluation` | Metrics, targets, and evaluator functions |
| `expected_outputs` | Artifacts the completed research should produce |

See the [Idea quickstart](docs/IDEA_QUICKSTART.md), the complete
[Idea guide](docs/IDEA_GUIDE.md), [`ideas/schema.yaml`](ideas/schema.yaml), and
[`ideas/examples/`](ideas/examples/) for more examples.

Submit the YAML:

| Docker | Local `uv` |
| --- | --- |
| `./neurico submit ideas/my_idea.yaml` | `uv run python src/cli/submit.py ideas/my_idea.yaml` |

Submission validates the idea and prints an `<idea_id>`. It does not start a
research run. Relative and absolute idea paths work in both routes.

#### Markdown or text ideas

Use this route when the idea is written as prose or refers to datasets and
functions already on your machine:

| Docker | Local `uv` |
| --- | --- |
| `./neurico submit-local idea.md` | `uv run python src/cli/submit_local.py idea.md` |

The basic command creates a YAML draft under `ideas/` for review. Add
`--submit` to submit it immediately, or `--submit --run` to submit and start a
Standard run. Declared local resources are mounted read-only when research
starts. See [Local idea submission](docs/LOCAL_IDEA_SUBMISSION.md).

#### IdeaHub

Fetch and convert an IdeaHub page:

| Docker | Local `uv` |
| --- | --- |
| `./neurico fetch <ideahub_url>` | `uv run python src/cli/fetch_from_ideahub.py <ideahub_url>` |

The basic command creates a YAML draft for review. Add `--submit` or
`--submit --run` to continue directly to submission or execution. See the
[IdeaHub guide](docs/IDEAHUB_INTEGRATION.md).

#### Submission options

| Flag | Purpose |
| --- | --- |
| `--no-validate` | Skip schema validation; intended for development and diagnosis |
| `--no-github` | Disable repository creation for this submission |
| `--github-org ORG` | Create the repository in a GitHub organization |
| `--private` | Create a private repository |
| `--no-hash` | Omit the random hash from the generated repository name |

When `GITHUB_TOKEN` is configured, submission also creates and prepares a
research repository. Without it, submission stays local.

### 3. Choose a research mode

Replace `<idea_id>` with the ID printed during submission.

| Mode | Docker | Local `uv` |
| --- | --- | --- |
| **Standard** | `./neurico run <idea_id>` | `uv run python src/core/runner.py <idea_id>` |
| **AutoResearch** | `./neurico run <idea_id> --autoresearch` | `uv run python src/core/runner.py <idea_id> --autoresearch` |
| **HITL AutoResearch** | `./neurico hitl-web <idea_id>` | `uv run python src/cli/hitl_web.py <idea_id>` |

The sections below explain what each mode does and the options users are most
likely to need.

## Research modes

### Standard

Standard runs resource discovery, experiment design and execution, analysis,
and paper writing once.

| Docker | Local `uv` |
| --- | --- |
| `./neurico run <idea_id>` | `uv run python src/core/runner.py <idea_id>` |

The default provider is Claude, the default compute backend is local, and full
provider permissions and paper writing are enabled.

#### Common Standard options

| Flag | Default | Purpose |
| --- | --- | --- |
| `--provider claude\|codex\|gemini` | `claude` | Select the research worker provider |
| `--compute-backend local\|dsi-slurm\|modal` | `local` | Select where experiments execute |
| `--timeout SECONDS` | `3600` | Set the experiment-runner timeout |
| `--no-full-permissions` | full permissions | Restore normal provider permission prompts |
| `--no-write-paper` | paper enabled | Skip paper generation |
| `--paper-style neurips\|icml\|acl\|ams` | domain default | Select the paper template |
| `--no-github` | GitHub when configured | Keep the run local |
| `--force-fresh` | reuse workspace | Ignore an existing workspace and start again |

<details>
<summary>Advanced Standard pipeline controls</summary>

| Flag | Purpose |
| --- | --- |
| `--pause-after-resources` | Review resources before experimentation |
| `--skip-resource-finder` | Use an already prepared workspace |
| `--resource-finder-timeout SECONDS` | Change the resource-finder timeout; default `2700` |
| `--use-scribe` | Use the optional notebook-oriented execution path |
| `--enable-scoring` | Add a sealed rule-maker and scorer stage |
| `--comment-mode` | Apply targeted changes from comments in the submitted idea |

</details>

### AutoResearch

AutoResearch keeps a scored best checkpoint. Each iteration proposes one
change, runs it, scores it, and keeps it only when it improves the current best.

#### Start fresh

| Docker | Local `uv` |
| --- | --- |
| `./neurico run <idea_id> --autoresearch` | `uv run python src/core/runner.py <idea_id> --autoresearch` |

This runs the full scored pipeline, saves the initial best checkpoint, and
performs one improvement iteration.

#### Continue an existing AutoResearch workspace

| Docker | Local `uv` |
| --- | --- |
| `./neurico run <idea_id> --continue-autoresearch` | `uv run python src/core/runner.py <idea_id> --continue-autoresearch` |

Continuation uses an existing scored workspace and skips the upstream research
stages.

#### Bootstrap a Standard workspace

| Docker | Local `uv` |
| --- | --- |
| `./neurico run <idea_id> --bootstrap-autoresearch-baseline` | `uv run python src/core/runner.py <idea_id> --bootstrap-autoresearch-baseline` |

Bootstrap scores existing Standard work and prepares continuation state. It
does not run an improvement iteration; continue afterward with
`--continue-autoresearch`.

#### Common AutoResearch options

| Flag | Default | Purpose |
| --- | --- | --- |
| `--autoresearch-iterations N` | `1` | Set the number of improvement iterations |
| `--continue-recover` | off | Restore the best checkpoint after an interrupted dirty attempt |
| `--autoresearch-history-dir PATH` | workspace logs | Change attempt-history storage |

Fresh, continue, and bootstrap-baseline are mutually exclusive entry paths.
Standard provider, compute, permission, paper, and GitHub options also apply.

<details>
<summary>Advanced AutoResearch and bootstrap controls</summary>

| Flag | Default | Purpose |
| --- | --- | --- |
| `--proposer-timeout SECONDS` | `900` | Set proposal-generation timeout |
| `--rule-maker-timeout SECONDS` | `1800` | Set scoring-contract construction timeout |
| `--scorer-timeout SECONDS` | `600` | Set scoring timeout |
| `--manifest-trimmer-timeout SECONDS` | `300` | Set bootstrap manifest-trimmer timeout |
| `--bootstrap-rule-maker` | off | Retrofit scoring without creating AutoResearch continuation state |

</details>

See the [AutoResearch guide](docs/AUTORESEARCH.md) for checkpoint, scoring, and
recovery behavior.

### HITL AutoResearch

HITL AutoResearch adds a durable manager conversation, explicit human decision
points, isolated scoring, and a retained research frontier. Web and terminal
are two interfaces over the same workspace state.

#### Web interface

| Docker | Local `uv` |
| --- | --- |
| `./neurico hitl-web <idea_id>` | `uv run python src/cli/hitl_web.py <idea_id>` |

The default page is `http://localhost:7890`. Docker publishes it only to
`127.0.0.1` and prints the host URL. Use `--port N` to choose another port or
`--no-browser` to print the URL without opening it locally.

#### Terminal interface

| Docker | Local `uv` |
| --- | --- |
| `./neurico hitl-cli <idea_id>` | `uv run python src/cli/hitl_cli.py <idea_id>` |

Opening either interface does not start research. Use the manager controls when
you are ready:

| Control | Purpose |
| --- | --- |
| `/run` | Configure and start a fresh or continuing HITL run |
| `/reply <number>` | Choose an option for the active human request |
| `/reply <feedback>` | Resolve a request with free-form feedback |
| `/help` | Show interface commands |
| `/quit` | Close the terminal interface |

See the [HITL AutoResearch guide](docs/HITL_AUTORESEARCH.md) for the manager,
human requests, scoring frontier, and recovery model.

## Configuration

### Provider authentication

Claude Code, Codex, and Gemini use their own OAuth login. Docker setup persists
those credentials on the host and mounts them into containers. Local `uv` uses
the provider login already available on the host.

### Optional integrations

The `.env` file contains optional integrations. None of these service keys is
required for provider OAuth or a basic run.

| Variable | Purpose |
| --- | --- |
| `GITHUB_TOKEN` | Create and publish research repositories |
| `GITHUB_ORG` | Default GitHub organization |
| `OPENAI_API_KEY` | IdeaHub conversion, repository naming, and paper-finder |
| `S2_API_KEY` | Semantic Scholar literature search |
| `COHERE_API_KEY` | Paper-finder reranking |
| `OPENROUTER_KEY` | OpenRouter access during experiments |
| `HF_TOKEN` | Private Hugging Face models or datasets |
| `WANDB_API_KEY` | Weights & Biases tracking |

Docker users can run `./neurico config`; either route can edit `.env` directly.
See the [GitHub integration guide](docs/GITHUB_INTEGRATION.md) for repository
creation and publishing.

<details>
<summary>Paper-finder behavior</summary>

When `S2_API_KEY` and `OPENAI_API_KEY` are configured, paper-finder provides
ranked Semantic Scholar results. `COHERE_API_KEY` adds optional reranking.
Without those keys, agents use their normal literature-search tools.

</details>

### Workspace location

Workspaces default to `workspaces/`. To use another location, copy
`config/workspace.yaml.example` to `config/workspace.yaml` and set
`parent_dir`:

```yaml
workspace:
  parent_dir: "/path/to/your/workspaces"
  auto_create: true
```

Docker mounts that directory at `/workspaces`; local `uv` uses it directly.

## Outputs

A completed workspace can contain:

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

Idea records move through `ideas/submitted/`, `ideas/in_progress/`, and
`ideas/completed/`. Exact artifacts depend on the research mode and options.

<details>
<summary>System architecture</summary>

```mermaid
flowchart LR
    A["Idea (YAML, text, or IdeaHub)"] --> B["Submit and validate"]
    B --> C{"Choose a mode"}
    C --> D["Standard"]
    C --> E["AutoResearch"]
    C --> F["HITL AutoResearch"]
    D --> G["Research workspace"]
    E --> G
    F --> G
    G --> H["Code, results, logs, scores, and paper"]
```

</details>

## Supported domains

| Domain | Examples |
| --- | --- |
| Artificial intelligence | LLM evaluation, prompting, agents, benchmarking |
| Machine learning | Training, evaluation, and hyperparameter studies |
| Data science | Statistical analysis and visualization |
| Systems | Performance benchmarking and optimization |
| Theory | Algorithmic analysis and proof verification |
| Mathematics | Pure and applied mathematics |
| Mathematics (Lean) | Machine-checked Lean 4 proofs |
| Finance | Empirical finance and panel-data analysis |
| Battery research | Electrochemical energy storage |
| Scientific computing | Simulation and numerical methods |
| NLP | Language-model and text experiments |
| Computer vision | Image processing and detection |
| Reinforcement learning | Policy training and evaluation |

Domain definitions live in [`config/domains.yaml`](config/domains.yaml).

## Documentation

| Guide | What it covers |
| --- | --- |
| [Workflow](docs/WORKFLOW.md) | Complete Docker and local `uv` workflow |
| [Idea quickstart](docs/IDEA_QUICKSTART.md) | Write and submit a first idea |
| [Idea guide](docs/IDEA_GUIDE.md) | Full idea schema, fields, and examples |
| [AutoResearch](docs/AUTORESEARCH.md) | Fresh runs, continuation, recovery, and bootstrap |
| [HITL AutoResearch](docs/HITL_AUTORESEARCH.md) | Manager workflow, interfaces, frontier, and recovery |
| [Local files](docs/LOCAL_IDEA_SUBMISSION.md) | Markdown ideas, local datasets, functions, and evaluators |
| [IdeaHub](docs/IDEAHUB_INTEGRATION.md) | Import ideas from IdeaHub |
| [GitHub integration](docs/GITHUB_INTEGRATION.md) | Optional repository creation and publishing |

The [documentation index](docs/README.md) separates current user guides from
developer, internal, and legacy material.

## Contributing

Contributions are welcome, especially new domain templates, evaluation
contracts, experiment integrations, and improvements to the research modes.
Open an issue before beginning a large change so the approach can be discussed.

## Citation

If you use NeuriCo in research, please cite:

```bibtex
@software{neurico_2025,
  title={NeuriCo: Autonomous Research Framework},
  author={Haokun Liu, Chenhao Tan},
  year={2025},
  url={https://github.com/ChicagoHAI/neurico}
}
```

## Acknowledgments

Some skills in `templates/skills/` were inspired by
[claude-scientific-skills](https://github.com/K-Dense-AI/claude-scientific-skills)
(MIT License, K-Dense Inc.). See [`NOTICE`](NOTICE) for details.

## License

Apache 2.0. See [`LICENSE`](LICENSE).

For questions and feedback, [open an issue](https://github.com/ChicagoHAI/neurico/issues)
or join the [NeuriCo Discord](https://discord.gg/BgkfTvBdbV).
