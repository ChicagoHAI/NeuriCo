---
name: neurico
version: 0.4.0
description: >
  Autonomous and human-in-the-loop research framework. Submit a structured
  research idea, then run Standard, AutoResearch, or HITL AutoResearch through
  either Docker or a local uv environment.
tags:
  - autonomous-research
  - ai-scientist
  - experiment-automation
  - research-agent
  - paper-writing
  - literature-review
  - hypothesis-testing
  - human-in-the-loop
  - autoresearch
  - multi-agent
  - machine-learning
  - docker
---

# NeuriCo

NeuriCo turns a structured research idea into experiments, results,
documentation, and an optional paper. It supports Claude Code, Codex, and
Gemini.

Source: [github.com/ChicagoHAI/neurico](https://github.com/ChicagoHAI/neurico)

## Research modes

| Mode | Purpose |
| --- | --- |
| **Standard** | Run the research pipeline once |
| **AutoResearch** | Score a baseline and iteratively keep improvements |
| **HITL AutoResearch** | Add a durable manager, human decisions, and a retained research frontier |

## Choose an execution route

NeuriCo has two equal execution routes. ClawHub is the distribution and
onboarding surface; it does not create a third runtime.

| Docker | Local `uv` |
| --- | --- |
| Requires Git and Docker | Requires Git, `uv`, and a locally installed provider CLI |
| Use `./neurico ...` | Use `uv run python ...` |
| NeuriCo and provider CLIs run in containers | NeuriCo and provider CLIs run on the host |

Do not mix Docker and local commands within one run.

## 1. Set up

### Docker

```bash
git clone https://github.com/ChicagoHAI/neurico.git
cd neurico
./neurico setup --quick
```

Quick setup pulls the current image, creates minimal configuration, and guides
the user through Claude OAuth login. Run `./neurico setup` for Codex or Gemini,
GitHub configuration, optional API keys, or a custom workspace.

### Local `uv`

Install `uv` and one provider CLI, then:

```bash
git clone https://github.com/ChicagoHAI/neurico.git
cd neurico
uv sync
cp .env.example .env
claude  # or: codex, gemini
```

The final command performs OAuth login. API keys are optional for the basic
local-only workflow.

## 2. Write and submit an idea

Create `ideas/my_idea.yaml`:

```yaml
idea:
  title: "Do LLMs understand causality?"
  domain: artificial_intelligence
  hypothesis: "LLMs distinguish causal from correlational relationships."
```

Submit without GitHub:

| Docker | Local `uv` |
| --- | --- |
| `./neurico submit ideas/my_idea.yaml --no-github` | `uv run python src/cli/submit.py ideas/my_idea.yaml --no-github` |

Keep the printed `<idea_id>`. GitHub is optional; configure `GITHUB_TOKEN` and
omit `--no-github` to create and publish a research repository.

## 3. Choose a mode

| Mode | Docker | Local `uv` |
| --- | --- | --- |
| **Standard** | `./neurico run <idea_id> --provider claude --no-github --full-permissions` | `uv run python src/core/runner.py <idea_id> --provider claude --no-github --full-permissions` |
| **AutoResearch** | `./neurico run <idea_id> --provider claude --no-github --full-permissions --autoresearch --autoresearch-iterations 3` | `uv run python src/core/runner.py <idea_id> --provider claude --no-github --full-permissions --autoresearch --autoresearch-iterations 3` |
| **HITL AutoResearch — web** | `./neurico hitl-web <idea_id>` | `uv run python src/cli/hitl_web.py <idea_id>` |
| **HITL AutoResearch — terminal** | `./neurico hitl-cli <idea_id>` | `uv run python src/cli/hitl_cli.py <idea_id>` |

The web and terminal commands are two interfaces for the same HITL mode. Use
`/run` in the interface to configure and start research. NeuriCo automatically
detects fresh or continuing HITL state.

Replace `claude` with an authenticated `codex` or `gemini` provider.

## Other idea sources

| Source | Docker | Local `uv` |
| --- | --- | --- |
| IdeaHub | `./neurico fetch <ideahub_url> --submit --no-github` | `uv run python src/cli/fetch_from_ideahub.py <ideahub_url> --submit --no-github` |
| Markdown or text | `./neurico submit-local idea.md --submit --no-github` | `uv run python src/cli/submit_local.py idea.md --submit --no-github` |

## Configuration

- Provider CLIs use OAuth, not API keys.
- GitHub is optional. Add `GITHUB_TOKEN` to `.env` only for automatic repository
  creation and publishing.
- `OPENROUTER_KEY` or `OPENAI_API_KEY` enables LLM-assisted IdeaHub conversion;
  conversion has a template-based fallback without either key.
- `S2_API_KEY` and `COHERE_API_KEY` enhance paper-finder.
- Workspace location is configured in `config/workspace.yaml` and defaults to
  `workspaces/`.

## Outputs

Depending on the selected mode and flags, a workspace can contain source code,
results, plots, logs, scoring records, artifacts, reports, and `paper_draft/`.

## Security boundary

Docker mounts the configured workspace, idea records, logs, configuration,
templates, provider credentials, and explicitly declared local resources.
Declared local resources are mounted read-only. Full provider permissions are
not an operating-system sandbox; users should review the requested execution
scope before running.

For the authoritative user guide, read the project
[README](https://github.com/ChicagoHAI/neurico#start-here).
