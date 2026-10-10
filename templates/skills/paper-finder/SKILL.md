---
name: paper-finder
description: Find and search for academic papers using the paper-finder service. Use when conducting literature review, searching for related work, finding baseline papers, or looking for methodology references.
---

# Paper Finder

Systematic paper discovery and prioritization for research projects.

## When to Use

- Starting a literature review
- Looking for related work on a topic
- Finding baseline papers for experiments
- Searching for methodology references
- Building a citation list for a research paper

## How to Use

Run the helper script from your workspace:

```bash
{{ research_python_path }} .claude/skills/paper-finder/scripts/find_papers.py "your research topic"
```

Options:
- `--mode fast` (default): Quick search
- `--mode diligent`: Thorough search (recommended for comprehensive review)
- `--format json`: Output as JSON instead of text

Example:
```bash
{{ research_python_path }} .claude/skills/paper-finder/scripts/find_papers.py "hypothesis generation with large language models" --mode fast
```

## Search Strategy

### Query Formulation

Use structured queries for better results:

1. **Core concept + Method**: "transformer attention mechanism"
2. **Problem + Domain**: "few-shot learning natural language processing"
3. **Technique + Application**: "graph neural networks drug discovery"

### Multi-Stage Search

1. **Broad scan**: Start with general topic terms
2. **Focused dive**: Use specific method/technique names from initial results
3. **Citation chase**: Search for highly-cited papers referenced in relevant work

## Citation Prioritization

### Relevance Tiers

| Relevance Score | Priority | Action |
|-----------------|----------|--------|
| 3 (High) | Must read | Download PDF, read fully, cite |
| 2 (Medium) | Should read | Read abstract + intro, cite if relevant |
| 1 (Low) | Optional | Skim abstract, cite only if needed |
| 0 (Not relevant) | Skip | Do not include |

### Citation Count Thresholds

| Category | Citation Count | Interpretation |
|----------|----------------|----------------|
| Seminal | 1000+ | Foundational work, must cite |
| Well-established | 100-999 | Widely accepted, cite if relevant |
| Recent/Emerging | 10-99 | Current research, cite for novelty |
| New | <10 | Very recent, check publication venue |

### Venue Tiers (ML/AI Focus)

**Tier 1** (Top venues, high credibility):
- NeurIPS, ICML, ICLR, ACL, EMNLP, CVPR, ICCV

**Tier 2** (Strong venues):
- AAAI, IJCAI, NAACL, COLING, ECCV, WACV

**Tier 3** (Good venues):
- *ACL workshops, COLM, EACL, CoNLL

**Preprints** (arXiv):
- Check for peer-reviewed version first
- Cite arXiv only if no published version exists

## Screening Workflow

### Phase 1: Title Screening
- Review titles from search results
- Mark papers as "include", "exclude", or "maybe"
- Goal: ~50% reduction

### Phase 2: Abstract Screening
- Read abstracts for included/maybe papers
- Evaluate: relevance, methodology, findings
- Goal: Identify key papers for deeper reading

### Phase 3: Full-Text Review
- Download and read full PDFs for key papers
- Extract: methods, results, limitations, citations
- Use the PDF chunker for detailed reading (see below)

## Output Structure

Returns relevance-ranked papers with:
- Title, authors, year
- Abstract (already extracted)
- URL for download
- Relevance score (0-3, focus on papers with score >= 2)
- Citation count

## After Finding Papers

1. Download PDFs for papers with relevance >= 2
2. Read abstracts first (already provided in output)
3. Only read full PDFs for most relevant papers
4. Write notes to literature_review.md immediately
5. Track citations for references.bib

## Reading Large PDFs

Use the PDF chunker to split papers into smaller PDF files that can be read directly.
This preserves all formatting perfectly (unlike text extraction which loses formatting).

**Dependencies:**
```bash
# Using uv (recommended):
uv add --project {{ research_env_dir }} pypdf
```

**How to run:**

```bash
{{ research_python_path }} .claude/skills/paper-finder/scripts/pdf_chunker.py <pdf_path>
```

Options:
- `--pages-per-chunk N`: Number of pages per chunk (default: 1)
- `--output-dir DIR`: Output directory (default: `<pdf_dir>/pages`)

**Output:**
- Creates PDF chunk files: `<pdf_name>_chunk_001.pdf`, `<pdf_name>_chunk_002.pdf`, etc.
- Creates a manifest: `<pdf_name>_manifest.txt` listing all chunks with page ranges

**Integration with screening workflow:**
1. Run the chunker on papers before detailed reading
2. For abstract skimming: read only chunk 1 (page 1 or pages 1-3)
3. For deep reading: read ALL chunk PDFs sequentially, writing notes after each
4. Check the manifest to see how many chunks exist
5. IMPORTANT: Do not skip chunks - methodology and results are in later chunks

## If Paper-Finder Service Not Running

The script will show a fallback message. Use manual search instead:
- arXiv: https://arxiv.org
- Semantic Scholar: https://www.semanticscholar.org
- Papers with Code: https://paperswithcode.com
- Google Scholar: https://scholar.google.com

Manual search works well - paper-finder is just a convenience for faster, more targeted results.

## References

See `references/` folder for:
- `search_strategies.md`: Detailed search query formulation
- `prioritization_guide.md`: Extended prioritization criteria
