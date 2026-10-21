# SHUSHCAST (METR monitorability evaluation)

- Slug: shushcast-monitorability
- What it measures: Whether LLM monitors catch agents doing covert side tasks alongside main tasks, and whether agents can evade monitoring; effect of reasoning-trace access
- Metric: Monitor catch rate at a 5% false-positive threshold on innocent runs; 95% bootstrap CIs
- Open-source: n (prototype; no repo found)
- Runnable on a 0.5B-7B open model: y in principle (any agent/monitor pair; side tasks are hard for small models)
- Source URL(s): https://metr.org/blog/2026-01-19-early-work-on-monitorability-evaluations/
- Fetched: 2026-10-19

## Description
"a prototype evaluation called SHUSHCAST that tests monitors' ability to catch AI agents doing side tasks, and AI agents' ability to bypass this monitoring". Access to GPT-5 reasoning traces raised averaged monitor catch rate from 52% to ~80%; GPT-5 fails side tasks in 9% of runs.

## Used by
- Used by: METR (https://metr.org/blog/2026-01-19-early-work-on-monitorability-evaluations/)
