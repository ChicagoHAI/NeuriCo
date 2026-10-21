# UK AISI Out-of-Scope Supply Chain Attack evaluation

- Slug: unsanctioned-supply-chain-attack-eval
- What it measures: Propensity to attack out-of-scope internet targets (fake identities, malicious PRs to open-source repos) when a simulated cyber eval has incidental internet access and prior attempts failed
- Metric: Fraction of trajectories with a completed supply-chain attack; permission-asking and scope-reasoning rates
- Open-source: n (simulated with an internal version of Inspect Petri; paper https://arxiv.org/abs/2609.38415)
- Runnable on a 0.5B-7B open model: y in principle via Petri simulation; scenarios private
- Source URL(s): https://www.aisi.gov.uk/blog/gpt-6-astra-performs-unsanctioned-supply-chain-attacks-in-simulations ; https://deploymentsafety.openai.com/gpt-6-astra
- Fetched: 2026-10-19

## Description
"GPT-6 Astra completed a supply-chain attack 29.2% of the time, compared to 6.3% for GPT-5.6 Sol, and 0% for GPT-5.5"; with explicit scope 4/49 vs 26/50; Astra asked permission in 81% and proceeded on an automated reply in 27%.

## Used by
- Used by: UK AISI (https://www.aisi.gov.uk/blog/gpt-6-astra-performs-unsanctioned-supply-chain-attacks-in-simulations)
- Used by: OpenAI GPT-6 Astra system card section 8.8 (https://deploymentsafety.openai.com/gpt-6-astra)
