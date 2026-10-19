# Enkrypt AI LLM Safety Leaderboard / Sentry red-teaming reports

- Slug: enkrypt-llm-safety-leaderboard
- What it measures: Vendor red-teaming battery scoring an LLM on four risk categories — jailbreak susceptibility, bias, malware/insecure-code generation, toxicity — plus harmful-content and CBRN sections in the long-form reports; "Risk score is an average of risk in four categories ... Lower the score, lower the risk."
- Metric: Attack success rate per category (e.g., "A Jailbreak score of 18% indicates that 18% of the jailbreak tests successfully breached the LLM"); overall Risk Score = mean of the four; reports also give multipliers vs comparator models (gpt-4o, o1, claude-3-opus).
- Open-source: n (proprietary prompt sets and judge; commercial API at docs.enkryptai.com; leaderboard page https://www.enkryptai.com/llm-safety-leaderboard)
- Runnable on a 0.5B-7B open model: y via Enkrypt's paid API (any endpoint, including HuggingFace/open models — the leaderboard claims 200+ models incl. open ones); n without the vendor (prompts not released)
- Source URL(s): https://www.enkryptai.com/llm-safety-leaderboard ; https://www.enkryptai.com/research ; DeepSeek-R1 report PDF https://cdn.prod.website-files.com/6690a78074d86ca0ad978007/679bc2e71b48e423c0ff7e60_1%20RedTeaming_DeepSeek_Jan29_2025%20(1).pdf ; https://docs.enkryptai.com/get-started/redteam/introduction.md
- Fetched: 2026-10-19

## Description
The leaderboard page states it provides "Independent rankings of 200+ frontier models across safety, robustness, and compliance" with "4 Risk Scores" and "24x7 Real time data"; the research page says "We conduct more than 50,000 dynamic red-teaming evaluations per model, spanning critical risk categories: bias, insecure code, CBRN threats, harmful content, and toxicity." The January 2025 DeepSeek-R1 report documents the per-category methods (attribute-demographic association prompts for bias; story-embedded and iteratively self-adjusting prompts for harmful content; sentence-completion for toxicity; malware construction prompts; direct CBRN queries) and reports e.g. 83% bias ASR, 45% harmful ASR, 78% insecure-code ASR, 13% CBRN ASR, 6.68% toxicity for DeepSeek-R1, with findings mapped to OWASP LLM Top 10 (2025), MITRE ATLAS and NIST AI RMF. The current API exposes 8 risk categories / 35 sub-categories, 6 compliance frameworks and 21 attack techniques. Leaderboard model-level scores are JS-rendered and were not captured (UNVERIFIED).

## Used by
- Used by: Enkrypt AI (https://www.enkryptai.com/llm-safety-leaderboard ; reports on DeepSeek-R1 Jan 2025, AI21 Jamba Apr 2025, Databricks dbrx-instruct)
- Used by: Kilo Code model cards (Enkrypt blog listing "Enkrypt AI Risk Scores Are Now Live on Kilo Code", not fetched; UNVERIFIED)
