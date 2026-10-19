# SRE-Bench (software reverse engineering)

- Slug: sre-bench
- What it measures: Reverse engineering of compiled binaries without source: 262 binary instances from 19 privately developed programs spanning network protocols, file formats, malware remediation and firmware, across C/C++/Go/Rust, multiple compilation settings and software-protection techniques; six task-specific objectives each.
- Metric: pass@1 and pass@4 (a challenge counts solved only when all six objectives are met); pass@4 sums tokens across four trials and takes the best accuracy.
- Open-source: n - "designed to be contamination-free" from private programs; not publicly released by OpenAI. (Unrelated public repos share the name.)
- Runnable on a 0.5B-7B open model: n
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (10.1.2.3)
- Fetched: 2026-10-19

## Description
Added in the Astra card. "At pass@4, Astra solves 99.2% of the reverse engineering challenges vs GPT-5.6 Sol's 68.7%, using about 1/4th as many output tokens." No indicative threshold is published.

## Used by
- Used by: OpenAI (GPT-6 Astra card; labs/openai/system-cards.md)
