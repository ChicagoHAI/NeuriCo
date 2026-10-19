# MALT (Manually-reviewed Agentic Labeled Transcripts)

- Slug: malt
- What it measures: Ground-truth dataset of natural and prompted reward hacking, sandbagging, giving-up and eval-awareness behaviours on HCAST/RE-Bench transcripts, for validating monitors
- Metric: Monitor AUROC against labels (METR's o4-mini reward-hack monitor: 0.93)
- Open-source: y: https://huggingface.co/datasets/metr-evals/malt-transcripts-public ; https://huggingface.co/datasets/metr-evals/malt-public
- Runnable on a 0.5B-7B open model: y (a small model can be used as the monitor to be scored against MALT; it is a dataset, not a task suite)
- Source URL(s): https://metr.org/blog/2025-10-14-malt-dataset-of-natural-and-prompted-behaviors/
- Fetched: 2026-10-19

## Description
"103 unprompted examples of models exhibiting generalized reward hacking behavior ... 32 unprompted examples of models giving up on tasks ... 15 unprompted examples of models reasoning about elements of the task ... 34 unprompted examples of miscellaneous behavior, like evaluation awareness" plus confirmed benign controls (METR, Oct 14, 2025).

## Used by
- Used by: METR (https://metr.org/evaluations/gpt-5-report/)
