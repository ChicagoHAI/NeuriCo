# Multi-Agent Research Pipeline Implementation

## Overview

This document describes the implementation of the multi-agent research pipeline architecture for the NeuriCo system.

## Architecture

The system has been refactored from a single monolithic agent to a multi-agent pipeline with two specialized agents:

### 1. Resource Finder Agent (CLI-based)
- **Purpose**: Literature review, resource gathering, and data collection
- **Technology**: Direct CLI agent (Claude Code, Codex, or Gemini) without scribe
- **Duration**: ~45 minutes (configurable)
- **Outputs**:
  - `literature_review.md`: Comprehensive synthesis of research papers
  - `resources.md`: Catalog of all resources with locations
  - `papers/`: Downloaded research papers (PDFs)
  - `datasets/`: Downloaded datasets
  - `code/`: Cloned repositories with baseline implementations
  - `.resource_finder_complete`: Completion marker file

### 2. Experiment Runner Agent (Scribe-based)
- **Purpose**: Implementation, experimentation, analysis, and documentation
- **Technology**: Scribe wrapper (provides Jupyter notebook integration)
- **Duration**: ~3 hours (configurable)
- **Phases**: 1-6 (Planning → Implementation → Experiments → Analysis → Documentation → Validation)
- **Outputs**:
  - `REPORT.md`: Final research report
  - `README.md`: Project overview
  - Jupyter notebooks with experiments
  - Results and visualizations

## Context Management

The pipeline includes explicit working memory and validation layers:

### 1. State Tracking

Each run tracks current stage and phase, completed steps, key findings, next steps and failure/recovery signals by tracking:
- workspaces/<run_id>/STATE.md
- .neurico/state.json


### 2. Phase Summarization

After each stage summarizes key findings, decision rationale, constraints and failures, next steps, top-k candidates by generating:
- .neurico/phase_summary.json
- .neurico/phase_summary_<stage>.json

### 3. Top-K Prioritization

Agents are constrained to top-k most promising directions to reduce exploration noise, improve focus and control cost.

### 4. Validation Before Progression

Each stage must pass validation before continuing. If validation fails, pipeline halts or marks recoverable failure and prevents silent downstream errors.

### 5. Working Directory Enforcement

Before each stage, check current working directory against expected workspace. If mismatch, record it in STATE.md and halt or flag execution.


## Implementation Details

### New Files Created

1. **`templates/agents/resource_finder.txt`**
   - Comprehensive prompt template for resource finding agent
   - Instructions for literature search, paper download, dataset search, and code cloning
   - Structured output specifications

2. **`src/agents/__init__.py`**
   - Module initialization for agents package

3. **`src/agents/resource_finder.py`**
   - Resource finder agent launcher
   - CLI command mapping for different providers
   - Prompt generation from template + idea specification
   - Completion detection and output validation
   - Timeout handling and error recovery

4. **`src/core/pipeline_orchestrator.py`**
   - `PipelineState`: Tracks pipeline execution state in `.neurico/pipeline_state.json`
   - `ResearchPipelineOrchestrator`: Manages multi-agent workflow
   - Stage execution and monitoring
   - Optional human review checkpoint
   - Resume capability for interrupted pipelines
   - Integrate state tracking, validation, and summarization
   - Inject context into each stage

5. **`src/core/state_manager.py`**
   - `StateManager`: Manage persistent execution state in `STATE.md`, `./neurico/state.json`
   - Track stage, phase, progress, and failures
   - Maintain history and snapshots for reproducibility

6. **`src/core/context_summarizer.py`**
   - Generate phase summaries after each stage
   - Extract key findings, constraints, and decision rationale
   - Produce Top-K prioritized candidates for next stage
   - Write `./neurico/phase_summary.json` and stage-specific summaries

7. **`src/core/validators.py`**
   - Validate stage outputs before progression
   - Enforce required artifacts (e.g., literature review, report, etc.)
   - Prevent invalid or incomplete stages from continuing

### Modified Files

1. **`templates/base/researcher.txt`**
   - Removed Phase 0 (literature review) - now handled by Resource Finder
   - Added preamble about pre-gathered resources
   - Updated Phase 1 (Planning) to reference available resources
   - Renumbered phases accordingly
   - Emphasized structured reasoning and validation

