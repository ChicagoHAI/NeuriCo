# AI Control APPS backdoor setting (original control evaluation)

- Slug: ai-control-apps-backdoor
- What it measures: Whether control protocols prevent an untrusted model (GPT-4) from submitting backdoored solutions to APPS programming problems, with a trusted weaker model (GPT-3.5) and limited human audits
- Metric: Safety (no backdoor submitted) vs usefulness; protocols: trusted monitoring, trusted editing, untrusted monitoring
- Open-source: y: ControlArena 'apps' setting (https://control-arena.aisi.org.uk/settings/apps.html)
- Runnable on a 0.5B-7B open model: y (trusted model can be a small open model)
- Source URL(s): https://arxiv.org/abs/2312.06942 ; https://www.redwoodresearch.org/research/ai-control
- Fetched: 2026-10-19

## Description
"we develop and evaluate pipelines of safety techniques ('protocols') that are robust to intentional subversion"; backdoors = "logical errors that are not caught by test cases".

## Used by
- Used by: Redwood Research (https://arxiv.org/abs/2312.06942)
- Used by: UK AISI ControlArena (https://github.com/UKGovernmentBEIS/control-arena)
