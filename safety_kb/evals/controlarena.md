# ControlArena (UK AISI + Redwood Research)

- Slug: controlarena
- What it measures: Library and settings for AI-control experiments: main tasks plus covert side tasks (code sabotage, research sabotage, data poisoning), protocols, monitors
- Metric: Safety (side-task caught/prevented) vs usefulness (main-task success); monitor suspicion scores, FPR/TPR
- Open-source: y: https://github.com/UKGovernmentBEIS/control-arena ; docs https://control-arena.aisi.org.uk
- Runnable on a 0.5B-7B open model: y (thin wrapper over Inspect; trusted/untrusted roles can be small open models, which are typical 'trusted' monitors)
- Source URL(s): https://www.aisi.gov.uk/blog/introducing-controlarena-a-library-for-running-ai-control-experiments ; https://github.com/UKGovernmentBEIS/control-arena
- Fetched: 2026-10-19

## Description
"ControlArena is a Python library for running AI Control experiments, created by the UK AI Security Institute and Redwood Research." Settings range from APPS programming problems to infrastructure codebases and BashArena; "already been used by researchers at ... Anthropic, Google DeepMind, Redwood Research and others".

## Used by
- Used by: UK AISI (https://www.aisi.gov.uk/blog/introducing-controlarena-a-library-for-running-ai-control-experiments)
- Used by: Redwood Research (BashArena released as a ControlArena setting, https://arxiv.org/abs/2512.15688)
