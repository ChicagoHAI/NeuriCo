# Workspace Directory Consistency - Verification

## Summary

Both the Resource Finder and Experiment Runner agents are configured to run in the workspace directory with consistent `cwd` settings and clear instructions.

Workspace consistency is enforced through:
- STATE tracking (`STATE.md`)
- explicit working directory checks
- stage-level validation before progression

## Process Execution Configuration

All three agent execution paths use `cwd=str(work_dir)` to start processes in the workspace:

### 1. Resource Finder Agent
**File**: `src/agents/resource_finder.py` (line 229)
```python
process = subprocess.Popen(
    shlex.split(cmd),
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    env=env,
    text=True,
    bufsize=1,
    cwd=str(work_dir)  # ✅ Runs in workspace
)
```

### 2. Experiment Runner Agent (Multi-Agent Mode)
**File**: `src/core/pipeline_orchestrator.py` (line 387)
```python
process = subprocess.Popen(
    shlex.split(cmd),
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    env=env,
    text=True,
    bufsize=1,
    cwd=str(self.work_dir)  # ✅ Runs in workspace
)
```

### 3. Legacy Monolithic Agent
**File**: `src/core/runner.py` (line 358)
```python
process = subprocess.Popen(
    shlex.split(cmd),
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    env=env,
    text=True,
    bufsize=1,
    cwd=str(work_dir)  # ✅ Runs in workspace
)
```
## Runtime Enforcement

Workspace consistency is actively enforced at runtime.

### 1. Working Directory Check

Before each stage:

```python
check_working_directory(expected_dir, actual_dir)

If mismatch: state is marked as failure, execution is halted or flagged as recoverable.
```

### 2. State Integration

All directory-related issues are recorded in:
- workspaces/<run_id>/STATE.md
- .neurico/state.json

### 3. Stage Validation Dependency

Each stage must:
- produce outputs in the workspace
- pass validation checks

Otherwise:
- pipeline does NOT proceed
- prevents downstream failures caused by wrong directories

## Agent Instructions

Both agent templates explicitly tell the agent about the workspace directory:

### Resource Finder Template
**File**: `templates/agents/resource_finder.txt` (lines 7-18)

```
IMPORTANT: WORKSPACE SETUP
────────────────────────────────────────────────────────────────────────────────
You are already running in the project workspace directory. All files and
directories you create will be saved here automatically.

DO NOT use cd or change directories - you are already in the correct location.
All paths are relative to your current working directory (the workspace).

For example:
- Create papers/paper1.pdf → saves in workspace/papers/paper1.pdf
- Create datasets/data.csv → saves in workspace/datasets/data.csv
- Create literature_review.md → saves in workspace/literature_review.md
```

**Output Deliverables** (line 31):
```
OUTPUT DELIVERABLES (all saved in current workspace):
- papers/ directory with downloaded PDFs
- datasets/ directory with downloaded data
- code/ directory with cloned repositories
- literature_review.md (comprehensive synthesis of papers)
- resources.md (catalog of all resources with locations and descriptions)
- .resource_finder_complete (marker file indicating completion)
```

### Experiment Runner Template
**File**: `templates/research_agent_instructions.py` (lines 247-263)

```python
WORKSPACE DIRECTORY:
────────────────────────────────────────────────────────────────────────────────
You are already running in the project workspace directory: {work_dir}

All files and directories you create will be saved here automatically.
DO NOT use cd or change directories - you are already in the correct location.
All paths are relative to your current working directory (the workspace).

Remember:
- READ literature_review.md and resources.md first (they're in your current directory)
- Use pre-downloaded datasets from datasets/ directory (relative to current directory)
- Leverage code from code/ directory (relative to current directory)
- Use Jupyter notebooks for experiments and analysis (saved in current directory)
- Use markdown files (.md) for documentation (saved in current directory)
- Save outputs to organized directories: results/, figures/, logs/ (all relative)
- All your work stays within this workspace directory
```

## Expected Workspace Structure

After both agents complete, the workspace should contain:

```
workspace/
├── STATE.md
├── .neurico/
│   ├── state.json                    # Phase state
│   └── state_history.json            # Record state
│   └── phase_summary.json            # Phase summary
│   └── phase_summary_<stage>.json    # Stage summary
│   └── pipeline_state.json           # Orchestrator state
│   └── pipeline_results.json         # Final results
├── .resource_finder_complete         # Completion marker
├── papers/
│   ├── paper1.pdf
│   ├── paper2.pdf
│   └── README.md
├── datasets/
│   ├── dataset1/
│   ├── dataset2/
│   └── README.md
├── code/
│   ├── repo1/
│   ├── repo2/
│   └── README.md
├── notebooks/
│   └── experiment_*.ipynb            # Generated by scribe
├── results/
│   ├── metrics.json
│   └── plots/
├── figures/
│   └── *.png
├── logs/
│   ├── resource_finder_claude.log
│   ├── execution_claude.log
│   ├── research_prompt.txt
│   └── session_instructions.txt
├── literature_review.md              # From Resource Finder
├── resources.md                      # From Resource Finder
├── planning.md                       # From Experiment Runner
├── REPORT.md                         # From Experiment Runner
├── README.md                         # From Experiment Runner
└── pyproject.toml                    # From Experiment Runner
```

## Verification Checklist

