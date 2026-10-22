---
name: literature-review
description: Conduct systematic literature reviews using a structured workflow. Use when starting a new research project, surveying a field, or documenting related work for a paper.
---

# Literature Review

Systematic workflow for conducting comprehensive literature reviews.

## When to Use

- Starting a new research project
- Surveying a research field
- Writing the Related Work section of a paper
- Identifying research gaps
- Building a comprehensive reading list

## PRISMA-Lite Workflow

This workflow adapts the PRISMA (Preferred Reporting Items for Systematic Reviews) framework for ML/AI research.

### Phase 1: Define Scope

Before searching, define:

1. **Research Question**: What are you trying to learn?
2. **Inclusion Criteria**: What makes a paper relevant?
3. **Exclusion Criteria**: What makes a paper not relevant?
4. **Time Frame**: How far back to search?
5. **Search Sources**: Which databases to use?

Document in `literature_review.md`:

```markdown
## Review Scope

### Research Question
[Your research question here]

### Inclusion Criteria
- [ ] Criterion 1
- [ ] Criterion 2

### Exclusion Criteria
- [ ] Criterion 1
- [ ] Criterion 2

### Time Frame
[e.g., 2019-present]

### Sources
- [ ] Semantic Scholar
- [ ] arXiv
- [ ] Google Scholar
- [ ] ACL Anthology
```

### Phase 2: Search

Execute systematic search using paper-finder or manual search:

1. **Primary search**: Use core topic terms
2. **Secondary search**: Use method/technique names
3. **Citation search**: Check references of key papers

Track search queries:

```markdown
## Search Log

| Date | Query | Source | Results | Notes |
|------|-------|--------|---------|-------|
| YYYY-MM-DD | "query here" | Semantic Scholar | N papers | Initial search |
```

### Phase 3: Screening

Three-stage screening process:

#### Stage 1: Title Screening
- Review all titles
- Quick relevance judgment
- Mark: Include / Exclude / Maybe

#### Stage 2: Abstract Screening
- Read abstracts for Include/Maybe papers
- Evaluate methodology and findings
- Mark: Include / Exclude

#### Stage 3: Full-Text Screening
- Download and read full papers
- Verify relevance and quality
- Extract key information

Track screening:

```markdown
## Screening Results

| Paper | Title Screen | Abstract Screen | Full-Text | Notes |
|-------|-------------|-----------------|-----------|-------|
| Paper1 | Include | Include | Include | Key baseline |
| Paper2 | Maybe | Exclude | - | Different task |
```

### Phase 4: Data Extraction

For each included paper, extract:

1. **Bibliographic**: Authors, year, venue
2. **Problem**: What problem is addressed?
3. **Method**: What approach is used?
4. **Data**: What datasets/benchmarks?
5. **Results**: Key findings
6. **Limitations**: Acknowledged weaknesses
7. **Relevance**: How relates to our work?

Use the extraction template in `assets/review_template.md`.

### Phase 5: Synthesis

Organize findings by theme:

1. **Identify themes**: Group related papers
2. **Compare approaches**: What are the differences?
3. **Find gaps**: What's missing?
4. **Position work**: Where does your work fit?

## Output Files

### literature_review.md

Main document tracking the review:

```markdown
# Literature Review: [Topic]

## Review Scope
[Scope definition]

## Search Log
[Search queries and results]

## Paper Summaries
[Individual paper notes]

## Themes and Synthesis
[Grouped findings]

## Research Gaps
[Identified opportunities]

## Key Citations
[Must-cite papers for your work]
```

### papers/ directory

Organize downloaded papers:

```
papers/
├── must_read/           # Relevance 3, priority reading
├── should_read/         # Relevance 2
├── reference/           # Background papers
└── README.md            # Index of all papers
```

## Tools

### Reading Large PDFs

Use the PDF chunker to split papers into smaller PDF files that can be read directly.
This preserves all formatting perfectly (unlike text extraction which loses formatting).

**Dependencies:**
```bash
# Using uv (recommended):
uv add --project {{ research_env_dir }} pypdf
```

**How to run:**

```bash
{{ research_python_path }} .claude/skills/literature-review/scripts/pdf_chunker.py <pdf_path>
```

Options:
- `--pages-per-chunk N`: Number of pages per chunk (default: 1)
- `--output-dir DIR`: Output directory (default: `<pdf_dir>/pages`)

**Output:**
- Creates PDF chunk files: `<pdf_name>_chunk_001.pdf`, `<pdf_name>_chunk_002.pdf`, etc.
- Creates a manifest: `<pdf_name>_manifest.txt` listing all chunks with page ranges

**Integration with screening workflow:**
1. During Phase 3 (Full-Text Screening), run the chunker on papers that need detailed review
2. For abstract skimming: read only chunk 1 (page 1 or pages 1-3)
3. For deep reading: read ALL chunk PDFs sequentially, writing notes after each
4. Check the manifest to see how many chunks exist
5. IMPORTANT: Do not skip chunks - methodology and results are in later chunks

### Verify Citations

After completing the review, verify all citations are valid:

```bash
python .claude/skills/literature-review/scripts/verify_citations.py literature_review.md
```

## Quality Checklist

- [ ] Research question clearly defined
- [ ] Inclusion/exclusion criteria documented
- [ ] Multiple sources searched
- [ ] Search queries logged
- [ ] Screening decisions recorded
- [ ] Key information extracted from all included papers
- [ ] Papers organized by theme
- [ ] Research gaps identified
- [ ] Citations verified

## References

See `references/` folder for:
- `screening_guide.md`: Detailed screening criteria

See `assets/` folder for:
- `review_template.md`: Template for literature_review.md
