# Grok 4.1 Model Card

- URL: https://data.x.ai/2025-11-17-grok-4-1-model-card.pdf
- Fetched: 2026-10-19 (raw text: `safety_kb/sources/xai/2025-11-17-grok-4-1-model-card-guess.txt`; URL inferred from naming pattern, verified by PDF title)
- Document version/date: November 17, 2025 (6 pp.). Two configurations: Grok 4.1 Thinking (T) and Non-Thinking (NT), evaluated "with our production system prompt" and "a new and more robust input filter model". Framework cited: RMF.

## Table 1 (malicious use)
| Eval | 4.1 T | 4.1 NT |
|---|---|---|
| Refusals answer rate (internal multilingual) | 0.07 | 0.05 |
| + user jailbreak | 0.02 | 0.00 |
| + system jailbreak | 0.02 | 0.00 |
| AgentHarm (no JB) | 0.14 | 0.04 |
| AgentDojo ASR | 0.05 | 0.01 |
Correction disclosed: "results in previous model cards were reported with an error in the evaluation settings, where only the English prompts were evaluated. Here, we report true multilingual results, which are not directly comparable to previous results." (§2.1.2)

## Table 2 (input filter, first time reported): false negative rate
Restricted biology 0.03; + prompt injection 0.20; restricted chemistry 0.00; + prompt injection 0.12. (The RMF criterion is an answer rate <1/20 on restricted queries; the 0.20/0.12 under prompt injection exceed it, though the card does not relate them to the criterion.)

## Table 3 (propensities): Grok 4 / 4.1 T / 4.1 NT
MASK dishonesty 0.43 / 0.49 / 0.46; sycophancy 0.07 / 0.19 / 0.23. Both metrics regressed vs Grok 4 despite "training the model to be honest" and "to give less sycophantic responses". No political-bias result reported (dropped).

## Table 4 (dual-use, 4.1 T, safeguards removed) with human baselines
WMDP Bio 0.87 (human 0.61); VCT 0.61 (0.22); BioLP-Bench 0.37 (0.38); ProtocolQA 0.79 (0.79); FigQA 0.34 (0.77); CloningScenarios 0.46 (0.60); WMDP Chem 0.84 (0.43); WMDP Cyber 0.84; CyBench 0.39; MakeMeSay 0.00. New additions: LAB-Bench subsets ProtocolQA / FigQA / CloningScenarios (Laurent et al. 2024), human baselines from Dev et al. (RAND 2025). "Grok 4.1 matches or outperforms human baselines on knowledge and protocol troubleshooting questions, but performs worse ... on multi-modal and multi-step reasoning benchmarks".

## What is NOT run or disclosed
No third-party testing; no R/N eval; no autonomy/AI-R&D eval; no pre-mitigation refusal numbers; no analysis of why honesty/sycophancy regressed; the filter prompt-injection FNR (20%) is not tied to the RMF threshold. The card promises "real-time safety monitoring" only as a future exploration.
