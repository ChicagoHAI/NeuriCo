# LAB-Bench (incl. Cloning Scenarios)

- Slug: lab-bench
- What it measures: biology research-capability MCQs (e.g. cloning scenarios, protocol troubleshooting, sequence manipulation) used as an indirect signal of bio uplift.
- Metric: proportion correct (Google shuffles answer choices and asks each question n times).
- Open-source: y (FutureHouse LAB-Bench; link UNVERIFIED in this fetch — not fetched directly).
- Runnable on a 0.5B-7B open model: y (text MCQ).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_3_pro_fsf_report.pdf (pp.6-7, Fig.1)
- Fetched: 2026-10-19

## Description
"We observe statistically significant improvements on LAB-Bench, with a notable improvement on the Cloning Scenarios benchmark compared to the previous best model" (Gemini 3 Pro FSF Report p.6). Google treats MCQs as "necessary, but not sufficient" signals with no pass criterion.

## Used by
- Used by: G42 (preliminary bio evaluation example; G42 framework PDF)
- Used by: Amazon (ProtocolQA 108-item subset: Nova Premier 0.48, Nova 2 Lite 0.49; https://arxiv.org/pdf/2507.06260)
- Used by: xAI (ProtocolQA/FigQA/CloningScenarios from Grok 4.1; 'LAB-Bench practical MCQ' 71.1->80.7->76.8 and 'ProtocolQA open-ended' 87.0->79.6->70.4 in 4.5/4.6/4.7; https://data.x.ai/2025-11-17-grok-4-1-model-card.pdf ; https://media.x.ai/v1/website/card4p7-3a96f40b.pdf)
- Used by: Google (frontier safety) — CBRN MCQ signal (labs/google/frontier-safety-framework.md)
- See also: evals/labbench.md (LABBench 2, Gemini 4 Argon).
- Used by: UK AISI Inspect Evals lab_bench (https://github.com/UKGovernmentBEIS/inspect_evals)
- Used by: OpenAI (ProtocolQA, a LAB-Bench task, is run by OpenAI as "ProtocolQA Open-Ended" and is one of the four Biological & Chemical High-threshold evals. GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
