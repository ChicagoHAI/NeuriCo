# Epoch AI

- Org: Epoch AI (501(c)(3) nonprofit; "data-first research nonprofit investigating the future of artificial intelligence")
- Website: https://epoch.ai
- Fetched: 2026-10-19
- Raw text: /data/haokun_test/neurico/safety_kb/sources/epoch/
- Framing note: Epoch is a **capability tracker and benchmark administrator**, not a safety evaluator. It runs no misuse, alignment, or red-team evaluations; its relevance to this KB is (a) independent re-runs of capability benchmarks with published settings/logs, (b) the FrontierMath funding/access episode as a case study in evaluator independence, and (c) the ECI as a cross-benchmark capability scale.

## What they evaluate
- **Benchmarking Hub** (epoch.ai/benchmarks): internally-run evaluations (GPQA Diamond, MATH Level 5, Mock AIME 2024-2025, FrontierMath, SWE-bench Verified; later additions such as EBR-Bench, Chess Puzzles, MirrorCode, Epoch Automation Reports, Earthborne Rangers appear in nav) plus externally-administered results sourced "from official leaderboards or primary sources" (about-benchmarks-hub.txt).
- **FrontierMath program** (epoch.ai/frontiermath): three components — *Tiers 1-4* ("several hundred unpublished, highly challenging mathematics problems"; Tiers 1-3 undergraduate to advanced-graduate, Tier 4 research-level; "On 2026-06-12, we released v2 which addressed errors in 42% of problems"; "This project is supported by OpenAI"), *Open Problems* (unsolved research problems with computationally verifiable solutions; "supported by Schmidt Sciences"; verifier access sold), and *FrontierMath Erdős* (68 conjectures in Lean 4/Mathlib covering 65 erdosproblems.com problems open as of Aug 2026, curated by Thomas Bloom; proofs checked by Lean FRO's "Comparator"; agent built on Inspect deepagent with Lean, SageMath, Python, no network).
- **Epoch Capabilities Index (ECI)** (epoch.ai/eci): composite of "over 50 distinct benchmarks" fitted with performance = sigmoid(discriminability x (capability - difficulty)), yielding one ECI per model and one difficulty (EDI) per benchmark; domain variants: General, Software engineering, Math, Cyber ECI. Methodology paper "A Rosetta Stone for AI Benchmarks" was "funded by Google DeepMind, and written in collaboration with researchers from their AGI Safety & Alignment team. However, the ECI is an independent Epoch AI product that Epoch has full rights over."
- **AI models database** (epoch.ai/data/ai-models): "over 3600 models" from 1950 to today with training-compute estimates, subsets "Notable", "Frontier", "Large-scale".

## Methodology
- Internal evals "are powered by Inspect, and are run with consistent and well documented settings across models"; chat/instruct variants only (not base models); API-default temperature; zero-shot CoT for GPQA Diamond / MATH L5 / Mock AIME; empty system prompt; OpenAI models via Chat Completions API.
- Repeats: "16 times on GPQA Diamond and Mock AIME 2024-2025, 8 times on MATH Level 5"; error bars = ±1 standard error.
- Auditability: Inspect task definitions published for GPQA Diamond, MATH L5, Mock AIME, FrontierMath, SWE-bench Verified; hosted Inspect log viewer per run (CAPTCHA-gated to prevent leakage); "In the future, we plan to pin each benchmark run to the exact git revision for full auditability." Log viewer not available for MATH L5 (copyright) and for FrontierMath only on the 10 public questions (frontiermath-2025-02-28-public).
- Stated caveats: contamination/leakage risk ("particularly ... MATH Level 5"); setting-sensitivity (example: Claude 3.5 Sonnet 2024-10-22 claimed 65% GPQA Diamond vs Epoch's 0.55 ± 0.03 over 16 runs); strict formatting can push models below the 25% random baseline (Yi-34B-Chat 15%, Mistral-7B-Instruct-v0.3 15%, open-mistral-7b 13%).
- Model selection: "prioritize leading model releases from the main AI labs", plus best open-weight, non-US, and compute-estimated models; only models Epoch can run itself (no internal-only models like PaLM/Gopher).
- Data license: CC-BY for Epoch's data; "Benchmark questions and answers are the property of their respective creators." Download as CSV/ZIP ("LLM benchmark data, ZIP, Updated Oct. 19, 2026") or via `pip install epochai` (Airtable API).

## Open-source tools/datasets
| Name | Link | What it is |
|---|---|---|
| ECI fitting code | https://github.com/epoch-research/eci-public (MIT) | Fits the sigmoid IRT-style model to Epoch's benchmark_data.zip; outputs ECI, EDI, discriminabilities |
| ECI data | https://epoch.ai/data/eci_scores.csv , /data/eci_benchmarks.csv , /data/cyber/processed_data_for_eci.csv | Scores and benchmark list |
| epochai Python client | https://github.com/epoch-research/epochai-python/ | Access hub data via Airtable API |
| Inspect task definitions | linked from https://epoch.ai/benchmarks/about (gists by tadamcz; built on https://github.com/UKGovernmentBEIS/inspect_evals) | GPQA Diamond, MATH L5, Mock AIME, FrontierMath, SWE-bench Verified tasks |
| FrontierMath Erdős | "open-source repository" referenced on https://epoch.ai/benchmarks/frontiermath-erdos (URL not captured) | Lean statements of 68 conjectures + evaluation scaffold |
| FrontierMath public sample | frontiermath-2025-02-28-public (10 questions, per hub FAQ) | Only public FrontierMath questions; rest private/OpenAI-owned |
| Chess Puzzles benchmark; Compute-to-tokens analysis | https://github.com/epoch-research (39 repos listed) | Snapshots/reproducible analyses |

## Pre-deployment / early access
| lab | model | source URL | what they found |
|---|---|---|---|
| OpenAI | FrontierMath (300 problems commissioned; o3 evaluated Dec 2024) | https://epoch.ai/blog/openai-and-frontiermath | "OpenAI commissioned Epoch AI to produce 300 math questions ... They own these and have access to the statements and solutions, except for a 50-question holdout set." Epoch "cannot share the questions and answers with other parties without written permission from OpenAI." "Per our agreement, we needed OpenAI's permission before publicly disclosing their involvement ... We received permission from OpenAI ahead of the o3 announcement." Pilot funded by Nat Friedman. Transparency page lists OpenAI engagements: "2026 FrontierMath Data Audit", "2026 FrontierMath: Open Problems Verifier", "2024/25 Developing the FrontierMath benchmark". |
| Google DeepMind | "AI co-mathematician" (2026); "Model Evaluations" (2025); joint report (2024/25); ECI paper funding | https://epoch.ai/about/transparency ; https://epoch.ai/data/eci-documentation | Commissioned evaluations; whether access was pre-release is not stated (UNVERIFIED). |
| xAI | "Model Evaluations" (2025) | https://epoch.ai/about/transparency | Listed as a paid collaboration; details not disclosed. |
| Anthropic | "Small pilot for new benchmark" (2024) | https://epoch.ai/about/transparency | Pilot only. |
| EU AI Office; UK DSIT; ARIA; METR; Blitzy; Bridgewater; Sequoia; AI Index; EPRI | various consultations/benchmarks (2024-2026) | https://epoch.ai/about/transparency | Consultations, joint reports, "Building a software engineering benchmark" with METR (2025). |
| Pre-release access to unreleased frontier models | — | — | **none documented** in fetched text (Epoch's hub FAQ says it reports only models it can run itself). |

## Why they are trusted / credibility signals
- Proactive transparency page listing all donations ≥ $70,000 (Coefficient Giving: $8.5M Apr 2025, $4.13M Apr 2024, $6.92M Apr 2023, $2.74M Mar 2026 for Public Data Center Tracker, $600k Jul 2026 compute, $70k Mar 2025 "FrontierMath Benchmark Improvements"; Survival & Flourishing Fund $195k May 2026; Jaan Tallinn $600k Jan 2025; Leopold Aschenbrenner "Pilot for New Benchmark" Jan 2025; Girish Sastry $100k Dec 2025) and all paid collaborations ≥ $30,000.
- Stated neutrality: "Epoch does not advocate for any particular stance on AI policy, and we do not engage in lobbying"; "As an organization, we are decidedly neutral" on whether AI progress is good.
- Published evaluation code, repeated runs with error bars, hosted per-run logs; CC-BY data.
- Post-controversy commitments: "we will ensure all contributors have access to information about industry funding and data access agreements before participating and proactively publicly disclose benchmark sponsorship and data access agreements."
- Counter-signals: FrontierMath Tiers 1-4 is OpenAI-owned and OpenAI-supported; ECI paper funded by Google DeepMind; co-founder Tamay Besiroglu left to co-lead Mechanize (a startup "building ... benchmarks, and training data for AI development"). TechCrunch (2025-01-19) reported criticism that Epoch waited to disclose OpenAI's funding (techcrunch-frontiermath-openai.txt).

## Notable findings (numbers)
- FrontierMath paper (arXiv 2411.04872, Nov 2024): "Current state-of-the-art AI models solve under 2% of problems."
- FrontierMath Tiers 1-4 v2 (2026-06-12) "addressed errors in 42% of problems" — a notable data-quality disclosure.
- FrontierMath Erdős: 68 conjectures; Bloom's estimate of solvability captured only partially (text truncated) — UNVERIFIED.
- Hub: Claude 3.5 Sonnet (2024-10-22) GPQA Diamond 0.55 ± 0.03 (Epoch, 16 runs) vs 65% claimed by Anthropic.
- ECI: >50 benchmarks combined; leaderboard values not extracted (JS-rendered) — UNVERIFIED.

## Sources (all fetched 2026-10-19)
- https://epoch.ai/frontiermath ; https://epoch.ai/frontiermath/tiers-1-4 ; https://epoch.ai/frontiermath/open-problems ; https://epoch.ai/benchmarks/frontiermath-erdos
- https://epoch.ai/blog/openai-and-frontiermath (Besiroglu & Sevilla, 2025)
- https://arxiv.org/abs/2411.04872 (FrontierMath paper)
- https://epoch.ai/benchmarks ; https://epoch.ai/benchmarks/about ; https://epoch.ai/benchmarks/use-this-data
- https://epoch.ai/eci ; https://epoch.ai/data/eci-documentation ; https://github.com/epoch-research/eci-public
- https://epoch.ai/data/ai-models
- https://epoch.ai/about ; https://epoch.ai/about/transparency
- https://github.com/epoch-research
- https://techcrunch.com/2025/01/19/ai-benchmarking-organization-criticized-for-waiting-to-disclose-funding-from-openai (secondary)

## Gaps / UNVERIFIED
- 404s: epoch.ai/frontiermath/benchmark-rules, epoch.ai/epoch-capabilities-index (moved to /eci), epoch.ai/blog/independent-evaluations-of-frontier-models, epoch.ai/data/ai-models/documentation.
- Current FrontierMath and ECI leaderboard numbers are JS-rendered and were not captured.
- Whether OpenAI's "verbal agreement" not to train on FrontierMath exists is reported only in secondary press (TechCrunch/The Decoder via search summary) — UNVERIFIED; Epoch's own post does not mention a training restriction.
- Status of the 50-problem holdout ("We are finalizing" as of Jan 2025) and results of the 2026 "FrontierMath Data Audit" commissioned by OpenAI not fetched.
