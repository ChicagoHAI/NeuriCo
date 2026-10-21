# PINT (Prompt Injection Test) Benchmark

- Slug: pint-benchmark
- What it measures: accuracy of prompt-injection *detection systems* (classifiers/guardrails) on a mixed set of injections, jailbreaks, hard negatives, chats and benign documents, in English and ~1,300 non-English inputs.
- Metric: "PINT Score" (percentage; higher is better; computed by the notebook from true/false positives/negatives over 4,314 labelled inputs).
- Open-source: y (https://github.com/lakeraai/pint-benchmark, MIT; code and example dataset public, the full proprietary evaluation set is not released)
- Runnable on a 0.5B-7B open model: y (targets any detector exposed as a text->bool function; e.g. protectai/deberta-v3-base-prompt-injection-v2 and meta-llama/Llama-Prompt-Guard-2-86M are scored in the README; a small LLM can be wrapped as a classifier)
- Source URL(s): https://github.com/lakeraai/pint-benchmark ; https://raw.githubusercontent.com/lakeraai/pint-benchmark/main/DETAILS.md
- Fetched: 2026-10-19

## Description
Per the README, PINT "provides a neutral way to evaluate the performance of a prompt injection detection system" without relying on public datasets that tools could optimise against. The dataset has 4,314 inputs (3,016 English, 1,298 non-English): prompt injections 5.2%, jailbreaks 0.9%, hard negatives 20.9%, user-agent chats 36.5%, benign public documents 36.5%. Scores (test dates 2025-05-02 to 2025-08-27): Lakera Guard 95.22%, AWS Bedrock Guardrails 89.24%, Azure AI Prompt Shield 89.12%, protectai deberta-v3-base-prompt-injection-v2 79.14%, Llama Prompt Guard 2 (86M) 78.76%, Google Model Armor 70.07%, Aporia 66.44%, Llama Prompt Guard 1 61.82%. DETAILS.md states "the configuration with the highest PINT score was chosen for a given solution", so scores are upper bounds. The repo is archived (read-only) and is a fork of CheckPointSW/pint-benchmark after Check Point acquired Lakera.

## Used by
- Used by: Lakera (https://github.com/lakeraai/pint-benchmark)
- Used by: IMDA Starter Kit v1.0 (core benchmark for evaluating prompt-injection detection/input filters; https://www.imda.gov.sg/-/media/imda/files/about/emerging-tech-and-research/artificial-intelligence/starter-kit-for-testing-llm-based-applications-for-safety-and-reliability.pdf)
