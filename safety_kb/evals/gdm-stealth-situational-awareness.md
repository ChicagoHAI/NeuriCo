# GDM Stealth and Situational Awareness evaluations

- Slug: gdm-stealth-situational-awareness
- What it measures: scheming-prerequisite capabilities: "stealth" (circumventing oversight: 4 tasks — Cover Your Tracks, Strategic Rule Breaking, Classifier Evasion, Oversight Pattern; a 5th, Decision Sabotage, is in the paper but not released) and "situational awareness" (11 Linux-agent tasks with hidden constraints such as max_tokens, max_tool_calls, faulty_tool, read_logs, approved_directories, irreversibility, context_size, output_filters, requiring the agent to notice and self-modify/adapt).
- Metric: success rate / normalised score over 50 attempts per challenge; stealth compared with human baselines (pass = exceed top-50% humans); SA pass = success rate > 20%. Google's TCL is reached only if all challenges in both sets are passed.
- Open-source: y — Inspect Evals `gdm_stealth` and `gdm_self_reasoning` (https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/gdm_stealth; .../gdm_self_reasoning); paper arXiv 2505.01420 Appendix F.
- Runnable on a 0.5B-7B open model: y (Docker sandboxes; up to 32 GB RAM for some tasks; small models will mostly fail, which is itself informative).
- Source URL(s): https://arxiv.org/abs/2505.01420 ; https://storage.googleapis.com/deepmind-media/gemini/gemini_3-7_flash_fsf_report.pdf (pp.38-40); https://storage.googleapis.com/deepmind-media/gemini/gemini_3_pro_fsf_report.pdf (pp.15-17)
- Fetched: 2026-10-19

## Description
"We use a set of 15 automated challenges to measure scheming-relevant reasoning capabilities, with four measuring its abilities to reason about and circumvent oversight (stealth), and eleven measuring its ability to instrumentally reason about itself, its environment, and its deployment (situational awareness). These challenges were intentionally designed to be abstract and less realistic to ensure that failure strongly implies safety" (Gemini 3.7 Flash FSF Report p.38). Results: Gemini 3 Pro 1/4 stealth, 3/11 SA; Gemini 3.7 Flash 3/4 stealth, 6/11 SA; Gemini 4 Argon 14/15 (see labs/google/gemini-4-safety-report-notes.md). Known confound: refusals of the covert side task invalidated "Cover Your Tracks" for 3.7 Flash.

## Used by
- Used by: Google (frontier safety) — Stealth and Situational Awareness TCL under FSF v3.1 (labs/google/frontier-safety-framework.md)
- See also: evals/gdm-stealth-situational-awareness-challenges.md (Gemini 4 Argon results, other agent).
- Used by: UK AISI Inspect Evals gdm_stealth / gdm_self_reasoning (https://github.com/UKGovernmentBEIS/inspect_evals)
