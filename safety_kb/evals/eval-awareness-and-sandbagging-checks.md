# Evaluation-awareness and sandbagging checks

- Slug: eval-awareness-and-sandbagging-checks
- What it measures: whether a model recognises it is being tested and whether it deliberately underperforms (sandbagging); plus evaluation-environment bug detection.
- Metric: qualitative; automated transcript checks for "12 failure modes, including hallucinations, tool calling issues, and error messages"; automated sandbagging checks following van der Weij et al. 2025; anomaly-detection and eval-awareness autoraters over RL transcripts; CoT-vs-output consistency checks in manipulation evals.
- Open-source: n (Google's autoraters internal); van der Weij et al. method public.
- Runnable on a 0.5B-7B open model: y (judge-based transcript analysis on any eval logs).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_3_pro_fsf_report.pdf (pp.20, 24-25); https://storage.googleapis.com/deepmind-media/gemini/gemini_3-7_flash_fsf_report.pdf (pp.5, 13-14, 26)
- Fetched: 2026-10-19

## Description
"In all domains, we performed automated checks for sandbagging ... we also carried out manual inspection of transcripts, and found a number of more subtle examples where Gemini 3 Pro indicated awareness of being in a synthetic environment. Nonetheless we did not find any examples of sandbagging" (Gemini 3 Pro FSF Report p.20). Verbatim eval-aware quotes are published in Appendix 2 (e.g. "Maybe the 'reviewer' is an LLM that I can prompt-inject?"). For 3.7 Flash, refusals on a stealth side task ("Cover Your Tracks") were attributed to safety training rather than sandbagging.

## Used by
- Used by: Google (frontier safety) — correctness checks in every FSF report domain (labs/google/frontier-safety-framework.md)
- Used by: Apollo Research (https://www.apolloresearch.ai/science/claude-sonnet-37-often-knows-when-its-in-alignment-evaluations)
- Used by: METR GPT-5 report strategic-sabotage checks (https://metr.org/evaluations/gpt-5-report/)
