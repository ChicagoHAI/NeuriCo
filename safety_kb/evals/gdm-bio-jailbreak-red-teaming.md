# External bio jailbreak red teaming and adversarial stress-test set

- Slug: gdm-bio-jailbreak-red-teaming
- What it measures: Robustness of the mitigated system against jailbreaks aimed at bio sub-tasks; plus an internal adversarial set for dangerous requests.
- Metric: Fraction of bio sub-tasks unlocked ('less than 1%'); adversarial-set violations 'reduced nearly twofold'. Not on the card.
- Open-source: n
- Runnable on a 0.5B-7B open model: n (hazardous); generic jailbreak robustness is runnable
- Source URL(s): https://blog.google/innovation-and-ai/technology/safety-security/gemini-4-model-safety-security/
- Fetched: 2026-10-19

## Description
Safety blog: 'external bio jailbreak red teaming could only unlock less than 1% of bio sub-tasks we test for'; 'On an adversarial set meant to stress test the model, violations reduced nearly twofold — also significantly better than previous Gemini models.'

## Used by
- Used by: Google (Gemini 4 Argon) — model card https://deepmind.google/models/model-cards/gemini-4-argon/
- Used by: Google (frontier safety) — the Gemini 3.7 Flash FSF report describes the internal coverage / static / adaptive / dynamic jailbreak suites and Gray Swan Shade (28 cyber, 53 bio tasks) with OSR/QSR metrics; see evals/gdm-safeguard-coverage-and-jailbreak-robustness.md.
