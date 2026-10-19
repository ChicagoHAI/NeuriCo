# SecureBio Virology Capabilities Test (VCT)

- Slug: vct-virology-capabilities-test
- What it measures: "troubleshooting complex virology laboratory protocols" (Gemini 3 Pro FSF Report p.6); multimodal/text MCQ.
- Metric: proportion correct with shuffled choices and repeated sampling.
- Open-source: partial (SecureBio; access terms UNVERIFIED in this fetch).
- Runnable on a 0.5B-7B open model: y if dataset access granted.
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_3_pro_fsf_report.pdf (pp.6-7)
- Fetched: 2026-10-19

## Description
"Gemini 3 Pro's performance on Securebio VCT ... shows no statistically significant changes" versus Gemini 2.5 Deep Think (p.6).

## Used by
- Used by: Amazon (Nova 2 Lite 0.29, Nova Premier 0.30, Nova 1 Pro 0.15; https://arxiv.org/pdf/2601.19134)
- Used by: xAI (text-only subset; Grok 4 0.60 API / 0.71 Web vs 22.1% expert; Grok 4.5 65.5, 4.6 67.4, 4.7 63.0, plus internal 'Biosecurity VCT'; https://data.x.ai/2025-08-20-grok-4-model-card.pdf ; https://media.x.ai/v1/website/card4p7-3a96f40b.pdf)
- Used by: Google (frontier safety) — CBRN MCQ signal (labs/google/frontier-safety-framework.md)
- Used by: SecureBio (https://arxiv.org/abs/2504.16137 ; see third_party/academic-and-nonprofit-auditors.md)
- Used by: SecureBio / OpenAI GPT-6 Astra system card sec. 10.1.1.4 (https://deploymentsafety.openai.com/gpt-6-astra); VCT-v2 announced 2026-09-11 (https://securebio.org/virologytest)
- Used by: OpenAI (run by SecureBio as an external bio evaluation for OpenAI releases. GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
