# NeuriCo Workflow Guide

This guide explains the complete workflow for using NeuriCo, from idea submission to results publication.

## Overview

NeuriCo uses a **workspace-first** approach where GitHub repositories are created immediately upon idea submission, allowing you to add resources before the AI agent runs.

Usage and budget tracking reads the structured transcripts emitted by the
Claude, Codex, and Gemini CLI commands used during each agent stage. See
[`USAGE_TRACKING_TRANSCRIPTS.md`](USAGE_TRACKING_TRANSCRIPTS.md) for the exact
provider transcript fields parsed by NeuriCo.

## Complete Workflow

### Step 1: Setup (One-time)

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and setup NeuriCo
git clone https://github.com/ChicagoHAI/neurico
cd neurico

# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env and add your GITHUB_TOKEN
```

### Step 2: Create Research Idea

Create a YAML file describing your research idea. You have two options:

**Option A: Minimal Specification (v1.1 - Recommended)**

Let the agent research details through literature review:

```yaml
# my_experiment.yaml
idea:
  title: "Impact of Chain-of-Thought on Math Reasoning"
  domain: artificial_intelligence
  hypothesis: |
    Chain-of-thought prompting improves LLM performance on
    multi-step math problems by 15-30% compared to direct prompting.

  background:
    papers:
      - url: "https://arxiv.org/abs/2201.11903"
        description: "Original Chain-of-Thought paper"

  constraints:
    compute: cpu_only
    budget: "$50"
    time_limit: 3600
```

The agent will automatically:
- Search for appropriate datasets (e.g., GSM8K, MATH)
- Identify baselines from literature
- Select standard evaluation metrics
- Document choices in `resources.md`

**Option B: Detailed Specification (Traditional)**

Provide full experimental details if you have specific requirements:

```yaml
# my_experiment.yaml
idea:
  title: "My Research Title"
  domain: machine_learning
  hypothesis: "My testable hypothesis"

  methodology:
    approach: "High-level strategy"
    steps: ["Step 1", "Step 2"]
    baselines: ["Baseline 1", "Baseline 2"]
    metrics: ["accuracy", "f1_score"]

  background:
    datasets:
      - name: "Dataset Name"
        source: "huggingface:org/dataset"

  expected_outputs:
    - type: metrics
      format: json
      fields: [accuracy, f1_score]
```

See `ideas/schema.yaml` for complete specification and `ideas/examples/` for more examples.

### Step 3: Submit Idea

```bash
python src/cli/submit.py my_experiment.yaml
```

**What happens:**
1. ✅ Validates your idea against schema
2. 📦 Creates GitHub repository (personal account or organization)
3. 📥 Clones repository to `workspace/<repo-name>/`
4. 📝 Adds research metadata (README, idea.yaml)
5. 🚀 Commits and pushes initial setup to GitHub

**Output:**
```
✓ Idea submitted successfully: my_experiment_20250103_120000_abc123de
✓ Repository created: https://github.com/your-username/my-experiment-20250103-120000-abc123de
✓ Workspace ready at: workspace/my-experiment-20250103-120000-abc123de

NEXT STEPS:
1. (Optional) Add resources to workspace:
   cd workspace/my-experiment-20250103-120000-abc123de
   # Add datasets, documents, etc.
2. Run the research:
   python src/core/runner.py my_experiment_20250103_120000_abc123de
```

### Step 4: Add Resources (Optional but Recommended)

Navigate to the workspace and add your resources:

```bash
cd workspace/my-experiment-20250103-120000-abc123de

# Create directory structure
mkdir -p datasets docs code

# Add datasets
cp ~/data/my_dataset.csv datasets/
cp ~/data/reference_data.json datasets/

# Add documentation
cp ~/papers/related_work.pdf docs/
echo "# Background Information" > docs/context.md

# Add helper code
cat > code/utils.py << 'EOF'
import numpy as np

def preprocess_data(data):
    """Helper function for preprocessing."""
    return data
EOF

# Commit and push to GitHub
git add .
git commit -m "Add research resources: datasets and utilities"
git push

# Return to project root
cd ../..
```

**Why add resources?**

| Resource Type | Purpose | Example |
|--------------|---------|---------|
| **Datasets** | Large data files for analysis | CSV, JSON, parquet files |
| **Documents** | Papers, specs, documentation | PDFs, markdown files |
| **Code** | Helper functions, baselines | Python modules, utilities |
| **Configs** | Model configurations, hyperparameters | YAML, JSON configs |

The AI agent will have access to all these resources when it runs.

### Step 5: Run Research

```bash
python src/core/runner.py my_experiment_20250103_120000_abc123de

