# Writing Research Ideas for NeuriCo

This guide explains how to turn a research question into an idea YAML that
NeuriCo can validate, submit, and run. It is the human-readable companion to the
authoritative [`ideas/schema.yaml`](../ideas/schema.yaml).

For a shorter introduction, see
[`IDEA_QUICKSTART.md`](IDEA_QUICKSTART.md).

## What an idea controls

An idea is the research brief for a NeuriCo workspace. It tells the system:

- what question to investigate;
- which domain should guide the work;
- which resources or methods are already known;
- which execution limits must be respected;
- how evaluation must be performed, when the user already has a contract; and
- what evidence and artifacts should be produced.

Only `title`, `domain`, and `hypothesis` are required. NeuriCo can discover
papers and datasets, select baselines and metrics, and design methodology when
those details are omitted.

## Minimal valid idea

```yaml
# ideas/my_idea.yaml
idea:
  title: "Titanic Survival Prediction"
  domain: machine_learning
  hypothesis: >
    Passenger demographic and ticket-related features predict Titanic survival
    better than a majority-class baseline on held-out passengers.
```

Add optional fields only when they express useful context, a known resource, a
hard requirement, or an evaluation expectation.

## Required fields

### `title`

A title must be 10–200 characters. Name the subject and comparison or objective;
avoid process labels such as “Test idea” or “New experiment.”

```yaml
title: "Impact of L2 Regularization on Small Dataset Generalization"
```

### `domain`

Use the closest key from [`config/domains.yaml`](../config/domains.yaml):

| Domain key | Intended research |
| --- | --- |
| `artificial_intelligence` | LLMs, prompting, AI agents, and AI benchmarks |
| `machine_learning` | Model training, prediction, clustering, and evaluation |
| `data_science` | Statistical analysis, forecasting, and visualization |
| `nlp` | Traditional non-LLM text-processing tasks |
| `computer_vision` | Image processing, detection, segmentation, and visual analysis |
| `reinforcement_learning` | Policies, rewards, environments, and RL agents |
| `systems` | Performance, distributed systems, databases, networks, and compilers |
| `theory` | Algorithms, complexity, optimization, and formal analysis |
| `mathematics` | Pure or applied mathematics and human-written proofs |
| `mathematics_lean` | Formal mathematics verified with Lean 4 and Mathlib |
| `finance` | Empirical finance, banking, asset pricing, and panel analysis |
| `battery` | Electrochemical storage, electrodes, electrolytes, and related devices |
| `scientific_computing` | Numerical methods, simulations, and computational science |
| `particle_physics` | Testable beyond-the-Standard-Model particle physics |

Unknown domains fall back to the configured default, but an exact key selects
the intended domain instructions and paper style.

### `hypothesis`

The hypothesis must contain at least 20 characters. It should name the subject
or variables, identify a measurable relationship or comparison, and allow the
result to support, contradict, or qualify it.

```yaml
hypothesis: >
  L2-regularized classifiers have a smaller train-validation performance gap
  than otherwise identical unregularized classifiers on datasets with fewer
  than 1,000 training examples.
```

Avoid statements that require a preferred result, such as “Prove that our new
method is the best.”

## Optional fields

### `max_directions`

Controls how many research directions can enter experimentation. It accepts
integers from 1 to 10 and defaults to 3.

```yaml
max_directions: 2
```

### `background`

Use `background` for context and resources already selected by the user:

```yaml
background:
  description: "Context and motivation for the research."
  papers:
    - url: "https://arxiv.org/abs/..."
      description: "Why this paper is relevant."
    - path: "references/local-paper.pdf"
      description: "Why this local paper is relevant."
  datasets:
    - name: "Dataset name"
      source: "huggingface:organization/dataset"
      description: "What the dataset contains."
  code_references:
    - repo: "https://github.com/organization/repository"
      description: "What this implementation provides."
      branch: "main"
```

Each paper needs a URL or local path plus a description. Each dataset needs a
name and source. Each code reference needs a repository and description. Omit a
resource list when NeuriCo should discover that resource.

### `methodology`

Use methodology when the research must follow a particular approach, sequence,
baseline, or metric:

```yaml
methodology:
  approach: "Controlled comparison using a fixed train-validation split"
  steps:
    - "Prepare the dataset without using validation labels for training."
    - "Train baseline and candidate methods."
    - "Evaluate both methods on identical held-out examples."
  baselines:
    - "Majority-class prediction"
    - "TF-IDF with logistic regression"
  metrics:
    - "Macro F1"
    - "Accuracy"
```

Treat this block as binding guidance, not a place to predict the conclusion.

### `constraints`

Constraints express hard execution boundaries:

| Field | Accepted value |
| --- | --- |
| `compute` | `cpu_only`, `gpu_required`, `multi_gpu`, `tpu`, or `any` |
| `time_limit` | 60–86,400 seconds; schema default `3600` |
| `memory` | Integer followed by `MB` or `GB`, such as `8GB` |
| `budget` | Non-negative USD amount |
| `dependencies` | Required Python packages or system libraries |

```yaml
constraints:
  compute: cpu_only
  time_limit: 7200
  memory: "8GB"
  budget: 0
  dependencies:
    - "scikit-learn"
    - "pandas"
```

### `expected_outputs`

