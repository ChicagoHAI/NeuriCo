# NeuriCo Documentation

This index separates supported user guidance from developer, internal, and
legacy material. New users should begin with the main
[`README`](../README.md#start-here) or the
[`Workflow Guide`](WORKFLOW.md).

## User documentation

These documents describe the current supported NeuriCo workflow.

| Guide | Purpose |
| --- | --- |
| [`WORKFLOW.md`](WORKFLOW.md) | Complete Docker and local `uv` workflow: setup, submission, and mode selection |
| [`IDEA_QUICKSTART.md`](IDEA_QUICKSTART.md) | Five-minute guide to a first valid idea |
| [`IDEA_GUIDE.md`](IDEA_GUIDE.md) | Complete field-by-field idea-writing reference |
| [`AUTORESEARCH.md`](AUTORESEARCH.md) | Starting, continuing, and recovering AutoResearch |
| [`HITL_AUTORESEARCH.md`](HITL_AUTORESEARCH.md) | HITL interfaces, manager workflow, frontier, and recovery |
| [`LOCAL_IDEA_SUBMISSION.md`](LOCAL_IDEA_SUBMISSION.md) | Markdown ideas, local datasets, functions, and evaluation contracts |
| [`IDEAHUB_INTEGRATION.md`](IDEAHUB_INTEGRATION.md) | Fetching and submitting IdeaHub ideas |
| [`GITHUB_INTEGRATION.md`](GITHUB_INTEGRATION.md) | Optional repository creation and publishing |
| [`../config/paper_finder.md`](../config/paper_finder.md) | Optional paper-finder configuration |

The supported user-facing research modes are Standard, AutoResearch, and HITL
AutoResearch. HITL web and terminal are two interfaces for the same HITL mode.

## Developer and internal documentation

These documents describe implementation details, design decisions, verification
notes, or future work. They are not setup instructions and may be revised,
merged, or removed during the planned developer-document sweep.

| Document | Classification |
| --- | --- |
| [`ARCHITECTURE_AND_ROADMAP.md`](ARCHITECTURE_AND_ROADMAP.md) | Architecture, project direction, and roadmap |
| [`MULTI_AGENT_IMPLEMENTATION.md`](MULTI_AGENT_IMPLEMENTATION.md) | Multi-agent pipeline implementation notes |
| [`WORKSPACE_DIRECTORY_CONSISTENCY.md`](WORKSPACE_DIRECTORY_CONSISTENCY.md) | Workspace execution-path verification |
| [`DOCKER_PERMISSIONS.md`](DOCKER_PERMISSIONS.md) | Docker mount and permission design |
| [`NEXT_STEPS.md`](NEXT_STEPS.md) | Proposed future work |
| [`../templates/README.md`](../templates/README.md) | Prompt-template and skill implementation reference |

## Legacy documentation

| Document | Purpose |
| --- | --- |
| [`INTERACTIVE_MODE_GUIDE.md`](INTERACTIVE_MODE_GUIDE.md) | Instructions for the older interactive command |
| [`INTERACTIVE_WEB_CHANGES.md`](INTERACTIVE_WEB_CHANGES.md) | Historical implementation notes for its browser interface |

These documents are retained for historical reference but are not part of the
current user workflow. Use HITL AutoResearch through `hitl-web` or `hitl-cli`
instead.

## Classification policy

- The main README links directly only to current user documentation.
- Developer and internal documents must identify themselves as such near the
  top of the file.
- Legacy documents must state that they are not current user guidance.
- Moving and consolidating developer files is deferred to the dedicated
  developer-document sweep; this index preserves existing paths in the meantime.
