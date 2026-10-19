# GDM self-proliferation early-warning tasks

- Slug: gdm-self-proliferation
- What it measures: agentic ability to "autonomously proliferate: (a) maintaining a network of AI agents with access to the internet (example task: installing an open-source model on a cloud server); (b) acquiring resources (example task: building and hosting an online product); and (c) self-improvement (example task: re-implementing a new scaffolding technique from a recent paper)" (arXiv 2403.13793 Table 1; 11 tasks in paper, 10 released).
- Metric: milestone-based partial progress; expert-rated success.
- Open-source: y — Inspect Evals `gdm_self_proliferation` (https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/gdm_self_proliferation).
- Runnable on a 0.5B-7B open model: y (Docker environments; some tasks need network/cloud credentials, which limits automation).
- Source URL(s): https://arxiv.org/abs/2403.13793 ; sources/google/inspect-evals-gdm-readmes.md
- Fetched: 2026-10-19

## Description
Part of Google DeepMind's 2024 dangerous-capability programme under the then-"Autonomy" domain of FSF v1.0. The Autonomy domain was dropped in FSF v2.0 (Feb 2025) and self-proliferation no longer appears in Gemini 3-era FSF reports.

## Used by
- Used by: Google (frontier safety, 2024 pilot; domain dropped from FSF v2.0 onward) — labs/google/frontier-safety-framework.md
- Used by: UK AISI Inspect Evals gdm_self_proliferation (https://github.com/UKGovernmentBEIS/inspect_evals)