2. **`templates/research_agent_instructions.py`**
   - Removed entire Phase 0 section (150+ lines)
   - Added resource awareness instructions
   - Updated execution workflow to start with resource review
   - Changed phase numbering from 0-6 to 1-6
   - Updated all references to leverage pre-gathered resources
   - Updated to include:
     - state awareness
     - workspace constraints
     - Top-K prioritization rules
   - Guided agents to follow structured execution flow

3. **`src/core/runner.py`**
   - Updated `run_research()` signature with multi-agent parameters
   - Added conditional execution: multi-agent pipeline vs legacy monolithic
   - Created `_finalize_research()` helper method for GitHub integration and status updates
   - Integrated `ResearchPipelineOrchestrator` for multi-agent mode
   - Added CLI flags:
     - `--legacy-mode`: Use old monolithic approach
     - `--pause-after-resources`: Enable human review checkpoint
     - `--skip-resource-finder`: Skip resource gathering if already done
     - `--resource-finder-timeout`: Configure resource finder timeout
   - Updated to use state-aware pipeline execution
   - Added working directory checks before each stage
   - Handled validation failures and recovery states
   - Ensured context (state + summaries) is passed across stages

4. **`src/agents/resource_finder.py`**
   - Integrated with validation system to ensure required outputs exist
   - Generated structured outputs for downstream stages
   - Worked with context summarizer to produce Top-K candidates
   - Improved completion detection and robustness

5. **`src/templates/prompt_generator.py`**
   - Injected execution context into prompts:
     - current state (STATE.md)
     - prior phase summaries
     - Top-K prioritization constraints
     - workspace directory
   - Enabled context-aware and state-grounded agent behavior

6. **`templates/agents/resource_finder.txt`**
   - Refined output requirements to align with validation checks
   - Ensured consistent structure for downstream processing

## Usage

### Default Mode (Multi-Agent Pipeline)

```bash
python src/core/runner.py <idea_id> --provider claude
```

This will:
1. Launch Resource Finder agent (45 min)
2. Automatically proceed to Experiment Runner (3 hours)
3. Commit results to GitHub

### With Human Review Checkpoint

```bash
python src/core/runner.py <idea_id> --provider claude --pause-after-resources
```

This will:
1. Launch Resource Finder agent
2. **PAUSE** and wait for human approval
3. Only proceed to Experiment Runner after user confirms

### Skip Resource Finding

If resources have already been gathered (e.g., manually or from previous run):

```bash
python src/core/runner.py <idea_id> --provider claude --skip-resource-finder
```

### Legacy Monolithic Mode

To use the old single-agent approach (includes Phase 0):

```bash
python src/core/runner.py <idea_id> --provider claude --legacy-mode
```

### Adjust Timeouts

```bash
python src/core/runner.py <idea_id> \\
    --provider claude \\
    --resource-finder-timeout 3600 \\  # 1 hour for resource finding
    --timeout 7200                     # 2 hours for experiments
```

## CLI Command Mapping

The Resource Finder agent uses direct CLI commands (not scribe):

| Provider | Command | Full Permissions Flag |
|----------|---------|----------------------|
| Claude   | `claude` | `--dangerously-skip-permissions` |
| Codex    | `codex` | `--yolo` |
| Gemini   | `gemini` | `--yolo` |

The Experiment Runner continues to use scribe for Jupyter integration:

| Provider | Command | Full Permissions Flag |
|----------|---------|----------------------|
| All | `scribe <provider>` | Same as above |

## Pipeline State Management

Pipeline state is tracked in `.neurico/pipeline_state.json`:

```json
{
  "created_at": "2025-01-22T10:30:00",
  "current_stage": "experiment_runner",
  "stages": {
    "resource_finder": {
      "status": "completed",
      "started_at": "2025-01-22T10:30:00",
      "completed_at": "2025-01-22T11:15:00",
      "success": true,
      "outputs": {
        "literature_review": "/path/to/literature_review.md",
        "resources_catalog": "/path/to/resources.md",
        ...
      }
    },
    "experiment_runner": {
      "status": "in_progress",
      "started_at": "2025-01-22T11:15:30",
      ...
    }
  },
  "completed": false
}
```

## Completion Detection

The Resource Finder agent creates a `.resource_finder_complete` marker file when finished:

