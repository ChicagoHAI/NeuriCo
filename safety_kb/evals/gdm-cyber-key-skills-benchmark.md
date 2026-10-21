# GDM cyber "key skills" benchmark (v1 and v2)

- Slug: gdm-cyber-key-skills-benchmark
- What it measures: offensive-cyber capability as a proxy for cost reduction in high-impact attacks. v1: 50 CTF-style challenges (12 "hard") on reconnaissance, tool development, tool usage, operational security. v2: 13 "end-to-end" multi-stage cyber ranges covering all seven kill chains of Rodriguez et al. 2025.
- Metric: challenge solved if at least one of N attempts (N=10-200; 75 for Gemini 3 Pro) captures the flag; fraction solved by difficulty tier; mapped to Threat Actor Capability (TAC-1..4) tiers and an uplift cost model (22 historical attacks x 26 operational steps, expert-elicited human costs).
- Open-source: n (challenges "developed with a third party"; not released). Framework paper public: arXiv 2503.11917.
- Runnable on a 0.5B-7B open model: n for the exact suite (private); public proxies: Cybench, `gdm_in_house_ctf`, `gdm_intercode_ctf` in Inspect Evals.
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_3_pro_fsf_report.pdf (pp.8-10, App.1); https://storage.googleapis.com/deepmind-media/gemini/gemini_3-7_flash_fsf_report.pdf (pp.15-18); https://deepmind.google/blog/evaluating-potential-cybersecurity-threats-of-advanced-ai/
- Fetched: 2026-10-19

## Description
"These challenges comprise our 'key skills' benchmark ... The first is composed of 50 challenges we developed with a third party ... of which 12 are at the 'hard' level ... we worked with the same third party to develop a new set of harder, more realistic challenges. These challenges simulate full end-to-end attacks" (Gemini 3 Pro FSF Report p.9). Gemini 3 Pro: 11/12 hard v1 solved (alert threshold), 0/13 v2. For Gemini 3.7 Flash the benchmark was not run ("ongoing security improvements"); proxies were used. With safeguards on, "The model refuses on 100% of the milestones" (3.7 Flash report p.30).

## Used by
- Used by: Google (frontier safety) — Cyber Uplift Level 1 CCL early warning evaluation (labs/google/frontier-safety-framework.md)
- See also: evals/gdm-cyber-end-to-end-attack-scenarios.md (Gemini 4 Argon: 12/12 end-to-end scenarios); evals/cybench.md, evals/gdm-in-house-ctf.md as public proxies.
