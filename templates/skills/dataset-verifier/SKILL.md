---
name: dataset-verifier
description: Verify a dataset id or URL exists and is reachable before download. Use during PHASE 2 of resource finding to filter inaccessible candidates.
---

# Dataset Verifier

Pre-flight check that a dataset actually exists and is reachable before
the experiment runner commits to download.

## When to Use

- During PHASE 2 of resource_finder, after candidate datasets are identified
  but before download
- When the agent considers a dataset citation but is unsure if it's accessible

## How to Call

```bash
python .claude/skills/dataset-verifier/scripts/verify_dataset.py <id_or_url>
```

Examples:
```bash
# HuggingFace dataset (bare name or hf:// prefix)
python verify_dataset.py glue
python verify_dataset.py hf://datasets/squad

# Kaggle dataset
python verify_dataset.py kaggle://uciml/iris
python verify_dataset.py https://www.kaggle.com/datasets/uciml/iris

# Generic URL
python verify_dataset.py https://example.com/dataset.tar.gz
```

## Output

JSON to stdout:
```json
{
  "id": "glue",
  "exists": true,
  "url": "https://huggingface.co/datasets/glue",
  "error": null
}
```

Exit code: 0 if exists, 1 otherwise.

## Source Detection

- `hf://...` or bare alphanumeric name → HuggingFace Hub
- `kaggle://...` or `kaggle.com/datasets/...` → Kaggle
- Otherwise → generic HTTP

For existence checks, the script uses a single streaming HTTP GET (only
headers are fetched, body is discarded). This avoids servers that mishandle
HEAD (e.g. Kaggle returns 404 for HEAD on valid dataset pages).

**HuggingFace specifically**: the existence check hits the API endpoint
`/api/datasets/<slug>` rather than the web URL `/datasets/<slug>`. Several
legacy canonical names (e.g. `wikitext`, `cnn_dailymail`, `xsum`) return
404 on the web URL but exist via the API and load via `load_dataset()`.
The `url` field in the JSON output still reports the web URL for human use.

## Limitations

- Only checks HTTP reachability — does not verify license, size, gating,
  or file format. Those are downstream concerns.
- No retry on transient errors. If the agent needs robustness, retry at
  the call site.
- HuggingFace URLs should point to the dataset root (e.g.
  `https://huggingface.co/datasets/glue`), not subpaths like `/viewer`,
  `/tree/main`, or `/blob/main/...`. Subpaths are interpreted as part of
  the dataset slug and produce false negatives. Use the bare slug or the
  root URL when in doubt.
