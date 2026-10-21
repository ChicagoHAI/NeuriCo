# AI Verify Testing Framework and Toolkit

- Slug: ai-verify-toolkit
- What it measures: Process checks against 11 AI governance principles (traditional and generative AI) and technical tests for traditional supervised ML (classification/regression on tabular and image data): fairness, explainability, robustness; Veritas plugin for financial-sector fairness tests.
- Metric: Plugin-specific metrics (fairness parity metrics, feature importance, robustness under perturbation) plus a process-check summary report; crosswalks to NIST AI RMF, NIST GenAI Profile, Hiroshima Process CoC, ISO/IEC 42001.
- Open-source: y (https://github.com/aiverify-foundation/aiverify , Apache-2.0; v2.0 modular plugins)
- Runnable on a 0.5B-7B open model: n as designed (technical tests target tabular/image supervised models; LLM testing is delegated to Project Moonshot) — the process checks are model-agnostic.
- Source URL(s): https://github.com/aiverify-foundation/aiverify ; https://aiverifyfoundation.sg/what-is-ai-verify/
- Fetched: 2026-10-19

## Description
README: "AI Verify is an AI governance testing framework and software toolkit that validates the performance of AI systems against a set of internationally recognised principles through standardised tests ... It can perform technical tests on common supervised learning classification and regression models for most tabular and image datasets. It however does not define AI ethical standards and does not guarantee that any AI system tested will be free from risks or biases or is completely safe." AI Verify 2.0 adds a modular architecture, independently runnable test algorithms, a redesigned test-engine worker, Veritas integration for financial institutions and more computer-vision evaluations. The framework page lists crosswalks dated 2023-10-13 (NIST AI RMF), 2025-05-29 (NIST GenAI Profile; Hiroshima CoC) and ISO/IEC 42001:2023.

## Used by
- Used by: AI Verify Foundation / IMDA (https://aiverifyfoundation.sg/what-is-ai-verify/)
