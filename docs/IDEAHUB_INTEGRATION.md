# IdeaHub Integration Guide

NeuriCo can automatically fetch research ideas from [IdeaHub](https://hypogenic.ai/ideahub/) and convert them into minimal YAML format (v1.1).

## Overview

IdeaHub is a platform for sharing and discovering research ideas. This integration allows you to:
1. **Fetch** ideas from IdeaHub URLs
2. **Convert** them to minimal NeuriCo format (preserves only provided info)
3. **Submit** them directly - agent will research missing details
4. **Run** autonomous experiments with agent-driven resource discovery

## Setup

### Prerequisites

1. **OpenAI API Key** (for GPT-4 conversion)
   - Get your API key from: https://platform.openai.com/api-keys
   - Add to your `.env.local` or `.env` file:
     ```bash
     OPENAI_API_KEY=sk-your-key-here
     ```

2. **Dependencies** (already included in `pyproject.toml`)
   ```bash
   uv sync  # Installs requests, beautifulsoup4, openai
   ```

## Usage

### Basic Usage

Fetch an idea from IdeaHub:

```bash
python src/cli/fetch_from_ideahub.py https://hypogenic.ai/ideahub/idea/HGVv4Z0ALWVHZ9YsstWT
```

**What happens (v1.1):**
1. 📥 Fetches the idea content from IdeaHub (title, description, references)
2. 🤖 Uses GPT-4o-mini to format as minimal YAML (no hallucination)
3. 💾 Saves only provided information - no invented datasets/methods
4. ✅ Agent will research missing details when you run the experiment

**Example output:**
```
================================================================================
IdeaHub to NeuriCo Converter
================================================================================
📥 Fetching idea from IdeaHub...
   URL: https://hypogenic.ai/ideahub/idea/HGVv4Z0ALWVHZ9YsstWT

✓ Found idea: Do LLMs differentiate epistemic belief from non-epistemic belief?

🤖 Converting to NeuriCo format using GPT-4...
   Calling GPT-4 API...
   ✓ Conversion complete

✅ Idea saved to: ideas/do_llms_differentiate_epistemic_belief.yaml

To submit this idea:
  python src/cli/submit.py ideas/do_llms_differentiate_epistemic_belief.yaml

================================================================================
Done!
================================================================================
```

### Auto-Submit

Fetch and automatically submit the idea:

```bash
python src/cli/fetch_from_ideahub.py https://hypogenic.ai/ideahub/idea/HGVv4Z0ALWVHZ9YsstWT --submit
```

This will:
1. Fetch and convert the idea
2. Validate it against the schema
3. Submit it to NeuriCo
4. Create a GitHub repository (if GitHub integration enabled)
5. Return the idea ID for running

**Example output:**
```
...
📤 Submitting idea to NeuriCo...

✓ Idea submitted successfully: do_llms_differentiate_epistemic_belief_20250103_120000_abc123de

To run this research:
  python src/core/runner.py do_llms_differentiate_epistemic_belief_20250103_120000_abc123de
```

### Custom Output Path

Save to a specific location:

```bash
python src/cli/fetch_from_ideahub.py \
  https://hypogenic.ai/ideahub/idea/HGVv4Z0ALWVHZ9YsstWT \
  --output my_ideas/llm_beliefs.yaml
```

## How It Works

### 1. Content Extraction

The script fetches the IdeaHub page and extracts:
- **Title**: Main research question
- **Description**: Detailed explanation and context
- **Tags**: Research domains and topics
- **Author**: Original idea creator
- **References**: Cited papers and resources

### 2. GPT-4 Conversion

GPT-4 is prompted to convert the IdeaHub content into structured YAML following the NeuriCo schema:

```yaml
idea:
  title: "Extracted or refined title"
  domain: artificial_intelligence  # Inferred from content
  hypothesis: "Clear, testable hypothesis"

  background:
    description: "Context and motivation"
    papers: [...]  # Extracted references

  methodology:
    approach: "Proposed experimental approach"
    steps: [...]
    baselines: [...]
    metrics: [...]

  constraints:
    compute: cpu_only  # For AI research
    budget: 150        # Typical API costs, USD (numeric per schema)

  expected_outputs: [...]
  evaluation_criteria: [...]
```

**GPT-4's Role:**
- **Domain Classification**: Infers appropriate domain from tags and content
- **Hypothesis Extraction**: Formulates testable hypothesis from description
- **Methodology Design**: Proposes experimental steps, baselines, and metrics
- **Constraint Estimation**: Sets realistic compute, time, and budget constraints
- **Output Specification**: Defines expected results and evaluation criteria

### 3. Validation & Saving

The converted YAML is:
1. Validated against the schema
2. Enhanced with metadata (source, source_url)
3. Saved with a sanitized filename derived from the title

## Examples

### Example 1: AI/LLM Research

**IdeaHub URL:** https://hypogenic.ai/ideahub/idea/HGVv4Z0ALWVHZ9YsstWT

**IdeaHub Content:**
- Title: "Do LLMs differentiate epistemic belief from non-epistemic belief?"
- Description: Research on whether LLMs exhibit distinct types of beliefs
- Tags: Psychology, LLM behavior

**Converted YAML:**
```yaml
idea:
  title: "Evaluating Epistemic vs Non-Epistemic Belief Differentiation in LLMs"
  domain: artificial_intelligence

  hypothesis: |
    LLMs demonstrate measurable differences in representing epistemic beliefs
    (knowledge-based) versus non-epistemic beliefs (religious, moral),
    similar to human cognitive patterns.

  methodology:
    approach: "Comparative prompt-based evaluation"
    steps:
      - "Design prompts testing epistemic beliefs (factual knowledge)"
      - "Design prompts testing non-epistemic beliefs (values, preferences)"
      - "Run across multiple LLMs (GPT-4, Claude, Gemini)"
      - "Analyze response patterns and confidence levels"
      - "Compare with human baseline from Vesga et al. (2025)"

    baselines:
      - "Human belief differentiation patterns from psychology research"
      - "Zero-shot vs few-shot prompting"

    metrics:
      - "Belief type classification accuracy"
      - "Confidence level differences"
      - "Response consistency across similar prompts"
```

### Example 2: Complete Workflow

```bash
# 1. Fetch idea from IdeaHub
python src/cli/fetch_from_ideahub.py \
  https://hypogenic.ai/ideahub/idea/ABC123 \
  --submit

# Output: idea_id_20250103_120000_abc123de

# 2. (Optional) Add resources to workspace
cd workspace/idea-id-20250103-120000-abc123de
# Add datasets, papers, etc.
git add . && git commit -m "Add resources" && git push
cd ../..

# 3. Run the research
python src/core/runner.py idea_id_20250103_120000_abc123de
```

## Troubleshooting

### "OPENAI_API_KEY not found"

**Solution:** Add your API key to `.env.local` or `.env`:

```bash
# Create .env.local if it doesn't exist
cp .env.example .env.local

# Edit .env.local
nano .env.local

# Add:
OPENAI_API_KEY=sk-your-key-here
```

### "Error fetching URL"

**Possible causes:**
- Network connectivity issues
- Invalid IdeaHub URL
- Page structure changed

**Solution:**
1. Verify the URL is correct and accessible
2. Check internet connection
3. Try again after a few seconds

### "Generated YAML may have issues"

**Cause:** GPT-4 occasionally generates invalid YAML syntax

**Solution:**
1. Check the saved YAML file for syntax errors
2. Manually fix any issues (usually missing quotes or colons)
3. Re-run the submission manually:
   ```bash
   python src/cli/submit.py ideas/generated_file.yaml
   ```

### Rate Limiting

**Issue:** GPT-4 API rate limits

**Solution:**
- Wait a few seconds between requests
- Use GPT-4 Turbo (higher rate limits)
- Check your OpenAI account quotas

## Advanced Usage

### Custom Conversion Prompts

If you need to customize how ideas are converted, you can modify the GPT-4 prompt in `src/cli/fetch_from_ideahub.py`:

```python
# Line ~140 in fetch_from_ideahub.py
prompt = f"""You are an expert research assistant...
# Customize this prompt to change conversion behavior
```

### Batch Processing

Fetch multiple ideas:

```bash
#!/bin/bash
# fetch_multiple.sh

urls=(
  "https://hypogenic.ai/ideahub/idea/ABC123"
  "https://hypogenic.ai/ideahub/idea/DEF456"
  "https://hypogenic.ai/ideahub/idea/GHI789"
)

for url in "${urls[@]}"; do
  python src/cli/fetch_from_ideahub.py "$url"
  sleep 2  # Avoid rate limits
done
```

### Manual Review

Always review converted ideas before running:

```bash
# Fetch without auto-submit
python src/cli/fetch_from_ideahub.py <url>

# Review the generated YAML
cat ideas/generated_file.yaml

# Edit if needed
nano ideas/generated_file.yaml

# Submit manually
python src/cli/submit.py ideas/generated_file.yaml
```

## Best Practices

### 1. Review Before Running

GPT-4 does a good job converting ideas, but always review:
- ✅ Check the hypothesis is testable
- ✅ Verify methodology is realistic
- ✅ Ensure constraints match your resources
- ✅ Confirm metrics are appropriate

### 2. Add Context

After conversion, you can enhance the idea:
- Add specific datasets you have access to
- Include references to relevant papers
- Adjust time/budget constraints to your needs
- Specify additional evaluation criteria

### 3. Use Resources

If the IdeaHub idea references specific papers or datasets:
1. Fetch the idea with `--submit`
2. Navigate to the workspace
3. Add the referenced papers/datasets
4. Commit and push before running

```bash
cd workspace/<repo-name>
mkdir docs && cp ~/papers/*.pdf docs/
git add . && git commit -m "Add referenced papers" && git push
cd ../..
python src/core/runner.py <idea_id>
```

## API Costs

**Typical costs per conversion:**
- GPT-4 Turbo: ~$0.02-0.10 per idea
- GPT-4: ~$0.05-0.20 per idea

**Cost optimization:**
- Use GPT-4 Turbo (cheaper, faster)
- Batch process during off-peak hours
- Cache conversions (script saves YAML, reuse if possible)

## Future Enhancements

Potential improvements to the IdeaHub integration:

- [ ] Support for fetching multiple ideas at once
- [ ] Integration with IdeaHub user accounts
- [ ] Automatic tagging and categorization
- [ ] Direct submission to IdeaHub from NeuriCo results
- [ ] Community sharing of converted ideas

## FAQ

**Q: Does this work with private IdeaHub ideas?**

A: Currently only public ideas are supported. Private ideas require authentication, which is not yet implemented.

**Q: Can I convert ideas from other platforms?**

A: The script is designed for IdeaHub, but you could adapt it for other platforms by modifying the content extraction logic.

**Q: What if the conversion doesn't match what I want?**

A: Simply edit the generated YAML file before submitting. The GPT-4 conversion is a starting point that you can refine.

**Q: Are the original IdeaHub authors credited?**

A: Yes! The conversion includes the author name and source URL in the metadata. Always respect original authorship and licensing.

**Q: Can I use a different model instead of GPT-4?**

A: Yes, modify the script to use Claude or Gemini. GPT-4 is used by default for its strong instruction following.

---

**Last Updated**: 2025-11-03
**Maintained by**: ChicagoHAI
