<div align="center">

<img src="assets/banner.png" alt="NeuriCo - AI-Powered Research Acceleration" width="600"/>

[![GitHub Stars](https://img.shields.io/github/stars/ChicagoHAI/neurico?style=flat-square)](https://github.com/ChicagoHAI/neurico)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg?style=flat-square)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](docker/)
[![License](https://img.shields.io/badge/License-Apache%202.0-green.svg?style=flat-square)](LICENSE)
[![X Follow](https://img.shields.io/badge/X-Follow-black?style=flat-square&logo=x)](https://x.com/ChicagoHAI)
[![Discord](https://img.shields.io/badge/Discord-Join-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/n65caV7NhC)

</div>

<!-- agent-summary: NeuriCo is an autonomous and human-in-the-loop research framework. Input: YAML, Markdown/text, or IdeaHub. Modes: Standard, AutoResearch, and HITL AutoResearch. Outputs: code, results, logs, scores, and an optional paper. Providers: Claude Code, Codex, Gemini. Installation: Docker or local uv. License: Apache 2.0. -->

**NeuriCo** (**Neur**al **Co**-Scientist, inspired by Enrico Fermi) coordinates
agents that turn a structured research idea into an experimental study.

<div align="center">
<img src="assets/neurico-6x.gif" alt="NeuriCo Demo" width="700"/>
</div>

## Key features

| Feature | Description |
| --- | --- |
| **Minimal input** | Start with a title, research domain, and testable hypothesis |
| **Agent-driven research** | Carries an idea from resource discovery through experimental analysis |
| **Multi-provider support** | Works with Claude Code, Codex, and Gemini CLI |
| **AutoResearch** | Tests iterative improvements and retains the strongest checkpoint |
| **HITL AutoResearch** | Adds a persistent manager and human decision points |
| **Domain-agnostic** | Provides guidance across research domains |
| **Reproducible outputs** | Preserves each run in a self-contained workspace |
| **GitHub integration** | Optionally creates repositories and publishes results |

## Requirements

Choose one installation route:

| Route | Requirements |
| --- | --- |
| **Docker** | [Git](https://git-scm.com/) and a running [Docker](https://docs.docker.com/get-docker/) installation |
| **Local `uv`** | Git, Python 3.10+, [`uv`](https://docs.astral.sh/uv/getting-started/installation/), and a provider CLI |

NeuriCo uses OAuth access to one of these providers:
[Claude Code](https://docs.anthropic.com/en/docs/claude-code),
[Codex](https://github.com/openai/codex), or
[Gemini CLI](https://github.com/google-gemini/gemini-cli).

For automatic repository creation, use a classic GitHub token with `repo`
scope. [Create a token](https://github.com/settings/tokens/new) and add it to
`.env` as `GITHUB_TOKEN`. GitHub is optional.

## Quick start

Use either Docker or local `uv` throughout the workflow.

### 1. Install

#### Docker

```bash
git clone https://github.com/ChicagoHAI/neurico.git
cd neurico
./neurico setup --quick
```

Quick setup uses Claude. Run `./neurico setup` to choose another provider or
configure optional services.

#### Local `uv`

Install one provider CLI, then run:

```bash
git clone https://github.com/ChicagoHAI/neurico.git
cd neurico
uv sync
cp .env.example .env
claude  # or: codex, gemini
```

### 2. Submit an idea

Create `ideas/my_idea.yaml`:

```yaml
idea:
  title: "Do LLMs distinguish causation from correlation?"
  domain: artificial_intelligence
  hypothesis: >
    Explicit causal prompts improve causal-reasoning accuracy compared with
    otherwise equivalent direct prompts.
```

Submit it and keep the printed `<idea_id>`:

| Docker | Local `uv` |
| --- | --- |
| `./neurico submit ideas/my_idea.yaml` | `uv run python src/cli/submit.py ideas/my_idea.yaml` |

### 3. Run the idea

Replace `<idea_id>` with the ID from submission.

| Mode | Docker | Local `uv` |
| --- | --- | --- |
| **Standard** | `./neurico run <idea_id>` | `uv run python src/core/runner.py <idea_id>` |
| **AutoResearch** | `./neurico run <idea_id> --autoresearch` | `uv run python src/core/runner.py <idea_id> --autoresearch` |
| **HITL AutoResearch** | `./neurico hitl-web <idea_id>` | `uv run python src/cli/hitl_web.py <idea_id>` |

HITL opens a manager interface; enter `/run` to start research. For a terminal
interface, use `./neurico hitl-cli <idea_id>` or
`uv run python src/cli/hitl_cli.py <idea_id>`.

Claude is the default provider. Add `--provider codex` or `--provider gemini`
to Standard and AutoResearch commands after logging in to that provider.

Workspaces are stored under `workspaces/` by default.

## Guides

Use the focused guides when you need more than the basic workflow:

| Task | Guide |
| --- | --- |
| Follow the complete workflow | [Workflow guide](docs/WORKFLOW.md) |
| Write a first idea | [Idea quickstart](docs/IDEA_QUICKSTART.md) |
| Use the complete idea schema | [Idea reference](docs/IDEA_GUIDE.md) |
| Continue or bootstrap AutoResearch | [AutoResearch guide](docs/AUTORESEARCH.md) |
| Work with the HITL manager | [HITL AutoResearch guide](docs/HITL_AUTORESEARCH.md) |
| Submit Markdown or local resources | [Local submission guide](docs/LOCAL_IDEA_SUBMISSION.md) |
| Import an IdeaHub idea | [IdeaHub guide](docs/IDEAHUB_INTEGRATION.md) |
| Publish research to GitHub | [GitHub integration guide](docs/GITHUB_INTEGRATION.md) |
| Configure paper-finder | [Paper-finder setup](config/paper_finder.md) |
| Customize agent behavior | [Template reference](templates/README.md) |

See the [documentation index](docs/README.md) for developer and legacy
references. The [ClawHub skill](clawskill/SKILL.md) provides discovery and
onboarding metadata; NeuriCo still runs through Docker or local `uv`.

## Contributing

Contributions are welcome. Open an issue before starting a large change.

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
