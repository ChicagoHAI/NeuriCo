<div align="center">

<img src="assets/banner.png" alt="NeuriCo - AI-Powered Research Acceleration" width="600"/>

[![GitHub Stars](https://img.shields.io/github/stars/ChicagoHAI/neurico?style=flat-square)](https://github.com/ChicagoHAI/neurico)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg?style=flat-square)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](docker/)
[![License](https://img.shields.io/badge/License-Apache%202.0-green.svg?style=flat-square)](LICENSE)
[![X Follow](https://img.shields.io/badge/X-Follow-black?style=flat-square&logo=x)](https://x.com/ChicagoHAI)
[![Discord](https://img.shields.io/badge/Discord-Join-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/n65caV7NhC)

</div>

<hr>

<!-- agent-summary: NeuriCo is an autonomous research framework. Input: YAML (title, domain, hypothesis). Output: code, results, plots, LaTeX paper, GitHub repo. Providers: Claude Code, Codex, Gemini. Install: curl one-liner or git+docker. Requirements: git + docker (or git + python 3.10+), plus an AI coding CLI (Claude Code, Codex, or Gemini). License: Apache 2.0. Repository: https://github.com/ChicagoHAI/neurico -->

**NeuriCo** (**Neur**al **Co**-Scientist, inspired by Enrico Fermi) is an autonomous research framework that takes structured research ideas and orchestrates AI agents to design, execute, analyze, and document experiments across diverse domains.

<div align="center">
<img src="assets/neurico-6x.gif" alt="NeuriCo Demo" width="700"/>
</div>

<details open>
<summary><b>Key Features</b></summary>

| Feature | Description |
|---------|-------------|
| **Minimal Input** | Just provide title, domain, and hypothesis - agents handle the rest |
| **Agent-Driven Research** | Literature review, dataset search, baseline identification |
| **Multi-Provider Support** | Works with Claude, Codex, and Gemini (raw CLI by default, notebooks optional) |
| **Pragmatic Execution** | Creates resources when they don't exist, always proceeds |
| **Domain-Agnostic** | ML, data science, AI, systems, theory, and more |
| **Smart Documentation** | Auto-generates reports, code, and results |
| **GitHub Integration** | Auto-creates repos and pushes results |

</details>

## Requirements

**Minimal** (one of):
- **Option 1:** `git` + [Docker](https://docs.docker.com/get-docker/) (recommended)
- **Option 2:** `git` + Python 3.10+ + [`uv`](https://astral.sh/uv)

**Resource** — access to at least one AI coding CLI (uses OAuth login, not API keys):
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (recommended), [Codex](https://github.com/openai/codex), or [Gemini CLI](https://github.com/google-gemini/gemini-cli)

**Recommended:**
- GitHub token (classic, `repo` scope) — for auto-creating repos and pushing results. [Create here](https://github.com/settings/tokens/new)

**Optional API keys** (enhance functionality):

| Key | Purpose |
|-----|---------|
| `OPENAI_API_KEY` | LLM-based repo naming, IdeaHub fetching, paper-finder |
| `S2_API_KEY` | Semantic Scholar literature search ([get here](https://www.semanticscholar.org/product/api)) |
| `OPENROUTER_KEY` | Multi-model access during experiments |
| `COHERE_API_KEY` | Improves paper-finder ranking (~7%) |
| `HF_TOKEN` | Hugging Face private models/datasets |
| `WANDB_API_KEY` | Weights & Biases experiment tracking |

**Setup tiers:**
- **Basic:** CLI login + `GITHUB_TOKEN` — full NeuriCo functionality
- **Enhanced:** + `OPENAI_API_KEY` — LLM repo naming + IdeaHub support
- **Full:** + `S2_API_KEY` (+ optional `COHERE_API_KEY`) — paper-finder literature search

<details open>
<summary><b>Quick Start</b></summary>

**1. Install** (clones repo, pulls Docker image, walks you through setup):

```bash
curl -fsSL https://raw.githubusercontent.com/ChicagoHAI/neurico/main/install.sh | bash
```

**2. Run** — pick or submit an idea on [IdeaHub](https://hypogenic.ai/ideahub) and go:

```bash
cd NeuriCo
./neurico fetch <ideahub_url> --submit --run --provider claude --write-paper --full-permissions
```

That's it! The agent fetches the idea, creates a GitHub repo, runs experiments, writes a paper, and pushes everything.

<details>
<summary>Manual setup (alternative to one-liner)</summary>

```bash
git clone https://github.com/ChicagoHAI/neurico
cd neurico
./neurico setup      # Interactive wizard: pulls Docker image, configures API keys
```

</details>

</details>

## Setup

### Docker (Recommended)

Docker provides an isolated environment with GPU support, CLI tools, LaTeX, and paper-finder pre-installed. The pre-built image includes everything — Python venvs, CLI tools (Claude/Codex/Gemini), LaTeX, and paper-finder — so you skip the long build step.

```bash
# Clone the repo (provides CLI scripts, config, templates, and idea examples)
git clone https://github.com/ChicagoHAI/neurico
cd neurico

# Option A: Pull pre-built image (faster, ~2 min download)
docker pull ghcr.io/chicagohai/neurico:latest
docker tag ghcr.io/chicagohai/neurico:latest chicagohai/neurico:latest

# Option B: Build from source (~10-15 min)
./neurico build

# Configure
./neurico config   # Interactive menu for API keys and settings

# Login to your AI CLI (one-time, on your host machine)
claude   # or: codex, gemini
# Credentials are automatically mounted into containers
```

> **Note:** Cloning the repo is required even when pulling the pre-built image. The repo provides the `./neurico` CLI, config files, templates, and idea examples. The Docker image provides the runtime environment (Python, tools, LaTeX). At runtime, config and templates are mounted from your local clone into the container, so you can customize them without rebuilding.

**GPU support** requires [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html):

```bash
sudo apt install nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### Native Installation

For users who prefer running directly on their system.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # Install uv
git clone https://github.com/ChicagoHAI/neurico
cd neurico
uv sync
cp .env.example .env   # Edit: add your API keys
claude   # Login to your AI CLI
```

## Configuration

### CLI Authentication

Claude Code, Codex, and Gemini CLIs use **OAuth login** (not API keys). Login once on your host machine:

```bash
claude    # or: codex, gemini
```

In Docker mode, credentials are automatically mounted into containers.

### Environment Variables (.env)

The easiest way to configure is the interactive menu:

```bash
./neurico config
```

Or copy `.env.example` to `.env` and edit manually. Here's what each variable does:

**GitHub** — token required; org optional (uses personal account if empty)

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | Yes | GitHub Classic Personal Access Token ([create here](https://github.com/settings/tokens/new), select `repo` scope) |
| `GITHUB_ORG` | No | GitHub org name (default: personal account) |

**Paper Finder** — `OPENAI_API_KEY` + `S2_API_KEY` required for full paper-finder; `COHERE_API_KEY` optional (improves ranking)

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | For paper-finder | Used for paper-finder, IdeaHub fetching, and LLM repo naming |
| `S2_API_KEY` | For paper-finder | Semantic Scholar API key ([get here](https://www.semanticscholar.org/product/api)) |
| `COHERE_API_KEY` | No | Improves paper-finder ranking (~7% boost) |

**Agent API Keys** — optional, provided to the agent during automated experiments

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Claude API access |
| `GOOGLE_API_KEY` | Google AI / Gemini API access |
| `OPENROUTER_KEY` | OpenRouter multi-model access |
| `HF_TOKEN` | Hugging Face model/dataset access |
| `WANDB_API_KEY` | Weights & Biases experiment tracking |

### Workspace Configuration

Research workspaces are created in the directory specified by `config/workspace.yaml`.

**Default:** `workspace/` in the project root (already gitignored).

**To customize:** Copy `config/workspace.yaml.example` to `config/workspace.yaml` and edit `parent_dir`:

```yaml
workspace:
  parent_dir: "/path/to/your/workspaces"
  auto_create: true
```

### Customizing Templates and Skills

Templates in `templates/` control agent behavior. In Docker mode, these are mounted from the host, so you can edit them without rebuilding:

| What to Change | Template File |
|----------------|---------------|
| Experiment workflow (phases 1-6) | `templates/agents/session_instructions.txt` |
| Paper writing structure | `templates/agents/paper_writer.txt` |
| Resource finding behavior | `templates/agents/resource_finder.txt` |
| Research methodology | `templates/base/researcher.txt` |
| Domain-specific guidance | `templates/domains/<domain>/core.txt` |
| Claude Code skills | `templates/skills/<skill-name>/SKILL.md` |

See [ARCHITECTURE_AND_ROADMAP.md](ARCHITECTURE_AND_ROADMAP.md) for details on the template system.

## Usage

### Fetch from IdeaHub (Easiest)

Browse ideas at [IdeaHub](https://hypogenic.ai/ideahub), then fetch and run:

```bash
# Docker
./neurico fetch <ideahub_url> --submit --run --provider claude --write-paper --full-permissions

# Native
uv run python src/cli/fetch_from_ideahub.py <ideahub_url> --submit --run --provider claude --write-paper --full-permissions
```

This one command: fetches the idea, converts it to YAML, submits it, creates a GitHub repo, runs the research agent, and writes a LaTeX paper.

You can also break it into steps:

```bash
./neurico fetch <url>             # Just fetch and convert to YAML
./neurico fetch <url> --submit    # Fetch, convert, and submit (creates GitHub repo)
```

### Submit Your Own Idea

Write an idea YAML (see examples in `ideas/examples/`) and submit:

```bash
# Docker
./neurico submit ideas/examples/ml_regularization_test.yaml
./neurico run <idea_id> --provider claude --full-permissions

# Native
uv run python src/cli/submit.py ideas/examples/ml_regularization_test.yaml
uv run python src/core/runner.py <idea_id> --provider claude --full-permissions
```

### Run Options

| Option | Description |
|--------|-------------|
| `--provider claude\|gemini\|codex` | AI provider (default: claude) |
| `--timeout SECONDS` | Execution timeout (default: 3600) |
| `--full-permissions` | Allow agents to run without prompts |
| `--no-github` | Run locally without GitHub integration |
| `--github-org ORG` | GitHub organization (default: `GITHUB_ORG` env var) |
| `--private` | Create private GitHub repository |
| `--no-hash` | Simpler repo names (skip random hash) |
| `--write-paper` | Generate LaTeX paper after experiments |
| `--paper-style neurips\|icml\|acl` | Paper format (default: neurips) |

### Other Commands

```bash
./neurico config      # Configure API keys and settings
./neurico shell       # Interactive shell inside the container
./neurico login       # Login to CLI tools inside the container
./neurico help        # Show all commands
```

<details>
<summary><b>System Architecture</b></summary>

```mermaid
flowchart LR
    subgraph Input
        A[Research Idea<br/>YAML] --> B[Submit CLI]
        C[IdeaHub URL] --> B
    end

    subgraph Processing
        B --> D[GitHub Repo<br/>Created]
        D --> E[Research Agent]
        E --> F[Literature Review]
        E --> G[Experiment Design]
        E --> H[Code Execution]
    end

    subgraph Output
        F --> I[Documentation]
        G --> I
        H --> I
        I --> J[Notebooks]
        I --> K[Results & Plots]
        I --> L[GitHub Push]
    end
```

**Directory Structure:**

```
ideas/
  submitted/      <- New research ideas
  in_progress/    <- Currently executing
  completed/      <- Finished research

workspace/<repo-name>/
  .claude/skills/ <- Claude Code skills (paper-finder, literature-review, etc.)
  src/            <- Python scripts for experiments (default mode)
  results/        <- Metrics, plots, models
  logs/           <- Execution logs and transcripts
  artifacts/      <- Models, checkpoints
  notebooks/      <- Jupyter notebooks (only with --use-scribe)
  paper_draft/    <- LaTeX paper output (only with --write-paper)
  .neurico/ <- Original idea spec
```

</details>

<details>
<summary><b>Research-First Philosophy</b></summary>

**You can submit minimal ideas** - agents will research the details:

- Just provide: title, domain, research question
- Agent searches for: datasets, baselines, evaluation methods
- Grounds in literature when resources exist
- Creates synthetic data/baselines when they don't
- Always proceeds to execution - doesn't get stuck

**Example minimal idea:**
```yaml
idea:
  title: "Do LLMs understand causality?"
  domain: artificial_intelligence
  hypothesis: "LLMs can distinguish causal from correlational relationships"
  # That's it! Agent handles the rest
```

**Full specification example:**
```yaml
idea:
  title: "Clear, descriptive title"
  domain: machine_learning
  hypothesis: "Specific, testable hypothesis"

  background:
    description: "Context and motivation"
    papers:
      - url: "https://arxiv.org/..."
        description: "Why this paper is relevant"
    datasets:
      - name: "Dataset name"
        source: "Where to get it"

  methodology:
    approach: "High-level strategy"
    steps: ["Step 1", "Step 2"]
    baselines: ["Baseline 1", "Baseline 2"]
    metrics: ["Metric 1", "Metric 2"]

  constraints:
    compute: gpu_required
    time_limit: 3600
```

See `ideas/schema.yaml` for full specification.

</details>

<details>
<summary><b>Supported Domains</b></summary>

| Domain | Examples |
|--------|----------|
| **Artificial Intelligence** | LLM evaluation, prompt engineering, AI agents, benchmarking |
| **Machine Learning** | Training, evaluation, hyperparameter tuning |
| **Data Science** | EDA, statistical analysis, visualization |
| **Systems** | Performance benchmarking, optimization |
| **Theory** | Algorithmic analysis, proof verification |
| **Scientific Computing** | Simulations, numerical methods |
| **NLP** | Language model experiments, text analysis |
| **Computer Vision** | Image processing, object detection |
| **Reinforcement Learning** | Agent training, policy evaluation |

</details>

<details>
<summary><b>Paper-Finder Integration</b></summary>

When `S2_API_KEY` and `OPENAI_API_KEY` are set, the container automatically starts the paper-finder service for high-quality literature search with relevance ranking.

- **With paper-finder:** Agents get ranked, relevant papers via Semantic Scholar + LLM scoring
- **Without paper-finder:** Agents fall back to manual search (arXiv, Semantic Scholar, Papers with Code)
- **Optional `COHERE_API_KEY`:** Adds reranking for ~7% quality improvement

Paper-finder starts automatically in Docker — no extra setup needed.

</details>

## Testing

Install dev dependencies and run the test suite:

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install project with dev dependencies
uv sync --dev

# Run all tests
uv run pytest tests/ -v

# Run unit tests only
uv run pytest tests/test_security.py tests/test_config_loader.py tests/test_idea_manager.py tests/test_pipeline_state.py -v

# Run integration tests only
uv run pytest tests/test_pipeline_orchestrator_integration.py -v
```

No API keys or external services are required — all tests use temporary directories and mock data.

## Documentation

- **[docs/WORKFLOW.md](docs/WORKFLOW.md)** - Complete workflow guide
- **[docs/IDEAHUB_INTEGRATION.md](docs/IDEAHUB_INTEGRATION.md)** - IdeaHub integration
- **[ARCHITECTURE_AND_ROADMAP.md](ARCHITECTURE_AND_ROADMAP.md)** - Architecture, template system, and roadmap
- **[DESIGN.md](DESIGN.md)** - Comprehensive design document
- **[docs/GITHUB_INTEGRATION.md](docs/GITHUB_INTEGRATION.md)** - GitHub setup and usage
- **[ideas/schema.yaml](ideas/schema.yaml)** - Full specification schema
- **[ideas/examples/](ideas/examples/)** - Example research ideas

## Contributing

Contributions welcome! Areas of interest:

- New domain templates (biology, chemistry, social science, etc.)
- Additional evaluation criteria
- Integration with experiment trackers
- Web interface
- Multi-agent collaboration features

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

Some skills in `templates/skills/` were inspired by [claude-scientific-skills](https://github.com/K-Dense-AI/claude-scientific-skills) (MIT License, K-Dense Inc.). See [NOTICE](NOTICE) for details.

## License

Apache 2.0 - See [LICENSE](LICENSE) file

<hr>

<div align="center">

**Ready to explore your research ideas?**

```bash
./neurico fetch https://hypogenic.ai/ideahub/idea/YOUR_IDEA_ID \
    --submit --run --provider claude --full-permissions
```

For questions and feedback, [open an issue](https://github.com/ChicagoHAI/neurico/issues) or join our [Discord](https://discord.gg/BgkfTvBdbV).

</div>
