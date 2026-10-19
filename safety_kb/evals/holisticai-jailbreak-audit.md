# Holistic AI Red Teaming & Jailbreaking Audit

- Slug: holisticai-jailbreak-audit
- What it measures: Resistance of a newly released LLM to known jailbreak prompts (DAN/STAN/DUDE-style) and its refusal of harmful requests without over-refusing matched benign requests.
- Metric: Counts/percentages of SAFE vs UNSAFE responses over 237 prompts (37 jailbreak + 100 harmful + 100 benign), with "Jailbreaking Resistance" = safe/37; classification by an LLM judge then "Human Expert Review". The Grok 4 variant used 3 x 100 prompts, manually scored.
- Open-source: n (prompts proprietary; harmful/benign items drawn from AdvBench, TDC/HarmBench and arXiv:2404.01318; open-source `holisticai` library is for tabular-ML bias/robustness, not this audit)
- Runnable on a 0.5B-7B open model: y in principle (public DAN-style jailbreaks + AdvBench/HarmBench/JailbreakBench items can be re-assembled; Holistic AI's exact 37 prompts are not published) — a faithful replication is not possible.
- Source URL(s): https://www.holisticai.com/red-teaming ; https://www.holisticai.com/red-teaming/deepseek-r1 ; https://www.holisticai.com/red-teaming/claude-3-7-sonnet-jailbreaking-audit ; https://www.holisticai.com/red-teaming/grok-3 ; https://www.holisticai.com/red-teaming/chatgpt-4-5-jailbreaking-red-teaming ; https://www.holisticai.com/blog/proactive-ai-governance-grok-4-launch
- Fetched: 2026-10-19

## Description
"37 Jailbreaking Prompts: These prompts were designed to test how well the models could resist bypass attempts, such as the widely known 'Do Anything Now' (DAN) exploits. 100 Harmful Prompts: ... sourced from AdvBench, TDC/HarmBench, and original test cases ... 100 Benign Prompts: ... mirror the harmful prompts in topic but not in intent" (DeepSeek R1 audit, 2025-02-05). Results 2025: o1 37/37 jailbreak-safe, 232/237 overall; DeepSeek R1 12/37 (32%), 210/237 (89%); Grok-3 1/37 (2.7%); Claude 3.7 Sonnet (thinking, 16k) 37/37, 237/237; GPT-4.5 36/37 (97.3%), 236/237 (99.6%); Grok 4 (July 2025, API, 100 prompts/set) 90% of jailbreaks unsafe, 11% unsafe on standard and 15% on harmful red-team prompts. Small samples; single snapshot per model.

## Used by
- Used by: Holistic AI (https://www.holisticai.com/red-teaming)