✅ **Process Execution**
- Resource Finder: `cwd=str(work_dir)` ✓
- Experiment Runner (orchestrator): `cwd=str(self.work_dir)` ✓
- Legacy Runner: `cwd=str(work_dir)` ✓

✅ **Agent Instructions**
- Resource Finder: Explicit workspace instructions ✓
- Experiment Runner: Explicit workspace instructions ✓
- Both emphasize relative paths ✓
- Both warn against using `cd` ✓

✅ **Output Paths**
- Resource Finder outputs: All relative paths ✓
- Experiment Runner outputs: All relative paths ✓
- Completion marker: `.resource_finder_complete` (relative) ✓

✅ **Consistency**
- Both agents use same directory structure ✓
- Both agents save files in workspace ✓
- No absolute paths in instructions ✓

✅ **Runtime Guarantees**
- Working directory is validated before each stage ✓
- Failures are recorded in STATE.md ✓
- Stage outputs must exist in workspace to pass validation ✓
- No stage proceeds with inconsistent directory ✓

## Common Pitfalls Avoided

### ❌ What We DON'T Want:
```bash
# Agent changes directory
cd /some/other/path
mkdir papers  # Creates papers in wrong location!

# Agent uses absolute paths
wget paper.pdf -O /tmp/paper.pdf  # Saves outside workspace!

# Agent doesn't know where it is
ls papers  # Might look in wrong directory
```

### ✅ What We DO Want:
```bash
# Agent stays in current directory (workspace)
mkdir papers  # Creates papers in workspace
wget paper.pdf -O papers/paper.pdf  # Saves in workspace
ls papers  # Lists files in workspace/papers
```

## How This Works in Practice

### Example: Resource Finder Execution

1. **Orchestrator starts Resource Finder**:
   ```python
   process = subprocess.Popen(
       ["claude", "--dangerously-skip-permissions"],
       cwd="/path/to/workspace/my-research"  # Sets working directory
   )
   ```

2. **Agent receives prompt** with instructions:
   ```
   You are already running in the project workspace directory.
   DO NOT use cd or change directories.
   ```

3. **Agent executes commands**:
   ```bash
   # Agent is in /path/to/workspace/my-research
   mkdir papers  # Creates /path/to/workspace/my-research/papers
   wget paper.pdf -O papers/paper1.pdf  # Saves in workspace
   ```

4. **All outputs stay in workspace**:
   ```
   /path/to/workspace/my-research/
   ├── papers/paper1.pdf  ✓
   ├── literature_review.md  ✓
   └── .resource_finder_complete  ✓
   ```

### Example: Experiment Runner Execution

1. **Orchestrator starts Experiment Runner**:
   ```python
   process = subprocess.Popen(
       ["scribe", "claude"],
       cwd="/path/to/workspace/my-research"  # Same workspace
   )
   ```

2. **Agent receives prompt** with instructions:
   ```
   You are already running in: /path/to/workspace/my-research
   READ literature_review.md (in your current directory)
   Use datasets/ directory (relative to current directory)
   ```

3. **Agent finds pre-gathered resources**:
   ```bash
   # Agent is in /path/to/workspace/my-research
   cat literature_review.md  # Reads from workspace
   ls datasets/  # Lists datasets in workspace
   ```

4. **Agent creates new outputs**:
   ```bash
   # Still in /path/to/workspace/my-research
   jupyter notebook  # Creates notebooks in workspace
   mkdir results  # Creates in workspace
   python experiment.py > results/output.txt  # Saves in workspace
   ```

5. **All outputs stay in same workspace**:
   ```
   /path/to/workspace/my-research/
   ├── papers/paper1.pdf  (from Resource Finder)
   ├── datasets/data1/  (from Resource Finder)
   ├── literature_review.md  (from Resource Finder)
   ├── notebooks/experiment.ipynb  (from Experiment Runner)
   ├── results/output.txt  (from Experiment Runner)
   └── REPORT.md  (from Experiment Runner)
   ```

## Benefits of This Design

1. **No Path Confusion**: Both agents work in same directory
2. **Easy Handoff**: Experiment Runner finds Resource Finder outputs automatically
3. **GitHub Integration**: All files in one repo directory
4. **Clean Organization**: Everything in one place
5. **No Symlinks/Copying**: Direct access to resources
6. **Debuggability**: All logs and outputs in one location
7. **Execution Safety**: Prevent sileng failure from wrong directories

## Testing Verification

To verify workspace consistency:

```python
# After Resource Finder
assert (work_dir / ".resource_finder_complete").exists()
assert (work_dir / "literature_review.md").exists()
assert (work_dir / "papers").exists()

# After Experiment Runner
assert (work_dir / "REPORT.md").exists()
assert (work_dir / "README.md").exists()
assert (work_dir / "notebooks").exists()

# All in same directory
assert work_dir == resource_finder_work_dir
assert work_dir == experiment_runner_work_dir
```

## Conclusion

✅ **Both agents consistently use the same workspace directory**
✅ **All subprocess calls set `cwd` correctly**
✅ **All prompts explicitly instruct agents about the workspace**
✅ **All file paths are relative to the workspace**
✅ **No directory changes or absolute paths in instructions**
✅ **Runtime checks prevent directory drift**
✅ **Validation ensures outputs are produced in the correct location**

The workspace directory design is fully consistent across both agents and all execution modes.
