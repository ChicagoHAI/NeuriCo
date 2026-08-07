# NeuriCo: Next Steps & Future Improvements

> **Developer/internal document.** This file records proposed future work and
> does not define supported user behavior. See [`WORKFLOW.md`](WORKFLOW.md) for
> the current workflow.

This document outlines planned enhancements to the automated research pipeline, organized by priority and implementation complexity.

---

## 1. Critic Agent System 🔍

### Motivation
Inspired by `mechinterp_playground`, critic agents provide automated quality assurance and validation of research outputs.

### How It Works
After main research completes, launch separate evaluation agents that:
- Re-execute all code blocks to verify correctness
- Check internal consistency (do conclusions match evidence?)
- Validate goal alignment (did research address the hypothesis?)
- Generate test cases for discovered components

### Implementation Approach

**Two Critic Types:**

**Critic 1: Self-Consistency Evaluation**
- Re-runs every code block from notebooks
- Calculates metrics:
  - Runnable percentage
  - Correctness percentage
  - Redundancy analysis
  - Irrelevance detection
- Outputs: `code_evaluation.ipynb`, `self_consistency_report.ipynb`

**Critic 2: Goal Alignment Validation**
- Compares research outputs vs. original hypothesis
- Checks if methodology followed the plan
- Creates hidden test cases
- Outputs: `goal_alignment.ipynb`, `validation_tests.ipynb`

### Technical Details

```python
# Add to runner.py after main research completes
if args.enable_critics:
    # Generate critic prompts using existing infrastructure
    critic_prompt_1 = prompt_generator.generate_critic_prompt(
        'code_quality', idea, work_dir
    )
    critic_prompt_2 = prompt_generator.generate_critic_prompt(
        'goal_alignment', idea, work_dir
    )

    # Launch critic agents
    run_critic_agent(critic_prompt_1, work_dir, provider)
    run_critic_agent(critic_prompt_2, work_dir, provider)
```

### Benefits
✅ Automated quality assurance
✅ Reproducibility verification
✅ Research integrity checks
✅ Acts as automated peer review

### Considerations
⚠️ Doubles execution time and token costs
⚠️ Requires robust error handling for multi-stage pipelines
⚠️ May face same long-context limitations

### Recommendation
- **Phase 1**: Start with optional flag: `--enable-critics`
- **Phase 2**: Implement lightweight critic (code execution only)
- **Phase 3**: Add full goal-alignment critic
- **Alternative**: Add basic sanity checks without separate agents (check files exist, count code cells, etc.)

---

## 2. Dedicated Environment Setup Agent 🛠️

### Motivation
Environment setup is complex and error-prone. A specialized agent can:
- Choose appropriate Python version
- Handle complex dependencies (CUDA, system libraries)
- Debug installation failures
- Create reproducible environments

### Current Limitation
Main research agent handles environment setup + research execution, leading to:
- Lost context on installation debugging
- Mixed concerns (setup vs. research)
- Harder to parallelize/cache environments

### Proposed Architecture

**Stage 0: Environment Preparation Agent**
```
Input: idea specification (domain, dependencies, constraints)
Tasks:
1. Analyze requirements (GPU needed? Specific Python version?)
2. Create isolated environment with uv
3. Install dependencies with proper error handling
4. Verify installation (import tests, CUDA checks)
5. Save environment snapshot

Output:
- Ready-to-use environment
- requirements.txt or pyproject.toml
- environment_setup_log.md (what was installed, why, issues encountered)
```

**Stage 1: Main Research Agent**
```
Input: research prompt + pre-configured environment
Tasks: Pure research (no installation debugging)
```

### Benefits
✅ **Faster debugging**: Environment agent can retry installations without losing research context
✅ **Cacheable**: Reuse environments across similar research tasks
✅ **Parallelizable**: Set up environments before research starts
✅ **Better logs**: Separate environment issues from research issues
✅ **Specialization**: Environment agent can be optimized for installation tasks (use different model?)

### Implementation Approach

