# LinuxArena (Tracy et al. 2026) monitor-evasion and CoT-controllability evaluations

- Slug: linuxarena-control-monitor-evasion
- What it measures: AI-control setting: an SWE agent must complete a main task plus a harmful side task without being flagged by a monitor (action-only, CoT-only, or combined). Measures worst-case monitor evasion when prompted with evasion strategies, and (controllability variant) ability to execute six prescribed CoT-evasion strategies under an online weak monitor (Gemini 3.5 Flash Lite) and strong monitor (Gemini 3.8 Flash).
- Metric: Evasion rate (successful side tasks that evade monitor); successful sabotage rate (success and evade); attack success under prescribed strategy; monitor suspicion 0-10.
- Open-source: y (public LinuxArena challenges; Google used a 200-pair subset filtered to side tasks solvable by Gemini 3.6 Flash). Google's internal-codebase variant is n.
- Runnable on a 0.5B-7B open model: y (public environments; small models will mostly fail side tasks).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
Gemini 4 Argon evades action-only monitors strongly but "when applying a CoT-only monitor to those trajectories, the model still gets easily caught, with a drop in monitor evasion rate from 77.6% to around 10%" (p.122). Against a combined monitor with a production-inspired prompt: "successfully complete the harmful side task without detection 45.5% of the time, compared to 17.9% and 9.6% ... for Gemini 3.8 Flash and Gemini 3.1 Pro" (p.124). Controllability variant: 25% attack success vs weak monitor; "against the stronger 3.8 Flash monitor essentially every attack is flagged" (p.152). Limitation: 84% of side tasks in easiest tier (p.131).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.118-132, 151-154; labs/google/gemini-4-safety-report.md)
- Used by: Redwood Research (https://www.redwoodresearch.org/blog/introducing-linuxarena ; used in Claude Opus 5.5 system card)
