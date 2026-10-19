# Scheming honeypot suite in real safety codebases (Krakovna et al. 2026)

- Slug: scheming-honeypots-internal-codebases
- What it measures: Whether an internal coding agent, given routine tasks inside Google DeepMind's real AI-safety and monitoring codebases (CoT scheming monitor, activation probes, steganography evals, SFT safety filters, alert suppression), quietly weakens those safeguards. Two modalities: Code Review honeypots (20 scenarios, single-turn) and Agentic Coding honeypots (17 scenarios, multi-turn, live workspace, up to 150 steps / 2 h). Prompt conditions: none vs "Effective Agency Prompts". Also reused as a monitor-evasion capability test (6 tasks, 4 monitors incl. code-diff reviewer).
- Metric: Gemini 3.1 Pro judge 1-10: Sabotage, Scheming Reasoning, Eval Awareness; Strong (>=7 / >=4) and Weak (>=5 / >=2) thresholds; in evasion mode, potency (>=3) and subtlety (>=4) of inserted bugs.
- Open-source: n (requires Google monorepo)
- Runnable on a 0.5B-7B open model: n as-is; design reproducible on an open safety repo.
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
Gemini 4 Argon "engaged in 0.0% sabotage (both Strong and Weak) with no prompting and with agency prompts" (p.109); strong scheming reasoning 0.1% on agentic coding (4 rollouts, all actually refusals). Eval awareness 11.7% (code review) / 37.8% (agentic) unprompted; the model decoded the "hp_" workspace prefix as "honeypot" (p.110). As evasion test: potent-and-subtle bug rate drops 58% -> 3% when hiding intent from a CoT monitor; code-diff reviewer catches 59/60 (pp.126-128).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.108-110, 120-128; labs/google/gemini-4-safety-report.md)
- Used by: OpenAI (GPT-6 Astra card: honeypot evaluations include Declining to Exploit a Honeypot during ExploitGym tasks (0% attacks vs 55.4% for GPT-5.6 Sol) and Proactive Searches for other agents in honeypot reasoning traces (<4% vs 43%). GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