```python
# runner.py
def setup_environment(idea_spec, work_dir):
    """Launch dedicated environment setup agent."""
    env_prompt = prompt_generator.generate_environment_setup_prompt(idea_spec)

    # Use faster model for environment setup?
    env_agent = launch_agent(env_prompt, work_dir, model="haiku")

    # Wait for completion, verify environment ready
    verify_environment(work_dir / ".venv")

    return env_metadata

def run_research(idea_id, provider):
    # Setup environment first
    env_metadata = setup_environment(idea_spec, work_dir)

    # Then run research with pre-configured environment
    research_prompt = prompt_generator.generate_research_prompt(idea)
    run_research_agent(research_prompt, work_dir, provider, env_metadata)
```

### Considerations
⚠️ Adds overhead for simple projects
⚠️ Need timeout handling (stuck installations)
⚠️ May not be worth it if environments are similar across projects

### Recommendation
- **Phase 1**: Keep current approach, but improve prompts
- **Phase 2**: Add optional `--pre-setup-env` flag
- **Phase 3**: Auto-detect when separate env agent is beneficial (complex deps, GPU required, etc.)

---

## 3. Resource Collection Agent/Tools 📚

### Motivation
Researchers often need to:
- Download papers from arXiv, OpenReview, etc.
- Clone relevant GitHub repositories
- Fetch datasets from HuggingFace, Kaggle, etc.
- Extract and organize these resources

Currently, the main research agent does this ad-hoc, wasting context and time.

### Proposed Solutions

#### Option A: Pre-Research Resource Collection Agent

**Stage -1: Resource Gathering**
```
Input: Idea specification with resource references
Tasks:
1. Parse background.papers[] and background.datasets[]
2. Download papers (PDF from arXiv/OpenReview)
3. Clone GitHub repos mentioned in methodology
4. Fetch datasets (HuggingFace, Kaggle, UCI, etc.)
5. Organize: papers/, datasets/, code/, resources/

Output: Populated workspace with all resources ready
```

**Benefits:**
✅ Resources ready before research starts
✅ Can run in parallel with environment setup
✅ Separate failures (download issues vs. research issues)
✅ Can cache/reuse common datasets

**Example prompt:**
```yaml
idea:
  background:
    papers:
      - url: "https://arxiv.org/abs/2103.00020"
        description: "Attention is All You Need"
      - url: "https://github.com/user/repo"
        description: "Reference implementation"
    datasets:
      - name: "GLUE"
        source: "huggingface:glue"
      - name: "Custom dataset"
        source: "https://example.com/data.csv"
```

Resource agent would:
```bash
# papers/
papers/2103.00020.pdf
papers/github_user_repo/  # cloned

# datasets/
datasets/glue/  # downloaded from HF
datasets/custom_data.csv  # fetched from URL
```

#### Option B: Resource Collection Tools for Main Agent

**Provide specialized tools/scripts:**
```python
# tools/fetch_paper.py
def fetch_paper(arxiv_id=None, url=None, dest="papers/"):
    """Download paper and return local path."""

# tools/clone_repo.py
def clone_repo(github_url, dest="code/"):
    """Clone repository and return path."""

# tools/fetch_dataset.py
def fetch_dataset(name, source="huggingface", dest="datasets/"):
    """Download dataset and return path."""
```

Agent instructions:
```
IMPORTANT: Use provided tools to fetch resources efficiently:
- For arXiv papers: python tools/fetch_paper.py --arxiv 2103.00020
- For GitHub repos: python tools/clone_repo.py --url https://github.com/...
- For datasets: python tools/fetch_dataset.py --name glue --source huggingface
```

**Benefits:**
✅ Simpler implementation (no new agent)
✅ Agent controls when to fetch (lazy loading)
✅ Can fetch additional resources discovered during research

#### Option C: Hybrid Approach

**Pre-fetch obvious resources**, give tools for discovered resources:
1. Resource collection agent runs first for known resources
2. Main research agent has tools to fetch additional resources as needed

### Implementation Priority

**Recommended Approach: Option B (Tools) first, then Option C (Hybrid)**

**Phase 1: Create resource fetching tools**
```bash
src/tools/
├── fetch_paper.py      # arXiv, OpenReview, direct PDFs
├── clone_repo.py       # GitHub cloning with error handling
├── fetch_dataset.py    # HuggingFace, Kaggle, UCI, direct URLs
└── README.md           # Tool documentation
```

