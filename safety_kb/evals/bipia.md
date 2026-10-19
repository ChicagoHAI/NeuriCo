# BIPIA (Benchmark for Indirect Prompt Injection Attacks, Microsoft)

- Slug: bipia
- What it measures: Whether an LLM application follows attacker-planted instructions embedded in externally ingested content (webpages, emails, documents) instead of the user's benign request.
- Metric: Attack success rate (share of cases where the planted instruction is followed) — per the Starter Kit's description; exact metric definitions UNVERIFIED (primary source not fetched).
- Open-source: y (Microsoft GitHub release; repo URL not fetched — UNVERIFIED)
- Runnable on a 0.5B-7B open model: y in principle (text-only prompts with injected content) — UNVERIFIED from a primary source.
- Source URL(s): secondary mention — IMDA Starter Kit v1.0, section 3.6.2 "Core Benchmarks for Indirect Prompt Attacks" (https://www.imda.gov.sg/-/media/imda/files/about/emerging-tech-and-research/artificial-intelligence/starter-kit-for-testing-llm-based-applications-for-safety-and-reliability.pdf)
- Fetched: 2026-10-19

## Description
Starter Kit v1.0 (p. 90): "Microsoft's BIPIA benchmark [5]. BIPIA evaluates indirect prompt injection by combining benign user requests with attacker-planted instructions embedded in externally ingested content (e.g. webpages or documents), and then measuring whether the app follows those instructions instead of the user's intent." It is the only core benchmark the Starter Kit names for indirect prompt attacks. Primary paper/repo not fetched for this entry.

## Used by
- Used by: IMDA Starter Kit v1.0 (https://www.imda.gov.sg/-/media/imda/files/about/emerging-tech-and-research/artificial-intelligence/starter-kit-for-testing-llm-based-applications-for-safety-and-reliability.pdf)
