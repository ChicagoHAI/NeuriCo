# GDM safeguard coverage and adversarial-robustness evaluations (cyber/CBRN)

- Slug: gdm-safeguard-coverage-and-jailbreak-robustness
- What it measures: effectiveness of deployed mitigations on three axes: Coverage (Violation Rate on malicious queries; Benign Refusal Rate), Adversarial Robustness (static template jailbreaks; adaptive automated attacker; multi-conversation "dynamic" bio attacker scored against rubrics; Gray Swan "Shade" agent on 28 cyber / 53 bio tasks), Impact on Benign Uses (random presumed-benign traffic).
- Metric: Violation Rate, Benign Refusal Rate, Objective Success Rate (goal achieved at least once) vs Query Success Rate (per-prompt breach); Gray Swan's "Behavior Success Rate"/"Attempt Success Rate" analogues.
- Open-source: n (datasets: ~1,000 cyber conversational, ~1,500 CBRN conversational, 700+ benign CBRN science; internal/partner).
- Runnable on a 0.5B-7B open model: methodology y (public jailbreak suites can emulate it); exact sets n.
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_3-7_flash_fsf_report.pdf (pp.28-33)
- Fetched: 2026-10-19

## Description
"We look at three main things when assessing the strength of our training and model guardrails: Coverage ... Adversarial Robustness ... Impact on Benign Uses" (3.7 Flash FSF Report p.29). Claimed results: "~0% violations for topics related to bio weapons queries (sourcing, enhancement, weaponization) and chemical weapons"; "close to 0% objective success rate against common jailbreaks templates and decent robustness against adaptive and dynamic attackers" (pp.30, 33). Google frames safeguards as imposing "significant operational friction" rather than eliminating risk.

## Used by
- Used by: Google (frontier safety) — residual risk assessment / deployment mitigations under FSF 2.1.2 (labs/google/safety-program-overview.md)
- See also: evals/gray-swan-shade.md; evals/gdm-bio-jailbreak-red-teaming.md (Gemini 4 Argon).
