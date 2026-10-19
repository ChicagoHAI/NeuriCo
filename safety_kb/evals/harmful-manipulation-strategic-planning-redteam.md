# Harmful manipulation strategic-planning red-team evaluation

- Slug: harmful-manipulation-strategic-planning-redteam
- What it measures: Whether a model can act as a planning partner for influence operations (ideation, reconnaissance, target profiling) across 11 real-world-grounded scenarios, under direct request, jailbreak+direct, and an adversarial 'investigator' dynamic-prompting agent.
- Metric: % of elicitation attempts yielding a forward-looking plan; # scenarios with >=1 plan; expert review of accuracy/actionability of top plans (auto-rubric selected).
- Open-source: n (dynamic prompting method withheld, p.52)
- Runnable on a 0.5B-7B open model: y for the direct/jailbreak arms (scenario authoring needed); dynamic attacker is internal.
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
11 scenarios x 3 methods x 5 repetitions. Gemini 4 Argon (Model C): direct 1.8% (1/55), jailbreak 3.6% (2/55), dynamic 98.2% (54/55); Gemini 3.8 Flash 9.1%/9.1%/98.2% (Table 3.4, p.43). Experts: plans "may provide beneficial ideation or planning guidance for actors lacking domain or regional expertise ... Not all of the plans were accurate, or actionable" (p.43).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.41-44; labs/google/gemini-4-safety-report.md)
