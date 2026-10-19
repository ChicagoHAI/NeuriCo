# Chain-of-thought legibility / monitorability metrics (Emmons et al. 2025)

- Slug: cot-monitorability-legibility
- What it measures: whether model reasoning traces are human-comprehensible and informative of the final output; underpins CoT-monitoring as a misalignment mitigation.
- Metric: autorater-judged % of transcripts "comprehensible" and % "informative of the model's output" (Gemini 3 Pro: 99.98% / 99.85%); qualitative manual inspection.
- Open-source: method y (arXiv 2507.05246, "When Chain of Thought is Necessary, Language Models Struggle to Evade Monitors"); Google's transcripts n.
- Runnable on a 0.5B-7B open model: y (needs a judge model and reasoning-style outputs).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_3_pro_fsf_report.pdf (pp.18-19); https://arxiv.org/abs/2507.05246
- Fetched: 2026-10-19

## Description
"We analyzed the readability of the thoughts produced by Gemini 3 Pro and found them to appear readable ... We also used the two metrics proposed by Emmons et al. (2025) ... We observe no drop compared to the previous generation of Gemini" (Gemini 3 Pro FSF Report p.18). Google ties this to training practice: RL "includes length penalties on the thoughts ... other rewards are computed without reference to the thoughts."

## Used by
- Used by: Google (frontier safety) — CoT legibility addendum in FSF reports; CoT monitoring is the named mitigation for the Stealth/SA TCL (labs/google/frontier-safety-framework.md)
- Used by: OpenAI (openai/monitorability-evals (Apache-2.0) plus Guan et al. 2025, arXiv 2512.18311; 13 evaluations / 24 environments. Astra shows a monitorability regression vs GPT-5.6 Sol on CoT-only and full-context scopes. https://github.com/openai/monitorability-evals ; https://openai.com/index/evaluating-chain-of-thought-monitorability/)
