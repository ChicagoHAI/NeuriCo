# OpenAI simple-evals (SimpleQA, BrowseComp, HealthBench reference implementations)

- Slug: simple-evals
- What it measures: Lightweight reference implementations OpenAI published so that its reported accuracy numbers could be reproduced: SimpleQA (short-form factuality), BrowseComp (browsing agents), HealthBench, plus legacy wrappers for MMLU, MATH-500, GPQA, DROP, MGSM, HumanEval.
- Metric: per-benchmark: accuracy; for SimpleQA also attempted/abstained/incorrect decomposition; HealthBench uses rubric grading.
- Open-source: y - https://github.com/openai/simple-evals (MIT), but **deprecated since July 2025**: "will no longer be updated for new models or benchmark results"; it continues to host HealthBench, BrowseComp and SimpleQA.
- Runnable on a 0.5B-7B open model: y - the zero-shot CoT setting and OpenAI/Anthropic samplers are easy to repoint at local models; SimpleQA grading needs a judge.
- Source URL(s): https://github.com/openai/simple-evals ; SimpleQA data at https://openaipublic.blob.core.windows.net/simple-evals/simple_qa_test_set.csv (4,326 questions)
- Fetched: 2026-10-19

## Description
The SimpleQA accuracy/abstention decomposition is the basis of OpenAI's hallucination argument ("Why language models hallucinate", Nature 2026): accuracy-only scoreboards reward guessing, so errors should be penalised more than abstentions. The hallucinations-paper-experiments repo reproduces that experiment end-to-end. SimpleQA and PersonQA were the hub's hallucination evals and have not been updated for any model after GPT-5.

## Used by
- Used by: OpenAI (Safety Evaluations Hub hallucination family; hallucination research; labs/openai/evaluations-hub.md, labs/openai/open-tools-and-methods.md)
