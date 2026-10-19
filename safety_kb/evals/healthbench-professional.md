# HealthBench Professional

- Slug: healthbench-professional
- What it measures: safety, accuracy and communication quality in realistic healthcare conversations (open-source HealthBench variant); xAI reports it as a medical capability/safety signal.
- Metric: rubric score (%) by LLM grader.
- Open-source: y (HealthBench, OpenAI; "Professional" subset per Grok 4.7 card)
- Runnable on a 0.5B-7B open model: y (needs grader)
- Source URL(s): https://media.x.ai/v1/website/card4p7-3a96f40b.pdf
- Fetched: 2026-10-19

## Description
Grok 4.7 card §5.1: "HealthBench-Professional is an open-source benchmark for measuring safety, accuracy, and communication in realistic healthcare settings ... Grok 4.6 (high) was used as the grader model for Grok 4.7 results ... Tasks that were rejected by safety filters were scored as zero."

## Used by
- Used by: xAI (Grok 4.7 56.7% xhigh, Grok 4.6 48.5%; GPT-6 Astra 63.4, Fable 5.1 62.1 per xAI; https://media.x.ai/v1/website/card4p7-3a96f40b.pdf)
- Used by: OpenAI (author; introduced Apr 2026 and reported in the 2026 cards' health sections. Tech-report URL not resolvable from the cards - UNVERIFIED. https://deploymentsafety.openai.com/gpt-6-1-sol)