# Options:
#   --provider claude|gemini|codex  (default: claude)
#   --timeout SECONDS               (default: 3600)
#   --no-github                     (run locally without GitHub)
```

**What happens:**
1. 📥 Pulls latest changes from GitHub (includes your resources)
2. 📝 Generates comprehensive research prompt
3. 🤖 Launches AI agent in the workspace
4. 🔬 Agent executes research (v1.1 workflow):
   - **Phase 0**: Checks provided resources, identifies gaps
   - **Research** (if needed): Searches for datasets, baselines, methods (30-60 min)
   - **Planning**: Designs detailed experimental plan
   - **Setup**: Creates virtual environment, installs dependencies
   - **Implementation**: Writes code, runs experiments (uses notebooks)
   - **Analysis**: Analyzes results, creates visualizations
   - **Documentation**: Writes REPORT.md, README.md, resources.md
5. 📤 Commits and pushes all results to GitHub

**During execution:**
- See real-time output in terminal
- Logs saved to `workspace/<repo-name>/logs/`
- Agent creates notebooks, results, and artifacts

### Step 6: Review Results

All results are available both locally and on GitHub:

**Local workspace:**
```
workspace/<repo-name>/
├── REPORT.md                   # Main research report (v1.1)
├── README.md                   # Project overview
├── resources.md                # Research process documentation (v1.1)
├── notebooks/
│   ├── experiments.ipynb       # Experimental code (descriptive names)
│   └── analysis.ipynb          # Analysis and visualizations
├── results/
│   ├── metrics.json            # Quantitative results
│   └── figures/                # Plots and visualizations
├── artifacts/
│   └── *.pt / *.pkl            # Models, checkpoints
├── logs/
│   ├── research_prompt.txt     # Generated prompt
│   └── execution_claude.log    # Full execution log
├── datasets/                   # Your datasets
├── docs/                       # Your documents
├── code/                       # Your helper code
└── .neurico/
    └── idea.yaml               # Original idea spec
```

**GitHub repository:**
- Visit the repository URL shown after submission
- All results committed and pushed automatically
- README with research overview
- Complete version history

### Step 7: Iterate (Optional)

If you want to extend or improve the research:

```bash
cd workspace/<repo-name>

# Make changes
# - Edit notebooks
# - Add more experiments
# - Refine analysis

# Commit changes
git add .
git commit -m "Extended analysis with additional metrics"
git push

# Or re-run with different provider
cd ../..
python src/core/runner.py my_experiment_id --provider gemini
```

## Advanced Workflows

### Collaborative Research

**Researcher A submits idea:**
```bash
python src/cli/submit.py experiment.yaml
# Shares idea_id with team
```

**Researcher B adds domain expertise:**
```bash
cd workspace/<repo-name>
# Add domain-specific datasets
# Add specialized utilities
git commit -am "Add domain expertise and resources"
git push
```

**Researcher C runs experiment:**
```bash
python src/core/runner.py <idea_id>
# Results available to entire team on GitHub
```

### Multi-Provider Comparison

Run same experiment with different AI providers:

```bash
# Run with Claude
python src/core/runner.py my_experiment --provider claude

# Run with Gemini
python src/core/runner.py my_experiment --provider gemini

# Compare results in respective run directories
```

### Local-First Development

Test locally before pushing to GitHub:

```bash
# Submit without GitHub
python src/cli/submit.py my_idea.yaml --no-github

# Run locally
python src/core/runner.py my_idea_id --no-github

# Results saved to runs/ directory instead of workspace/
```

## Tips and Best Practices

### Resource Management

✅ **DO:**
- Add datasets that are too large to describe in YAML
- Include reference implementations for baselines
- Provide domain-specific documentation
- Commit resources before running experiments

❌ **DON'T:**
- Add extremely large files (>100MB) - use Git LFS or external storage
- Include sensitive data without proper access controls
- Commit credentials or API keys

### Workspace Organization

Recommended structure for resources:

```
workspace/<repo-name>/
├── datasets/
│   ├── raw/           # Original data
│   ├── processed/     # Cleaned data
│   └── README.md      # Dataset documentation
├── docs/
│   ├── papers/        # Related papers
│   ├── specs/         # Specifications
│   └── notes.md       # Research notes
├── code/
│   ├── baselines/     # Baseline implementations
│   ├── utils/         # Helper functions
│   └── __init__.py
└── configs/
    └── model_config.yaml
```

### Version Control

- **Commit regularly**: Push resources incrementally
- **Descriptive messages**: "Add CIFAR-10 dataset" not "Add data"
- **Use .gitignore**: Exclude large binary files, temporary outputs
- **Tag releases**: Use git tags for important milestones

### Troubleshooting

**Issue: "No workspace found"**
```bash
# Solution: Submit idea first to create workspace
python src/cli/submit.py my_idea.yaml
```

**Issue: "Failed to pull latest changes"**
```bash
# Solution: Check git status in workspace
cd workspace/<repo-name>
git status
# Resolve any conflicts, then continue
```

**Issue: "Agent can't find my dataset"**
```bash
# Solution: Ensure dataset is committed and pushed
cd workspace/<repo-name>
git add datasets/
git commit -m "Add dataset"
git push
```

## FAQ

**Q: When should I add resources vs. describe them in YAML?**

A: Add resources as files when:
- Datasets are large (>1MB)
- You have existing code to reuse
- Documentation is extensive (papers, specs)

Describe in YAML when:
- You can provide a URL to download
- Dataset is generated synthetically
- Code should be written from scratch

**Q: Can I modify the workspace after the agent runs?**

A: Yes! The workspace is a regular git repository. You can:
- Edit notebooks
- Add more experiments
- Refine documentation
- Commit and push changes

**Q: What if I need to re-run an experiment?**

A: Simply run `python src/core/runner.py <idea_id>` again. The runner will:
- Use existing workspace
- Pull latest changes
- Re-execute research
- Commit new results

**Q: How do I share results with collaborators?**

A: Just share the GitHub repository URL. Collaborators can:
- View results on GitHub
- Clone the repository
- Add their own contributions
- Run additional experiments

---

**Next Steps:**
- Review example ideas in `ideas/examples/`
- See [GitHub Integration Guide](../GITHUB_INTEGRATION.md) for details
- Check [README](../README.md) for complete documentation
