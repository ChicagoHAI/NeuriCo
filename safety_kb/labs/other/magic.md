# Magic — AGI Readiness Policy v1.0

- URL: https://magic.dev/agi-readiness-policy (raw `safety_kb/sources/other-frameworks/magic-agi-readiness-policy.txt`)
- Fetched: 2026-10-19. "Version 1.0 — July 2, 2024". Page banner on 2026-10-19: "Note: This policy is outdated. We're working on an update." (no update found). "Our commitments were created with assistance from METR".

## Trigger
"when, at the end of a training run, our models exceed a threshold of 50% accuracy on LiveCodeBench, we will trigger our commitment to incorporate a full system of dangerous capabilities evaluations and planned mitigations into our AGI Readiness Policy, prior to substantial further model development, or publicly deploying such models." (Reference scores at the time: Claude-3.5-Sonnet 48.8%, GPT-4-Turbo 43.9%.) Also private internal coding benchmarks with "privately specified thresholds". "If we have not developed adequate dangerous capability evaluations by the time these benchmark thresholds are exceeded, we will halt further model development until" they exist. Quarterly reports to the Board; threshold changes require Board approval with external advisers.

## Covered Threat Models and critical capability thresholds (verbatim excerpts)
- Cyberoffense: "the cost of discovery of new zero-days or breaking critical infrastructure for a malicious expert actor is reduced by at least 10x; accessing classified and not previously accessible information from a major government; a talented Computer Science undergrad level malicious actor spending 3 months and ..." (truncated in fetched page).
- AI R&D: "facilitates a dramatic acceleration in the rate of effective compute scaling or can effectively replace high-level machine learning researchers."
- Autonomous Replication and Adaptation: "could autonomously maintain its own operation executing cybercrime and using the proceeds to create arbitrarily many replicas of itself."
- Biological Weapons Assistance: "a non-expert malicious actor can synthesize a viable pandemic agent, or an expert can synthesize a novel biological threat."

## Mitigations (illustrative)
Information security per RAND "Securing AI Model Weights" (harden weights/code; internal compartmentalization); deployment: harm refusal, output monitoring/classifiers (also for internal use). "A full set of mitigations will be detailed publicly by the time we complete our policy implementation".

## What is NOT disclosed
Whether the LiveCodeBench trigger has been crossed (frontier models exceeded 50% on LiveCodeBench long ago; the policy was never updated — it is the oldest unrevised framework in the set); no actual dangerous-capability evaluations; no security levels; no third-party evaluation; no public reporting since 2024. SaferAI: 11% overall (12/14/8/10).
