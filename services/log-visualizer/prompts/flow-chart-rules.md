# Flow Chart Rules

These rules guide agents that generate or update NeuriCo project flow charts.
The flow chart is for human review. It should explain the project process, not
mirror every raw log event.

## Core Principle

The main canvas is an explanation.
The inspector is evidence.
The raw logs are the audit trail.

Do not put raw commands, transcript mechanics, or generic event names on the
main canvas unless they are themselves the meaningful project operation.

## Data Ownership

Raw project data stays in the project run folder, for example:

```text
<run-id>/
```

Visualizer-generated data belongs to the visualizer:

```text
neurico-logvisualizer/data/
  element-library.json
  runs/
    <run-id>/
      flow-elements.json
      flow-graph.json
      layout.json
      annotations.json
```

Interpretation, layout, annotations, inferred branches, and semantic nodes are
visualizer data. They should not be written into the raw project folder.

## Two Graph Levels

Generate two conceptual levels.

### Main Story Graph

The default graph should have roughly 8-15 nodes. It should answer:

- What meaningful thing happened?
- Why did it matter?
- What did it produce?
- What later step used it?

Good nodes (these are GENERIC TEMPLATES — derive the actual title from THIS
project; never copy these words literally):

- Search for relevant prior work
- Collect the datasets and code
- Choose the dataset
- Define the experimental conditions
- Build the experiment runner
- Run the experiment
- Analyze the results
- Write the final report

Bad nodes:

- Intent
- Inspect
- Environment
- command_execution
- I confirmed the workspace root

Those may be evidence, but they are not usually main-story nodes.

### Evidence Graph / Inspector

Each main-story node should keep references to supporting logs and artifacts:

- transcript file
- item IDs
- commands
- file changes
- generated artifacts
- outputs
- errors

Show these in the inspector or an expandable detail view, not as default canvas
nodes.

## Element Library

The element library defines reusable node types. It does not define the full
chart for a project.

Recommended general-purpose types:

- Intent
- Constraint
- Plan
- Literature Search
- Dataset Search
- Data Inspection
- Method Design
- Decision
- Implementation
- Experiment Matrix
- Model Run
- Evaluation
- Analysis
- Report Writing
- Artifact
- Branch
- Parallel Track
- Failure
- Recovery
- Validation
- Handoff
- Risk
- Result

Twenty to thirty element types should be enough for most projects. Prefer adding
project-specific titles over adding too many new element types.

## Node Titles

Use human-readable project operations as titles.

Prefer titles that name the actual work in THIS project, e.g. the *shape* of:

```text
Choose the dataset
Run the experiment
Analyze the results
```

Avoid:

```text
Data
Execution
Analysis
```

The element type can be shown as a small badge. The title should say the actual
work.

## Time Order

Real-time order should be metadata, not the layout axis.

Use small monotonic badges such as:

```text
t1, t2, t3
```

The `tN` badge means the approximate order in which the semantic step happened.
It should not force the x-axis layout.

The layout should be based on logic:

```text
resources -> design -> implementation -> execution -> evaluation -> report
```

## Logical Layout

Lay out the graph by dependency and role, not by transcript order.

Typical research layout:

```text
Idea
  -> Gather resources
  -> Design experiment
  -> Build runner
  -> Run experiment
  -> Analyze results
  -> Write report
```

Typical software layout:

```text
Request
  -> Inspect code
  -> Reproduce issue
  -> Implement fix
  -> Run tests
  -> Summarize result
```

Use branches when the process has logical alternatives, parallel tracks,
factorial experiments, multiple models, multiple datasets, multiple prompts, or
fallback paths.

## Branches And Parallel Structure

Branches should represent logical structure, not merely adjacent timestamps.

Examples:

Multiple models:

```text
Run model comparison
  -> Model A
  -> Model B
  -> Baseline
```

Multiple datasets:

```text
Evaluate datasets
  -> Dataset A
  -> Dataset B
  -> Dataset C
```

Experimental matrix:

```text
Run experiment
  -> Condition A
  -> Condition B
  -> Prompt variant 1
  -> Prompt variant 2
```

Fallback or recovery:

```text
Install dependencies
  -> Failure: package build failed
  -> Recovery: add package stub
  -> Retry dependency install
```

Do not create a branch just because two log messages happened near each other.

## Collapsing And Expansion

Default to a compact story graph. Allow expansion into details.

Useful collapsed nodes:

- Gather resources
- Review papers
- Prepare datasets
- Build experiment
- Run experiment matrix
- Analyze outputs
- Write report

Expanded children may include:

- individual papers
- individual datasets
- model runs
- prompt conditions
- metrics
- generated files
- failures and recoveries

## Edge Types

Use typed edges. Recommended edge types:

- leads_to
- depends_on
- produced
- used_by
- branches_to
- validates
- failed_then
- recovered_by
- hands_off_to
- informs

Avoid making every edge mean only "next".

## Quality Checklist

Before accepting a generated flow chart, check:

- Can a human understand the project in under one minute?
- Does the main chart have roughly 8-15 meaningful nodes?
- Are raw logs hidden behind evidence references?
- Are branches based on project logic, not time order?
- Are failures and recoveries visible when they affected the path?
- Are important artifacts connected to the steps that produced or used them?
- Are `tN` badges metadata only, not the layout axis? 
- Are node titles specific to the project?
- Can the user move boxes without losing the default generated layout?

## For This Visualizer

The visualizer should store:

- semantic elements in `flow-elements.json`
- logical relationships in `flow-graph.json`
- user-adjusted positions in `layout.json`
- reviewer notes and corrections in `annotations.json`
- reusable element definitions in `element-library.json`

Future agents should read this file before changing flow-chart generation or
layout behavior.