Every expected output needs a `type` and `format`. Supported types are
`metrics`, `visualization`, `model`, `dataset`, `report`, `code`, and `analysis`.

```yaml
expected_outputs:
  - type: metrics
    format: json
    fields: [macro_f1, accuracy]
    description: "Held-out evaluation metrics."
  - type: report
    format: markdown
    description: "Methods, results, error analysis, and limitations."
```

### `evaluation_criteria`

Use free-form criteria for validity, reproducibility, coverage, or measurable
quality:

```yaml
evaluation_criteria:
  - "All compared methods use the same held-out examples."
  - "Metrics can be reproduced from saved code and configuration."
  - "The report discusses failures and limitations."
```

Avoid criteria that force a positive conclusion.

### `local_resources`

Use `local_resources` for datasets and Python functions that already exist on
the machine running NeuriCo. These are contractual inputs rather than advisory
references. They are staged into the workspace before agents run.

```yaml
local_resources:
  datasets:
    - path: "/data/fixed_protocol"
      name: "protocol_data"
      usage: "Use this exact copy for training and evaluation."
  functions:
    - path: "/home/user/eval_tools/protocol_eval.py"
      entrypoint: "evaluate_protocol"
      usage: "Compute the official protocol score."
      required_for_evaluation: true
```

Docker records declared paths during submission and mounts them read-only when
research starts. See
[`LOCAL_IDEA_SUBMISSION.md`](LOCAL_IDEA_SUBMISSION.md).

### `evaluation`

Use structured `evaluation` when exact metric names, definitions, targets, or
result shapes must be preserved in the scoring contract:

```yaml
evaluation:
  metrics:
    - name: "test_accuracy"
      definition: "Mean held-out accuracy over three fixed seeds"
      target: ">= 0.915"
    - name: "macro_f1"
      definition: "Macro F1 on the held-out split"
  results_format: "JSON object keyed by metric name"
```

Targets are optional. If omitted, the rule maker may derive one and records it
as derived rather than user-authored.

### `metadata`

Optional metadata can include `author`, `tags`, `priority`,
`estimated_duration`, and `related_ideas`. NeuriCo adds IDs, status, and
timestamps during submission.

```yaml
metadata:
  author: "Research Group"
  tags: [claim-verification, classification]
  priority: medium
```

### `comments`

`comments` describes targeted changes to an existing workspace used with
`--comment-mode`. It is normally omitted from a new research idea.

## Complete template

Remove every optional block that does not express a real requirement or known
resource:

```yaml
idea:
  title: "<clear research title>"
  domain: "<configured domain key>"
  hypothesis: >
    <specific, neutral, and testable question or claim>

  max_directions: 3

  background:
    description: "<context and motivation>"
    papers:
      - url: "<paper URL>"
        description: "<why it is relevant>"
    datasets:
      - name: "<dataset name>"
        source: "<URL, registry ID, or local path>"
        description: "<what it contains>"
    code_references:
      - repo: "<repository URL or local path>"
        description: "<what it provides>"

  methodology:
    approach: "<high-level approach>"
    steps: ["<first step>", "<next step>"]
    baselines: ["<comparison method>"]
    metrics: ["<evaluation metric>"]

  constraints:
    compute: cpu_only
    time_limit: 3600
    memory: "8GB"
    budget: 0
    dependencies: ["<required dependency>"]

  expected_outputs:
    - type: metrics
      format: json
      fields: ["<required field>"]
      description: "<what the artifact should contain>"

  evaluation_criteria:
    - "<validity, reproducibility, or quality criterion>"

  metadata:
    author: "<optional author>"
    tags: ["<tag>"]
    priority: medium
```

## Validate and submit

Keeping idea files under `ideas/` is recommended for organization. Docker and
local `uv` also accept other relative or absolute host paths:

```bash
# Docker
./neurico submit ideas/my_idea.yaml --no-github

# Local uv
uv run python src/cli/submit.py ideas/my_idea.yaml --no-github
```

Submission loads the YAML, validates required fields and constraints, creates a
durable idea record, and prints the generated `<idea_id>`. Keep validation
enabled; `--no-validate` is intended for development and can create records
that later stages cannot interpret.

Configure `GITHUB_TOKEN` and omit `--no-github` when submission should also
create a research repository.

After submission, choose Standard, AutoResearch, or HITL AutoResearch from the
main [`README`](../README.md#3-choose-a-research-mode).

## Common mistakes

- **The hypothesis requires a desired conclusion.** Write a comparison that can
  fail instead of asking NeuriCo to prove superiority.
- **Preferences are written as hard constraints.** Put methods in `methodology`;
  reserve `constraints` for boundaries that must not be violated.
- **The domain is too broad.** Use `nlp` for traditional text processing and
  `artificial_intelligence` for LLM, prompting, or agent research.
- **Evaluation leaks training data.** State held-out or private evaluation
  boundaries explicitly when leakage would invalidate the result.
- **Optional fields contain guesses.** Omit unknown papers, datasets, baselines,
  and metrics so NeuriCo can investigate them.
- **YAML values use the wrong type.** `budget` is numeric, `time_limit` is an
  integer number of seconds, and output and criteria blocks are lists.

When this guide and the implementation differ, use
[`ideas/schema.yaml`](../ideas/schema.yaml) for fields and validation rules and
[`config/domains.yaml`](../config/domains.yaml) for domain keys.
