# NeuriCo Idea Quickstart

This guide is for someone writing a NeuriCo idea for the first time. An idea is
a short YAML research brief: it tells NeuriCo what to investigate, not what
conclusion it must reach.

For every supported field and domain, see
[`IDEA_GUIDE.md`](IDEA_GUIDE.md).

## What an idea needs

Only three fields are required:

1. a descriptive title;
2. a research domain; and
3. a neutral, testable hypothesis.

NeuriCo can investigate missing details such as papers, datasets, baselines,
metrics, and experimental methodology.

## 1. Create the idea file

Create `ideas/my_idea.yaml`. Both Docker and local `uv` accept relative or
absolute host paths; `ideas/` is simply the recommended project location.

```yaml
idea:
  title: "Titanic Survival Prediction"
  domain: machine_learning
  hypothesis: >
    Passenger demographic and ticket-related features predict Titanic survival
    better than a majority-class baseline on held-out passengers.
```

This is a complete submission-ready idea. Extra sections are optional.

## 2. Choose the closest domain

Common choices include:

| Research centers on | Domain key |
| --- | --- |
| LLMs, prompting, or AI agents | `artificial_intelligence` |
| Training or comparing predictive models | `machine_learning` |
| Statistical analysis or visualization | `data_science` |
| Traditional non-LLM text processing | `nlp` |
| Images or visual recognition | `computer_vision` |
| Reinforcement-learning policies and environments | `reinforcement_learning` |
| Systems, databases, networks, or compilers | `systems` |
| Numerical methods or simulations | `scientific_computing` |
| Human-written mathematical proofs | `mathematics` |
| Machine-checked Lean proofs | `mathematics_lean` |

See [`config/domains.yaml`](../config/domains.yaml) for the complete current
list. Choose the domain that best matches the methods and evaluation, not only
the subject vocabulary.

## 3. Make the hypothesis testable

A good hypothesis can be supported, contradicted, or qualified by evidence.

Too vague:

```yaml
hypothesis: "Study survival prediction."
```

Biased toward a required conclusion:

```yaml
hypothesis: "Prove that the new model is best."
```

Neutral and measurable:

```yaml
hypothesis: >
  A classifier using passenger demographics and ticket information predicts
  survival better than a majority-class baseline on held-out data.
```

## 4. Add only real boundaries

Optional fields should communicate information NeuriCo must preserve, not fill
space with guesses. For example:

```yaml
idea:
  title: "Titanic Survival Prediction"
  domain: machine_learning
  hypothesis: >
    Passenger demographic and ticket-related features predict Titanic survival
    better than a majority-class baseline on held-out passengers.

  constraints:
    compute: cpu_only
    time_limit: 3600
    budget: 0

  evaluation_criteria:
    - "All methods are evaluated on the same held-out passengers."
    - "Saved artifacts reproduce the reported metrics."
```

If you do not know the right paper, dataset, baseline, or metric, omit it and
let NeuriCo investigate it.

## First-idea checklist

Before submission, confirm that:

- the title names the research clearly;
- the domain is the closest configured match;
- the hypothesis is neutral and measurable;
- hard compute, time, memory, and budget limits are explicit;
- optional fields contain known information rather than invented details; and
- YAML indentation uses spaces consistently.

## 5. Submit the idea

The following examples keep the workspace local and require no GitHub token:

```bash
# Docker
./neurico submit ideas/my_idea.yaml --no-github

# Local uv
uv run python src/cli/submit.py ideas/my_idea.yaml --no-github
```

NeuriCo validates the file and prints an ID similar to:

```text
titanic_survival_prediction_20260729_120000_a1b2c3d4
```

Keep this `<idea_id>`. Submission does not start research; use the ID afterward
to choose Standard, AutoResearch, or HITL AutoResearch from the main
[`README`](../README.md#3-choose-a-research-mode).

To create a GitHub repository during submission, configure `GITHUB_TOKEN` and
omit `--no-github`.
