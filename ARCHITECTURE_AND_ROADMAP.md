# NeuriCo: Architecture & Roadmap

> **TL;DR**: NeuriCo is an open-source AI scientist for exploring research ideas with AI agents. This document explains how it works and where we're headed based on lessons learned from running weekly competitions.

---

## Table of Contents

1. [Philosophy & Vision](#philosophy--vision)
2. [Architecture Overview](#architecture-overview)
3. [Core Components](#core-components)
4. [Pipeline Flow](#pipeline-flow)
5. [Template System](#template-system)
6. [What We've Learned](#what-weve-learned)
7. [Roadmap](#roadmap)
8. [Open Research Questions](#open-research-questions)
9. [How to Contribute](#how-to-contribute)

---

## Philosophy & Vision

### What AI Scientists Should Do

Our goal is to build general AI Scientists that serve as effective partners of human scientists.
They should
* work in any domain of interest,
* propose and reason about research directions,
* find and prioritize relevant resources,
* design rigorous experiments grounded in real data,
* interpretate results appropriately and recognize inconclusive results,
* explore alternative hypotheses and explanations,
* effectively collaborate with humans at any stage of research,
* produce reproducible and inspectable artifacts,
* report experiments and results honestly, including failures.

### Why Current Approaches Fall Short

Existing systems either focus on particular domains (e.g.,
[AI-Scientist](https://github.com/SakanaAI/AI-Scientist-v2),
[AI-Researcher](https://github.com/HKUDS/AI-Researcher) focusing on training ML models) or specific
tasks (e.g., Kosmos for data analyses). They also optimize for paper-like
outputs rather than rigorous research. They generate synthetic data when real data is needed, lack
meta-intelligence to judge when they're off track, and are developed behind closed doors where
failures aren't shared.

### Our Approach: Building This Together

NeuriCo is our open, collaborative effort toward better AI Scientists. We build in public, run weekly experiments, share what works and what doesn't, and welcome contributors who want to tackle the [hard problems](#open-research-questions) with us.

---

## Architecture Overview

NeuriCo uses a **multi-stage pipeline architecture** that separates resource gathering from experimentation:

```
┌─────────────────────────────────────────────────────────────────┐
│                         User (YAML Idea)                        │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                   1. Idea Manager                               │
│                   (Validation & Storage)                        │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                   2. GitHub Manager                             │
│                   (Create Workspace)                            │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                   3. Pipeline Orchestrator                      │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  Stage 1: Resource Finder Agent                             ││
│  │  - Literature review                                        ││
│  │  - Download papers, datasets, code                          ││
│  │  → Output: papers/, datasets/, literature_review.md         ││
│  └─────────────────────────────────────────────────────────────┘│
│                          │                                      │
│                          ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  Stage 2: Human Review (Optional)                           ││
│  │  - Inspect gathered resources                               ││
│  │  - Approve or abort                                         ││
│  └─────────────────────────────────────────────────────────────┘│
│                          │                                      │
│                          ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  Stage 3: Experiment Runner Agent                           ││
│  │  - Implementation & experimentation                         ││
│  │  - Analysis & documentation                                 ││
│  │  → Output: src/, results/, REPORT.md                        ││
│  └─────────────────────────────────────────────────────────────┘│
│                          │                                      │
│                          ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  Stage 4: Paper Writer Agent (Optional, --write-paper)      ││
│  │  - Generate LaTeX paper from results                        ││
│  │  - Compile to PDF                                           ││
│  │  → Output: paper_draft/main.tex, paper_draft/main.pdf       ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                   4. Results Published                          │
│                   (GitHub + Local Workspace)                    │
└─────────────────────────────────────────────────────────────────┘
```

**Key Design Decisions:**

- **Workspace-first**: GitHub repos are created immediately on idea submission, providing a persistent home for all artifacts
- **Pragmatic execution**: Agents create resources when they don't exist and always proceed rather than blocking
- **Multi-provider support**: Works with Claude, Codex, and Gemini as agent backends
- **Resumable**: Pipeline state is tracked and can resume from the last completed stage
- **Stateful execution**: `STATE.md` tracks progress, `./neurico/state.json` stores structured state
- **Validation-gated pipeline**: Each stage must produce required outputs before continuing
- **Context compression**: Phase summaries replace raw history
- **Top-K exploration control**: Agents operate on prioritized candidates instead of exploring everything
- **Working directory enforcement**: Prevent execution drift outside workspace

---

## Core Components

### Idea Manager (`src/core/idea_manager.py`)

Handles idea lifecycle management:
- **Validation**: Checks YAML against schema (required: title, domain, hypothesis)
- **ID Generation**: Creates unique IDs from timestamp + title hash
- **Status Tracking**: Moves ideas between `submitted/`, `in_progress/`, `completed/`
- **Storage**: Maintains directory structure under `ideas/`

### Pipeline Orchestrator (`src/core/pipeline_orchestrator.py`)

Manages the multi-stage execution:
- **Stage Management**: Runs resource finder, then experiment runner
- **State Persistence**: Saves progress to `.neurico/pipeline_state.json`
- **Timeout Handling**: Configurable timeouts per stage (default: 45 min / 3 hours)
- **Resume Capability**: Can restart from last completed stage
- **Validation**: Validation before progression
- **Context Management**: Context injection between stages 

### State Manager (`src/core/state_manager.py`)

Manages persistent execution state:
- **State Management**: Track stage/phase, etc. via `.neurico/state.json`, `STATE.md`

### Context Summarizer (`src/core/context_summarizer.py`)

Summarize key findsing, decision rationale, etc. via `.neurico/phase_summary.json`, `.neurico/phase_summary_<stage>.json`

### Validators (`src/core/validators.py`)

Conduct validations to:
- Ensure required outputs exist
- Ensure structure is valid 
- Ensure stage completition is trustworthy
- Prevent invalid pipeline progression

### Resource Finder Agent (`src/agents/resource_finder.py`)

Autonomous literature review and resource gathering:
- Generates specialized resource-finder prompt from idea specification
- Launches CLI agent (Claude/Codex/Gemini) with stdin pipe
- Monitors for completion marker (`.resource_finder_complete`)
- Outputs: `papers/`, `datasets/`, `code/`, `literature_review.md`, `resources.md`

### Paper Writer Agent (`src/agents/paper_writer.py`)

Generates academic papers from experiment results:
- Reads experiment outputs (REPORT.md, planning.md, literature_review.md)
- Generates paper following specified style (NeurIPS, ICML, ACL)
- Creates modular LaTeX project structure:
  - `paper_draft/main.tex` - Main file importing sections
  - `paper_draft/sections/` - Individual section files
  - `paper_draft/figures/`, `tables/`, `appendix/`
- Compiles to PDF using pdflatex/bibtex
- Verifies output structure and compilation success

### Research Runner (`src/core/runner.py`)

Main execution entry point:
- Loads idea from IdeaManager
- Sets up GitHub workspace (or local directory)
- Chooses execution mode (multi-agent pipeline or legacy monolithic)
- Runs coding agent for experiment execution
- Commits and pushes results to GitHub

### Prompt Generator (`src/templates/prompt_generator.py`)

Composes research prompts from templates:
- Loads base researcher template (universal methodology)
- Loads domain-specific template (ML, AI, Data Science, etc.)
- Renders Jinja2 templates with idea variables
- Produces layered prompt: task section + base methodology + domain guidance
- Inject current state, prior phase summary, Top-K constraints, workspace directory

### GitHub Manager (`src/core/github_manager.py`)

Handles repository operations:
- Creates repos in configured organization
- Clones to local workspace
- Commits and pushes results
- Generates concise repo names from idea titles

---

## Pipeline Flow

### 1. Submit an Idea

```bash
python src/cli/submit.py ideas/examples/ml_regularization_test.yaml
```

What happens:
1. YAML validated against schema
2. Unique idea_id generated
3. Saved to `ideas/submitted/`
4. GitHub repo created and cloned to `workspace/<repo-name>/`
5. Initial metadata committed

### 2. Run Research

```bash
python src/core/runner.py <idea_id> --provider claude --timeout 3600 --full-permissions
```

Options:
- `--provider` (claude|codex|gemini): AI backend
- `--timeout`: Experiment runner timeout in seconds
- `--full-permissions`: Allow autonomous execution
- `--pause-after-resources`: Stop for human review after resource gathering
- `--skip-resource-finder`: Jump straight to experimentation

### 3. Pipeline Execution

**Stage 1: Resource Finder** (45 min default)
- Agent searches for relevant papers, datasets, and code
- Downloads and organizes resources
- Creates `literature_review.md` synthesizing findings

**Stage 2: Human Review** (Optional)
- Inspect `papers/`, `datasets/`, `resources.md`
- Approve to continue or abort

**Stage 3: Experiment Runner** (3 hours default)
- Agent follows 6-phase methodology:
  1. Planning (hypothesis decomposition, resource review)
  2. Environment setup (venv, dependencies)
  3. Implementation (code, baselines)
  4. Experimentation (run, collect results)
  5. Analysis (statistical testing, interpretation)
  6. Documentation (REPORT.md, README.md)

**Stage 4: Paper Writer** (Optional, 1 hour default)
- Enabled with `--write-paper` flag
- Reads experiment outputs (REPORT.md, planning.md, literature_review.md)
- Generates modular LaTeX paper:
  - `paper_draft/main.tex` with `\input{}` for each section
  - `paper_draft/sections/` with individual .tex files
  - `paper_draft/references.bib`
- Compiles to PDF (requires texlive in environment)
- Supports styles: NeurIPS (default), ICML, ACL

### 4. Results

Final workspace structure:
```
workspace/<repo-name>/
├── .neurico/idea.yaml      # Original idea spec
├── .claude/skills/               # Claude Code skills (paper-finder, etc.)
├── papers/                       # Downloaded papers
├── datasets/                     # Downloaded datasets
├── code/                         # Cloned repositories
├── src/                          # Experiment Python scripts
├── results/                      # Metrics, visualizations
├── artifacts/                    # Models, checkpoints
├── logs/                         # Execution logs
├── notebooks/                    # Jupyter notebooks (with --use-scribe)
├── paper_draft/                  # LaTeX paper (with --write-paper)
│   ├── main.tex                  # Main document
│   ├── sections/                 # Individual section files
│   ├── figures/                  # Generated figures
│   └── references.bib            # Bibliography
├── REPORT.md                     # Comprehensive findings
└── README.md                     # Quick overview
```

---

## Template System

Templates live in `templates/` and use Jinja2 rendering. The `PromptGenerator` class (`src/templates/prompt_generator.py`) is the central hub for all prompt generation.

### Template Directory Structure

```
templates/
├── agents/                         # Agent-specific prompts
│   ├── session_instructions.txt    # Experiment runner workflow (phases 1-6)
│   ├── resource_finder.txt         # Resource gathering agent
│   └── paper_writer.txt            # Paper writing agent
│
├── base/
│   └── researcher.txt              # Universal research methodology
│
├── domains/                        # Domain-specific guidance
│   ├── artificial_intelligence/core.txt
│   ├── machine_learning/core.txt
│   ├── data_science/core.txt
│   └── ...
│
├── skills/                         # Claude Code skills (copied to .claude/skills/ in workspaces)
│   ├── paper-finder/               # Paper search with scripts/find_papers.py
│   ├── literature-review/          # Systematic lit review workflow
│   ├── citation-manager/           # BibTeX management
│   └── ... (10 skills total)
│
├── evaluation/                     # Critic/review prompts
│   ├── code_quality.txt
│   ├── scientific_rigor.txt
│   └── reproducibility.txt
│
├── paper_styles/                   # LaTeX templates
│   └── neurips/Styles/             # NeurIPS 2025 style files
│
└── research_agent_instructions.py  # Wrapper for backward compatibility
```

### Prompt Generation Flow

The three main agents use different prompt compositions:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PROMPT GENERATION FLOW                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  RESOURCE FINDER                EXPERIMENT RUNNER           PAPER WRITER   │
│  ─────────────────              ─────────────────           ────────────── │
│                                                                             │
│  ┌─────────────────┐           ┌─────────────────┐        ┌─────────────┐ │
│  │ Idea context    │           │ Research prompt │        │ Experiment  │ │
│  │ (title, hypo,   │           │ (from generate_ │        │ outputs     │ │
│  │  domain, etc.)  │           │  research_      │        │ (REPORT.md, │ │
│  └────────┬────────┘           │  prompt())      │        │ planning,   │ │
│           │                    └────────┬────────┘        │ lit review) │ │
│           ▼                             │                 └──────┬──────┘ │
│  ┌─────────────────┐                    ▼                        │        │
│  │ agents/         │           ┌─────────────────┐               ▼        │
│  │ resource_       │           │ base/           │        ┌─────────────┐ │
│  │ finder.txt      │           │ researcher.txt  │        │ agents/     │ │
│  └────────┬────────┘           │ + domains/      │        │ paper_      │ │
│           │                    │ <domain>/core   │        │ writer.txt  │ │
│           ▼                    └────────┬────────┘        └──────┬──────┘ │
│  generate_resource_                     │                        │        │
│  finder_prompt()                        ▼                        ▼        │
│                                ┌─────────────────┐        generate_paper_ │
│                                │ agents/         │        writer_prompt() │
│                                │ session_        │                        │
│                                │ instructions    │                        │
│                                │ .txt            │                        │
│                                └────────┬────────┘                        │
│                                         │                                 │
│                                         ▼                                 │
│                                generate_session_                          │
│                                instructions()                             │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Methods in PromptGenerator

| Method | Purpose | Template(s) Used |
|--------|---------|------------------|
| `generate_research_prompt()` | Creates task description from idea | `base/researcher.txt` + `domains/*/core.txt` |
| `generate_session_instructions()` | Wraps with execution workflow | `agents/session_instructions.txt` |
| `generate_resource_finder_prompt()` | Resource gathering instructions | `agents/resource_finder.txt` |
| `generate_paper_writer_prompt()` | Paper writing instructions | `agents/paper_writer.txt` |

### Customizing Templates

To modify agent behavior, edit the corresponding template file:

| What to Customize | File to Edit |
|-------------------|--------------|
| Experiment phases (1-6) | `templates/agents/session_instructions.txt` |
| Paper structure and format | `templates/agents/paper_writer.txt` |
| Resource finding behavior | `templates/agents/resource_finder.txt` |
| Research methodology | `templates/base/researcher.txt` |
| Domain-specific guidance | `templates/domains/<domain>/core.txt` |
| Claude Code skills | `templates/skills/<skill-name>/SKILL.md` |
| LaTeX paper style | `templates/paper_styles/<style>/` |

Templates use Jinja2 syntax for variable interpolation (e.g., `{{ prompt }}`, `{{ work_dir }}`).

---

## What We've Learned

We've been running weekly competitions since November 2025, exploring 15+ research ideas across 45+ agent runs. Here's what we've observed.

### What Agents Do Well

**Data curation with smart filtering.** When Codex filtered ChaosNLI for high human disagreement (`gini < 0.45`), it demonstrated genuine understanding of dataset structure—not just downloading data, but selecting appropriate subsets.

**Statistical rigor and faithful reporting.** Agents run proper tests with multiple comparisons correction. When experiments refute hypotheses, they report this honestly rather than spinning results.

**Contextual reasoning.** Despite instructions preferring "state-of-the-art models," agents chose GPT-2 for interpretability research because they correctly reasoned that activation access requires open-weight models. This shows appropriate contextual judgment.

**Resource finding and model training.** After our resource finder update, agents successfully download relevant papers, find datasets on HuggingFace, and even run finetuning experiments automatically.

**Exploring one direction of an idea.** Agents can take a hypothesis and pursue it to a conclusion with reasonable experimental design.

### Critical Limitations

**The Meta-Intelligence Gap.** Agents don't know when to search vs. rely on its own knowledge, when their approach is ungrounded, or which of many possible directions matters most. They can execute but can't judge. This is the hardest problem.

**Synthetic Data Problem.** Multiple agents generated synthetic data instead of collecting real data. In one case, Codex with real datasets found significant effects while Claude with synthetic data found nothing—same hypothesis, different data quality, opposite conclusions.

**Prioritization Failure.** Most existing works make the agents explore a wide range of tasks. For example, Kosmos generated 108 literature review tasks for a single idea, it demonstrated capability without prioritization. Agents can't tell you which of those tasks actually matters.

**Sample Size Issues.** Agents often use 20-30 examples when statistical power requires hundreds. They don't have intuition for adequate sample sizes.

**Ungrounded Experimental Designs.** Some agent outputs look sophisticated but lack scientific grounding—e.g., "multi-agent systems" that are just independent answers aggregated, missing fundamental aspects of how the field actually studies these problems.

**Stage-Specific Failures.** Different agents fail differently: Claude loses track of working directory, Codex gets stuck in rabbit holes during resource finding, Gemini doesn't follow full research instructions. These are trivial errors humans wouldn't make.

### Key Insight: NeuriCo as Exploration Accelerator

After testing multiple AI scientist systems (including [AI-Scientist](https://github.com/SakanaAI/AI-Scientist-v2), [AI-Researcher](https://github.com/HKUDS/AI-Researcher), and Kosmos), **we believe NeuriCo is the most useful for actually helping researchers explore ideas.** Here's why:

- **Grounded in real experiments**: Agents run actual code on real datasets, producing concrete results you can inspect and build upon
- **Good for** making ideas more concrete, thinking systematically, and providing a starting point for deeper investigation
- **Honest about limitations**: Rather than generating polished-looking reports that may be untrustworthy, we focus on transparent exploration with clear artifacts

Our long-term goal is for neurico to produce work good enough to support publishable research, but we are not there yet. We believe the path forward isn't to optimize directly for paper-writing, but to first build reliable exploration tools that help researchers accelerate their work, identify potential issues early, and make informed decisions about what to pursue next.

---

## Roadmap

Based on our learnings, we've identified five key challenges to address.

### Challenge 1: Dynamic Resource Finding

**Problem**: Agents need good resources to pursue research ideas, but they:
- Don't have good priors about what sources are reliable vs. unreliable
- Don't search diversely enough
- Don't leverage existing academic tools and APIs

**Current State**: Resource finder can download papers and datasets, but quality varies.

**Directions**:
- Expand tool use capabilities: integrate Semantic Scholar API, arXiv API, existing paper finders
- Provide source quality heuristics (citation count, venue reputation)
- Encourage diverse search strategies (different keywords, related work traversal)
- Let agents use existing libraries (scholarly, paperqa)

### Challenge 2: Research Meta-Knowledge

**Problem**: Agents lack understanding of research standards:
- When is synthetic data acceptable vs. when must you use real data?
- What sample sizes are needed for statistical power?
- What constitutes a well-grounded experimental design?
- When should you seek external sources?

**Current State**: Some methodology guidance in templates, but agents still make ungrounded choices.

**Directions**:
- Embed research methodology guidelines in domain templates
- Add explicit decision points ("Do you have real data? If not, justify why synthetic is appropriate")
- Create checklists for common pitfalls
- Research: Can we detect when agents are "outside their expertise"?

### Challenge 3: Context Management and Working Memory

**Problem**: Agents struggle to maintain coherence during long-horizon tasks:
- Losing track of working directory or task state (context drift)
- Getting stuck in rabbit holes without recognizing they've drifted
- Forgetting earlier instructions as context fills up
- Incomplete outputs due to working memory limitations

**Current State**: Solvable via careful instructions, but unclear how to generalize. 
- Updated STATE tracking 
- Implemented phase summaries
- Conducted validation to prevent incomplete execution
- Checked cwd to prevent directory drift
- Used Top-K to limit exploration

**Directions**:
- Better context curation strategies to prevent drift
- Validation checks at stage boundaries to catch errors early
- More structured output requirements (completion markers, required files)
- Research: Can we categorize common failure modes and build targeted mitigations?
- Semantic automatic drift detection via LLM judge
- Adaptive Top-K selection
- Confidence estimation and uncertainty tracking

### Challenge 4: Human Intervention & Feedback

**Problem**: Agents may take wrong turns that waste compute; no mechanism for mid-run correction.

**Current State**: Optional pause-after-resources checkpoint, but limited feedback integration.

**Directions**:
- More checkpoint opportunities during exploration
- Allow human steering without restarting entire pipeline
- Feedback integration: human corrections should inform future runs
- Support for iterative refinement (human reviews output, agent revises)

### Challenge 5: Long-horizon Experiment Execution

**Problem**: Even with good resources, experiment quality varies:
- Agents explore one direction but may not pick the best one
- Limited ablation and significance testing
- Don't know when results are inconclusive vs. definitive

**Current State**: Agents can run experiments and report, but scientific rigor varies.
- Updated validation enforcement
- Enhanced structured summaries
- Updated context management

**Directions**:
- Encourage exploration of multiple directions, not just one
- Better templates for ablation studies and statistical testing
- Explicit uncertainty quantification in conclusions
- Present trade-offs between directions for human selection

---

## Open Research Questions

These are harder problems that we don't have clear solutions for:

### 1. Measuring "Good Research Behavior"

What metrics capture research quality beyond task completion? How do we evaluate if an agent "did due diligence"? Current work like [MechEvalAgents](https://github.com/ChicagoHAI/MechEvalAgents) is exploring this space.

### 2. Metacognition and Self-Reflection

Can agents learn when to search vs. rely on training? How do we teach "knowing what you don't know"? This is fundamentally about metacognition—the ability to monitor and regulate one's own cognitive processes. Current agents lack self-reflection capabilities to recognize when they're outside their expertise or when their approach not grounded. This likely can't be solved with prompting alone—it may require architectural changes or new training approaches.

### 3. Generalizing Error Prevention

Currently, specific instructions prevent specific errors. But this creates a bias-variance tradeoff: more specific instructions mean less flexibility. How do we achieve robust behavior across diverse ideas and domains?

### 4. Supporting Human Selector/Evaluator Roles

How should agent outputs be structured for human decision-making? How do we present multiple explored directions with trade-offs? Integration with [IdeaHub](https://hypogenic.ai/ideahub) for community selection is one avenue.

### 5. Exploration Diversity vs. Reliability

As we add more scaffolding to prevent errors, agents converge on similar exploration paths. This is the bias-variance tradeoff in agentic design: more specific instructions reduce errors but also reduce the diversity of approaches tried.

This is particularly challenging because:
- Different ideas need different diversity levels (concrete ideas may be fine with one path; open-ended ideas need multiple trials)
- It's hard to evaluate what counts as "good diversity"
- The tradeoff may be fundamental to current LLM architectures

Possible directions: multi-agent ensembles with diverse personas, adaptive scaffolding based on idea openness, or mechanisms to encourage exploration of alternative hypotheses.

---

## How to Contribute

We're looking for collaborators who resonate with the vision of AI as exploration accelerators for human researchers.

**Areas of interest:**
- Tool use and resource finding (integrating academic APIs, existing searching tools)
- Evaluation systems (measuring research behavior quality)
- Context management (memory strategies, preventing drift in long-horizon tasks)
- Long-horizon reasoning (maintaining coherence across extended experiments)
- Exploration diversity (balancing reliability with diverse approaches)
- Domain templates (adding new domains, improving methodology guidance)
- Human-AI interaction (feedback loops, checkpoints, iterative refinement)

**Get started:**
- Browse [open issues](https://github.com/ChicagoHAI/neurico/issues)
- Read the [weekly competition results](https://hypogenic.ai/blog) for context on current limitations
- Try running the system on your own research ideas

**Contact:**
- Email: haokunliu@uchicago.edu
- GitHub: [ChicagoHAI/neurico](https://github.com/ChicagoHAI/neurico)
- IdeaHub: [hypogenic.ai/ideahub](https://hypogenic.ai/ideahub)

---

*Last updated: January 2026*
