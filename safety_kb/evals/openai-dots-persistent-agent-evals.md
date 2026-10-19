# OpenAI "dots" persistent-agent evaluations

- Slug: openai-dots-persistent-agent-evals
- What it measures: Safety and alignment of always-on, proactive, persistent agents (each with its own cloud computer and browser, delegating to subagents, acting across ChatGPT, text, email and Slack under a time budget): behaviour as scope or permissions change mid-task, boundary maintenance across chained tasks, robustness to misleading proactivity inputs, auto-review efficacy, and whether persistence changes monitor evasion.
- Metric: alignment pass rate per episode; flag rate for moderate/severe scope violations; misalignment rate over tasks; auto-review recall vs denial rate on unedited traffic; evasion rates by monitor scope.
- Open-source: n - internal product evals.
- Runnable on a 0.5B-7B open model: n as-is; the designs (mid-task permission revocation; N intervening tasks between an initial and final task; misleading proactive hints) are the clearest published template for evaluating persistent agents and are reimplementable.
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra Appendix B (sections B.2-B.6)
- Fetched: 2026-10-19

## Description
Key results: prompt-injection red-teaming with 50,000 simulated emails (166 attacks per 500-email rollout) produced **0 scored successes**, and 0 in 2,638 iterative attempts; Adapting to Changing Scope and Permissions 91.8% pass (45/49, including all 17 explicit permission-change cases); Maintaining Boundaries Across Chained Tasks showed no severe breach but moderate scope-violation flags rising from 8.6% to 19.7% when intervening tasks doubled from five to ten; Robustness to Misleading Proactivity Inputs 0.00% over 151 tasks; alignment results were roughly flat across simulated time budgets from 4 minutes to one year. Auto-review was evaluated on 30 synthetic disallowed trajectories per threat category plus 5,000 unedited de-identified employee requests for the denial rate, with recall weakest on "ambiguous authorization".

## Used by
- Used by: OpenAI (GPT-6 Astra card, dots appendix; labs/openai/system-cards.md)
