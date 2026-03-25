---
name: neurico
version: 0.2.0
description: >
  Autonomous research framework that orchestrates AI agents (Claude Code, Codex, Gemini)
  to design, execute, analyze, and document scientific experiments. Takes a structured
  research idea (YAML with title, domain, hypothesis) and produces code, results, plots,
  LaTeX papers, and GitHub repositories.
tags:
  - autonomous-research
  - ai-scientist
  - experiment-automation
  - research-agent
  - paper-writing
  - literature-review
  - hypothesis-testing
  - scientific-computing
  - multi-agent
  - machine-learning
  - docker
  - latex
---

# NeuriCo

Autonomous AI research framework. Idea in, paper out.

## Quick Reference

| | |
|---|---|
| **What it does** | Takes a research idea (YAML) and autonomously runs the full research lifecycle: literature review, experiment design, code execution, analysis, paper writing, GitHub push |
| **Input** | YAML file with 3 required fields: `title`, `domain`, `hypothesis` |
| **Output** | Code (`src/`), results & plots (`results/`), LaTeX paper (`paper_draft/`), GitHub repo |
| **Providers** | Claude Code, Codex, Gemini (OAuth login, not API keys) |
| **Install** | `git clone https://github.com/ChicagoHAI/neurico && cd neurico && ./neurico setup` |
| **Source** | [github.com/ChicagoHAI/neurico](https://github.com/ChicagoHAI/neurico) — Chicago Human+AI Lab (ChicagoHAI), University of Chicago |
| **License** | Apache 2.0 |

## Requirements

### Minimal (one of)

| Option | What you need |
|--------|--------------|
| Docker (recommended) | `git` + `docker` |
| Native | `git` + `python>=3.10` + [`uv`](https://astral.sh/uv) |

### Resource

Access to at least one AI coding CLI (OAuth login required):

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (recommended)
- [Codex](https://github.com/openai/codex)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli)

### Recommended

| What | Why |
|------|-----|
| GitHub token (classic, `repo` scope) | Auto-creates repos and pushes results. [Create here](https://github.com/settings/tokens/new) |

### Optional API Keys

| Key | Purpose |
|-----|---------|
| `OPENAI_API_KEY` | LLM-based repo naming, IdeaHub fetching, paper-finder |
| `S2_API_KEY` | Semantic Scholar literature search via paper-finder |
| `OPENROUTER_KEY` | Multi-model access during experiments |
| `COHERE_API_KEY` | Improves paper-finder ranking (~7% boost) |
| `HF_TOKEN` | Hugging Face private models/datasets |
| `WANDB_API_KEY` | Weights & Biases experiment tracking |

### Setup Tiers

- **Basic:** CLI login + `GITHUB_TOKEN` -- full NeuriCo functionality
- **Enhanced:** + `OPENAI_API_KEY` -- LLM repo naming + IdeaHub support
- **Full:** + `S2_API_KEY` (+ optional `COHERE_API_KEY`) -- paper-finder literature search

## Installation

### Docker (recommended)

The Docker image is a pre-configured environment with Python, Node.js, AI coding CLIs (Claude Code, Codex, Gemini), and a full LaTeX installation for paper compilation -- so you don't have to install any of these yourself. All experiments run inside this container; nothing is installed on your host system beyond the cloned repo. The image is built from the open-source [Dockerfile](https://github.com/ChicagoHAI/neurico/blob/main/docker/Dockerfile) and hosted on GitHub Container Registry.

```bash
git clone https://github.com/ChicagoHAI/neurico && cd neurico
./neurico setup     # pulls Docker image, configures API keys, walks through CLI login
```

Or step by step:

```bash
git clone https://github.com/ChicagoHAI/neurico && cd neurico
docker pull ghcr.io/chicagohai/neurico:latest
docker tag ghcr.io/chicagohai/neurico:latest chicagohai/neurico:latest
./neurico config    # configure API keys
claude              # login to AI CLI (one-time, on host)
```

### Native

```bash
git clone https://github.com/ChicagoHAI/neurico && cd neurico
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
cp .env.example .env   # edit: add your API keys
claude                  # login to AI CLI
```

## Invocation

### Fastest: Fetch from IdeaHub and run

```bash
./neurico fetch <ideahub_url> --submit --run --provider claude
```

Browse ideas at [IdeaHub](https://hypogenic.ai/ideahub), copy the URL, and run the command above. NeuriCo fetches the idea, creates a GitHub repo, runs experiments, writes a paper, and pushes everything.

### From a YAML file

```bash
./neurico submit path/to/idea.yaml
./neurico run <idea_id> --provider claude
```

### Run options

| Option | Description |
|--------|-------------|
| `--provider claude\|gemini\|codex` | AI provider (default: claude) |
| `--no-github` | Run locally without GitHub integration |
| `--write-paper` | Generate LaTeX paper after experiments (default: on) |
| `--paper-style neurips\|icml\|acl\|ams` | Paper format (default: neurips) |
| `--private` | Create private GitHub repository |

## Input Format

Only 3 fields required:

```yaml
idea:
  title: "Do LLMs understand causality?"
  domain: artificial_intelligence
  hypothesis: "LLMs can distinguish causal from correlational relationships"
```

Optional fields: `background` (papers, datasets, code references), `methodology` (approach, steps, baselines, metrics), `constraints` (compute, time, memory, budget), `expected_outputs`, `evaluation_criteria`.

Full schema: [`ideas/schema.yaml`](https://github.com/ChicagoHAI/neurico/blob/main/ideas/schema.yaml)

## Output Format

```
workspace/<repo-name>/
  src/            # Python experiment code
  results/        # Metrics, plots, models
  paper_draft/    # LaTeX paper (with --write-paper)
  logs/           # Execution logs
  artifacts/      # Models, checkpoints
  .neurico/       # Original idea spec
```

Results are automatically pushed to the GitHub repo created during submission.

## Supported Domains

| Domain | Examples |
|--------|----------|
| Artificial Intelligence | LLM evaluation, prompt engineering, AI agents |
| Machine Learning | Training, evaluation, hyperparameter tuning |
| Data Science | EDA, statistical analysis, visualization |
| NLP | Language model experiments, text analysis |
| Computer Vision | Image processing, object detection |
| Reinforcement Learning | Agent training, policy evaluation |
| Systems | Performance benchmarking, optimization |
| Theory | Algorithmic analysis, proof verification |
| Scientific Computing | Simulations, numerical methods |

## Configuration

```bash
./neurico config      # Interactive API key configuration
./neurico setup       # Full setup wizard
./neurico shell       # Interactive shell inside container
./neurico help        # Show all commands
```

Environment variables go in `.env` (copy from `.env.example`). See [README](https://github.com/ChicagoHAI/neurico#configuration) for details.

## Security

- **No secrets are uploaded.** API keys and tokens stay local in your `.env` file and are never committed, pushed, or sent anywhere beyond the APIs they authenticate with. Sensitive environment variables are explicitly [filtered out](https://github.com/ChicagoHAI/neurico/blob/main/src/core/security.py) from all subprocess calls and sanitized from logs.
- **Experiments run inside Docker.** The container is isolated from your host system. The only host directories mounted are your config, templates, and workspace output folder.
- **Open source.** The entire codebase, including the [Dockerfile](https://github.com/ChicagoHAI/neurico/blob/main/docker/Dockerfile) and [install script](https://github.com/ChicagoHAI/neurico/blob/main/install.sh), is publicly auditable on GitHub.
- **Built by [ChicagoHAI](https://github.com/ChicagoHAI)** — the Human+AI Lab at the University of Chicago.