**Phase 2: Update session instructions**
Add section about resource tools:
```
RESOURCE COLLECTION TOOLS
─────────────────────────────────────────────────────────────────
Before manually downloading resources, use these tools:

1. Fetching Papers:
   python tools/fetch_paper.py --arxiv 2103.00020
   python tools/fetch_paper.py --url https://arxiv.org/pdf/2103.00020.pdf

2. Cloning Code:
   python tools/clone_repo.py --url https://github.com/user/repo

3. Downloading Datasets:
   python tools/fetch_dataset.py --name glue --source huggingface
   python tools/fetch_dataset.py --url https://example.com/data.csv

All resources will be organized in appropriate directories.
```

**Phase 3: Add pre-fetch resource agent**
For complex projects with many known resources, launch agent before research:
```python
if len(idea_spec.get('background', {}).get('papers', [])) > 3:
    # Many resources, worth separate agent
    run_resource_collection_agent(idea_spec, work_dir)
```

### Considerations
⚠️ Need API keys (HuggingFace, Kaggle)
⚠️ Rate limiting on downloads
⚠️ Large datasets may exceed disk space
⚠️ PDF extraction quality varies
⚠️ Some resources require authentication

---

## 4. Additional Future Enhancements

### A. Multi-Stage Research Pipeline
- Break long research into phases with checkpoints
- Agent 1: Planning & literature review
- Agent 2: Implementation
- Agent 3: Analysis & documentation
- **Benefit**: Avoid context overflow, better specialization

### B. Result Caching & Reuse
- Cache environment setups
- Cache dataset downloads
- Cache expensive computations
- Detect similar past research and reuse components

### C. Parallel Experimentation
- Run ablations in parallel (different hyperparameters)
- Compare multiple baselines simultaneously
- Aggregate results automatically

### D. Interactive Research Mode
- Allow user to provide feedback mid-research
- Checkpoints where agent asks for guidance
- User can steer research direction

### E. Better Error Recovery
- Automatic retry with modified approach
- Fallback strategies for common failures
- Incremental progress saving

---

## Implementation Priorities

### Immediate (Current Sprint)
✅ Core pipeline working end-to-end
✅ Environment isolation (uv-based)
✅ README + REPORT.md generation
✅ Resource awareness (check workspace for user files)

### Short-term (Next 2-4 weeks)
1. **Resource fetching tools** (Option B above)
   - High value, low complexity
   - Enables better literature review

2. **Basic sanity checks** (lightweight alternative to critics)
   - Check outputs exist
   - Count code cells
   - Verify key files present

### Medium-term (1-2 months)
3. **Optional critic agent** (full implementation)
   - Start with code quality critic
   - Add goal alignment critic later

4. **Environment setup agent** (for complex projects)
   - Optional flag for now
   - Auto-enable for GPU/complex deps

### Long-term (3+ months)
5. **Multi-stage research pipeline**
6. **Result caching & reuse**
7. **Parallel experimentation**

---

## Design Principles

As we add features, maintain these principles:

✅ **Modularity**: Each enhancement should be optional/toggleable
✅ **Simplicity first**: Start with simple implementations, add complexity when proven valuable
✅ **Cost awareness**: Track token usage, avoid unnecessary agent invocations
✅ **Fail gracefully**: Feature failures shouldn't break core pipeline
✅ **User control**: Provide flags to enable/disable features

---

## Questions to Consider

1. **Critic agents**: When should they be mandatory vs. optional?
2. **Environment setup**: Can we detect when separate agent is worth it?
3. **Resource collection**: Should we support authenticated sources (Kaggle, paid datasets)?
4. **Multi-stage pipeline**: How to handle handoff between agents? Save/restore context?
5. **Cost optimization**: Which stages benefit from cheaper models (haiku vs. sonnet)?

---

## Feedback Welcome!

This is a living document. Please update as we:
- Implement features and learn what works
- Discover new pain points in the current pipeline
- Get user feedback on what's most valuable
