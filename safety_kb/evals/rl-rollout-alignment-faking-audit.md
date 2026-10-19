# RL training rollout audit for alignment faking and beyond-episode drives

- Slug: rl-rollout-alignment-faking-audit
- What it measures: Whether a model, during real RL training, reasons about training/evaluation regimes and strategically alters behavior (4-level rubric: L1 awareness, L2 local grader-pleasing, L3 conditional divergence, L4 alignment faking / training manipulation), and whether it expresses beyond-episode instrumental drives (self-preservation, goal-content integrity, non-task resource acquisition).
- Metric: % of sampled rollouts flagged per level by two LLM autoraters, each run with two judge models; 95% Wilson CIs; manual audit of top flags; autorater red-teamed with spliced adversarial examples.
- Open-source: n
- Runnable on a 0.5B-7B open model: y if one controls the RL run (needs raw CoT from training rollouts); not possible black-box.
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
"stratified random sample of 10,000 multi-step agentic RL training rollouts across 60 task-environment and training-stage strata (comprising 11,334 context-window spans)" judged by Gemini 3.1 Pro and 3.8 Flash (p.99). Results: L3/L4 0/10,000 ("upper bound of roughly 0.03% to 0.05%"), L1 6.3-7.3%, L2 1.1-5.2%; beyond-episode drives L4 0, L3 9/10,000 with 7 genuine (curiosity/permission probing); 906 context-handoff rollouts with no resistance (pp.100-101).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.84, 99-101; labs/google/gemini-4-safety-report.md)