```
Resource finding phase completed successfully.
Timestamp: 2025-01-22T11:15:00
Papers downloaded: 7
Datasets downloaded: 2
Repositories cloned: 3
```

The orchestrator polls for this file to know when to proceed to the next stage. It also uses this file together with validation checks.

## Error Handling

### Resource Finder Failures

If the Resource Finder fails:
1. Error is logged to `logs/resource_finder_<provider>.log`
2. Pipeline stops and reports failure
3. User can:
   - Review logs and fix issues
   - Manually add resources and re-run with `--skip-resource-finder`
   - Retry the resource finding stage
4. Validation prevents progression

### Experiment Runner Failures

If the Experiment Runner fails:
1. Error is logged to `logs/execution_<provider>.log`
2. Pipeline completes with `success: false`
3. Results are still committed to GitHub with "⚠️  Completed with issues" status
4. State is marked in STATE.md

### Resume Capability

The orchestrator supports resuming interrupted pipelines:

```python
orchestrator.resume_pipeline(
    idea=idea,
    provider="claude"
)
```

This checks `pipeline_state.json` and skips already-completed stages.

Pipeline can resume from saved state:
- skip completed stages
- reuses validated outputs

## Benefits of Multi-Agent Architecture

1. **Separation of Concerns**: Literature review vs experimentation are distinct tasks
2. **Better Tool Selection**: CLI agents for file operations, Scribe for Jupyter notebooks
3. **Improved Reliability**: Smaller, focused agents with specific completion criteria and validation
4. **Resource Reuse**: Downloaded resources can be reviewed and reused across runs
5. **Human Oversight**: Optional checkpoint for reviewing resources before expensive experiments
6. **Parallel Potential**: Future work could run resource finding for multiple ideas in parallel
7. **Modularity**: Easy to add new agents (e.g., experiment planner, critic agents)
8. **Context continuity**: Summaries are injected to prompts to keep context focused
9. **Controlled exploration via top-k**: Focus on top-k directions
10. **Reproducibility**: Record structured state

## Backward Compatibility

The `--legacy-mode` flag ensures backward compatibility with the original monolithic approach. This is useful for:
- Comparing old vs new architecture
- Simple projects where multi-agent overhead isn't needed
- Debugging issues specific to the new pipeline

## Future Enhancements

Potential improvements based on NEXT_STEPS.md:

1. **Experiment Planner Agent**: Separate planning from execution
2. **Critic Agents**: Automated quality assurance and validation
3. **Environment Setup Agent**: Dedicated agent for dependency management
4. **Parallel Resource Finding**: Gather resources for multiple ideas concurrently
5. **Caching**: Reuse downloaded papers and datasets across projects
6. **Smart Resumption**: More granular checkpointing within each stage
7. **Automated Drift Detection**: Apply LLM judge
8. **Adaptive Top-K Selection**: Optimize top-k algorithms

## Testing

Before merging to main, test the following scenarios:

1. ✓ Multi-agent pipeline end-to-end (default mode)
2. ✓ Multi-agent with human review checkpoint
3. ✓ Skip resource finder mode
4. ✓ Legacy monolithic mode
5. ✓ Error handling (resource finder timeout, experiment runner failure)
6. ✓ Resume capability
7. ✓ GitHub integration with multi-agent pipeline
8. ✓ Different providers (Claude, Codex, Gemini)

## Migration Guide

For existing workflows:

### Before (Monolithic)
```bash
python src/core/runner.py idea_123 --provider claude
# Single agent handles all 7 phases (0-6) including literature review
```

### After (Multi-Agent, Default)
```bash
python src/core/runner.py idea_123 --provider claude
# Stage 1: Resource Finder (literature, datasets, code)
# Stage 2: Experiment Runner (phases 1-6)
```

### After (Legacy Mode)
```bash
python src/core/runner.py idea_123 --provider claude --legacy-mode
# Same as before - single agent, all 7 phases
```

## Summary

The multi-agent architecture successfully separates resource finding from experimentation, providing:
- **Clearer separation of concerns**
- **Better tool utilization** (CLI agents vs Scribe)
- **Optional human oversight**
- **Backward compatibility via legacy mode**
- **Foundation for future enhancements**
- **Stateful execution**
- **Validated stage transitions**
- **Context-aware reasoning**
- **Controlled exploration**

All changes maintain the existing API and workflow while adding new capabilities through optional flags.
