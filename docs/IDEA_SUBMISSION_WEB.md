# Idea Submission Web Form

The submission web form lets you create, review, and edit research ideas in the
browser without hand-writing YAML. It is a standalone local page, independent of
the workspace-scoped HITL and interactive-manager pages. Submission goes through
the same path as the YAML command, so the result is identical to a CLI-submitted
idea and flows into every downstream mode unchanged.

## Usage

| Action | Docker | Local `uv` |
| --- | --- | --- |
| Open the submission page | not yet available | `uv run python src/cli/submit_web.py` |

The command prints a one-time token URL bound to localhost and opens your
browser. Use `--port N` to choose a port and `--no-browser` to only print the
URL.

## Submitting an idea

Title, domain, and hypothesis are the only required fields. Optional collapsible
sections cover background (description, papers, datasets), methodology
(approach, steps, baselines, metrics), and constraints (compute, time limit).
Before anything is written, a preview shows the generated YAML with validation
errors and warnings inline. Successful submission shows the `<idea_id>` and the
commands for the next step.

## Viewing and editing ideas

Existing ideas are listed with their status. Selecting one shows its YAML. Ideas
still in `submitted` status can be loaded back into the form and saved: the form
replaces only the sections it manages, and any other fields in the file (for
example `expected_outputs`, local resources, and metadata) are preserved. Ideas
a run has consumed (`in_progress`, `completed`) are view-only.

Fields without form controls survive edits but must still be written in YAML;
see the [complete Idea guide](IDEA_GUIDE.md).

After submission, choose Standard, AutoResearch, or HITL AutoResearch using the
route-specific command in [`WORKFLOW.md`](WORKFLOW.md).
