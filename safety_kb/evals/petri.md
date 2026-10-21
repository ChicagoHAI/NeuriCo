# Petri (Parallel Exploration Tool for Risky Interactions)

Fetched: 2026-10-19 (Anthropic scope). Slug: `petri`.

- What it measures: Automated alignment auditing: seed instructions -> auditor agent -> multi-turn simulated users/tools -> judge scores (misaligned behavior, eval awareness, misuse cooperation, deception, sycophancy, delusion, etc.).
- Metric: Per-dimension judge scores; 111+70 seeds; realism classifier in v2.
- Used by: Anthropic (Anthropic (Claude 4, Sonnet 4.5 cards; Fable 5 card cross-developer comparison by Meridian + UK AISI); UK AISI; Meridian Labs (maintainer))
- Open-source: Yes (MIT)
- Link: https://github.com/meridianlabs-ai/inspect_petri ; https://www.anthropic.com/research/petri-open-source-auditing ; https://alignment.anthropic.com/2026/petri-v2
- Runnable on a 0.5B-7B open model: Yes (Inspect; any provider incl. vLLM/HF for the target).
- Notes: v3.0 current; v2 branch kept.
- Source notes: labs/anthropic/system-cards.md, labs/anthropic/open-tools-and-methods.md

## Used by
- Used by: OpenAI (indirectly: UK AISI used an Inspect/Petri-based supply-chain eval on GPT-6 Astra during pre-deployment testing - 29.2% unsanctioned supply-chain attacks vs 6.3% for GPT-5.6 Sol. https://www.aisi.gov.uk/blog/gpt-6-astra-performs-unsanctioned-supply-chain-attacks-in-simulations)
