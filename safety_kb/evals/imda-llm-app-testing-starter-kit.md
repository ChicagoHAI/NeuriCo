# IMDA Starter Kit for Testing LLM-based Applications for Safety and Reliability

- Slug: imda-llm-app-testing-starter-kit
- What it measures: Pre-deployment "baseline safety and reliability" of LLM-based applications across five risks: hallucination and inaccuracy; bias in decision making; undesirable content; data leakage; vulnerability to adversarial prompts (direct and indirect injection) — via output testing (end-to-end) and component testing (RAG, filters, system prompt).
- Metric: Risk-specific; organisations set thresholds; guidance on "good" datasets, metrics and evaluators (LLM-as-judge with human calibration), attack success rates for adversarial prompts, parity/perturbation tests for bias.
- Open-source: y (guidelines PDF, free; tests "progressively made available on Project Moonshot")
- Runnable on a 0.5B-7B open model: y (method is model-agnostic; Moonshot cookbooks implement it; curated "core benchmarks" — AILuminate, PINT, CyberSecEval-4 prompt injection, BIPIA — are public)
- Source URL(s): https://www.imda.gov.sg/-/media/imda/files/about/emerging-tech-and-research/artificial-intelligence/starter-kit-for-testing-llm-based-applications-for-safety-and-reliability.pdf (Version 1.0, January 2026) ; https://aiverifyfoundation.sg/resources/starter-kit/
- Fetched: 2026-10-19

## Description
"The Starter Kit is a set of voluntary guidelines that consolidates emerging best practices and methodologies to test LLM apps for baseline safety and reliability. It focuses on five key risks ..." (p. 6). Developed from the Global AI Assurance Pilot ("real-world testing conducted by over 30 companies"), a public consultation "with feedback from more than 60 companies" (draft released 2025-05-29; consultation to 2025-06-25), and CSA/GovTech experts. Core benchmarks table (pp. 11-12, 85, 90): MLCommons AILuminate for undesirable content ("Available in Moonshot"); "MLCommons AIluminate Jailbreak Benchmark v1.0 ... Version 1.0 is expected in 2026"; Lakera PINT; CyberSecEval-4 prompt injections; Microsoft BIPIA; Singapore Factuality/Legal and ASEAN Factuality benchmarks "In development by IMDA (Available in Moonshot by 2026)". Automated red teaming section cites PAIR and Crescendomation and a Prism Eval BET case study on Changi Airport Group's AskMax chatbot.

## Used by
- Used by: IMDA / AI Verify Foundation (https://aiverifyfoundation.sg/resources/starter-kit/)
- Used by: Global AI Assurance Sandbox and AI TAP accredited testers (scoping framework; https://aiverifyfoundation.sg/ai-assurance/accredited-testers/)
