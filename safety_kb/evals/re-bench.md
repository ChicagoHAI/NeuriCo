# RE-Bench (METR Research Engineering Benchmark)

- Slug: re-bench
- What it measures: ability to automate ML research engineering: 7 tasks taking humans several hours (Google ran 5, omitting "Finetune GPT-2 for QA" and "Scaffolding for Rust Codecontest" which need internet).
- Metric: score normalised to a human-written solution; Google: 16 attempts x 2h per task, 32h budget, bootstrap of 24 runs, max within sample (mean for Scaling Law Experiment).
- Open-source: y (METR; Wijk et al. 2024).
- Runnable on a 0.5B-7B open model: y in principle (GPU-heavy tasks; small models score near zero).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_3_pro_fsf_report.pdf (pp.13-14)
- Fetched: 2026-10-19

## Description
"To measure progress towards the ML R&D CCLs, we adopt the Research Engineering Benchmark (RE-Bench) ... We adopt the METR modular scaffold with minimal changes" (Gemini 3 Pro FSF Report p.14). Gemini 3 Pro roughly doubled Gemini 2.5 on Scaling Law Experiment and Optimize LLM Foundry but stayed "substantially below the alert threshold" (threshold undisclosed). Replaced by the internal GRB benchmark in the Gemini 3.7 Flash report.

## Used by
- Used by: Amazon (Automated AI R&D domain; Nova Premier and Nova 2 Lite transcripts reviewed by METR; https://arxiv.org/pdf/2507.06260 ; https://arxiv.org/pdf/2601.19134)
- Used by: Google (frontier safety) — ML R&D CCLs, Gemini 3 Pro (labs/google/frontier-safety-framework.md)
- Used by: METR (https://metr.org/blog/2024-11-22-evaluating-r-d-capabilities-of-llms/ ; used in Claude 3.7 and o3 pre-deployment reports https://metr.org/evaluations/claude-3-7-report/)

- Used by: OpenAI (AI self-improvement capability reference; OpenAI's own self-improvement suite is Internal Research Debugging, KernelGen 1P, NanoGPT, PaperBench and SWE-Lancer. GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)

## Tooling (appended 2026-10-19)
Source (fetched 2026-10-19): https://arxiv.org/abs/2411.15114 (METR). "7 challenging, open-ended ML
research engineering environments"; 71 eight-hour expert attempts by 61 experts; best agents
score "4x higher than human experts" at a 2-hour budget, humans "2x the score of the top AI
agent" at 32 hours; best-of-k across time budgets. Relevance: the methodology (fixed time/token
budgets, best-of-k, human baselines per environment) is the template for judging our own
research-agent loop. Code/environment release not fetched here — UNVERIFIED.
