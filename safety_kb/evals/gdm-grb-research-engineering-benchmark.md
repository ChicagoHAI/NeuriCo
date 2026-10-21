# GRB (Google internal research engineering benchmark)

- Slug: gdm-grb-research-engineering-benchmark
- What it measures: "autonomous execution of highly realistic research engineering tasks ... 74 tasks spanning the pre-training and post-training lifecycle ... from data management, to evaluations, to analysis and experiment management", run in Google's internal coding-agent scaffold, sandboxed, 2h timeout, scripted verifiers.
- Metric: pass@1; CCL ruled out if < 90% ("a model theoretically needs to complete 100% ... we conservatively set our safety margin at 90%").
- Open-source: n.
- Runnable on a 0.5B-7B open model: n (internal; ~20% of tasks had verifier bugs in Aug 2026).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_3-7_flash_fsf_report.pdf (pp.36-38)
- Fetched: 2026-10-19

## Description
Gemini 3.7 Flash: 27% pass@1 (max 47% if all bugged tasks counted as passes); Gemini 3.1 Pro ~16% (preliminary). Used for both ML R&D Acceleration and Automation Level 1 CCLs. Gemini 4 Argon also uses "an internal benchmark" (see labs/google/gemini-4-safety-report-notes.md).

## Used by
- Used by: Google (frontier safety) — ML R&D CCLs from Gemini 3.7 Flash onward (labs/google/frontier-safety-framework.md)
- See also: evals/gdm-ml-rd-internal-benchmark.md (Gemini 4 Argon results); evals/re-bench.md.
