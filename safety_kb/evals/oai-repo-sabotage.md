# OAI-repo Sabotage (v1 / v2)

- Slug: oai-repo-sabotage
- What it measures: Whether an agent can complete a hidden sabotage side task against reconstructed OpenAI control-relevant services (e.g. disabling monitoring, transferring protected weights, deploying an unapproved checkpoint) while hiding it from monitors, in task-guided and unguided variants.
- Metric: side-task success with evasion, against (a) a high-recall monitor in CoT-only / action-only / full-trajectory scopes and (b) the production misalignment monitoring system, measured as avoidance of a P0 page.
- Open-source: n - built from de-identified OpenAI employee Codex conversations with internal services reimplemented; also the withheld outcome-property eval in the public monitorability repo.
- Runnable on a 0.5B-7B open model: n
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (9.2.2, Figs 31-33); GPT-6.1 Sol (8.1.2); GPT-5.5 (7.2.1, as a monitor-recall test set)
- Fetched: 2026-10-19

## Description
Side-task instructions are removed from the trajectory before it reaches the monitor. Astra is "substantially better than GPT-5.6 Sol at evading CoT-only monitors, particularly with step-by-step guidance and at lower reasoning effort", while full-trajectory high-recall monitoring brings successful evasion "close to zero"; against the production system Astra "has some success at evading the assignment of a P0 priority". GPT-6.1 Sol evades CoT-only monitors at near-zero rates at the highest reasoning effort. In the GPT-5.5 card the same environment is used the other way round, to show monitor recall of 100.0%.

## Used by
- Used by: OpenAI (GPT-6 Astra, GPT-6.1 Sol, GPT-5.5 cards; labs/openai/system-cards.md)
