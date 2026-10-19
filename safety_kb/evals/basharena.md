# BashArena

- Slug: basharena
- What it measures: Control setting: 637 Linux sysadmin/infra tasks with four sabotage objectives (execute malware, exfiltrate secrets, escalate privileges, disable firewall)
- Metric: Sabotage success while evading monitor at fixed trajectory-wise FPR; task completion; monitor detection
- Open-source: y: https://github.com/redwoodresearch/basharena_public ; ControlArena setting
- Runnable on a 0.5B-7B open model: y (monitor can be small; attacker policies need capable models)
- Source URL(s): https://arxiv.org/abs/2512.15688 ; https://www.bash-arena.com/
- Fetched: 2026-10-19

## Description
"Claude Sonnet 4.5 successfully executes sabotage while evading monitoring by GPT-4.1 mini 26% of the time, at 4% trajectory-wise FPR."

## Used by
- Used by: Redwood Research (https://arxiv.org/abs/2512.15688)
- Used by: UK AISI ControlArena (https://github.com/UKGovernmentBEIS/control-arena)
