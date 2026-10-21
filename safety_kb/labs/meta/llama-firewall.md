# LlamaFirewall (incl. Code Shield, AlignmentCheck)

- URLs: paper arXiv:2505.03574 "LlamaFirewall: An open source guardrail system for building secure AI agents" (6 May 2025; sources/meta/arxiv-2505.03574-llamafirewall.txt); repo https://github.com/meta-llama/PurpleLlama/tree/main/LlamaFirewall (README fetched raw: sources/meta/llamafirewall-readme.md).
- Fetched: 2026-10-19

## What it is
"an open-source security focused guardrail framework designed to serve as a final layer of defense against security risks associated with AI Agents." Three guardrails: PromptGuard 2 (jailbreak/injection detector); Agent Alignment Checks ("a chain-of-thought auditor that inspects agent reasoning for prompt injection and goal misalignment, which, while still experimental ..."); CodeShield ("an online static analysis engine", Semgrep + regex rules, 8 languages). Plus customizable regex/LLM-prompt scanners.

## Reported metrics
- AgentDojo (offline, public leaderboard traces): baseline ASR 17.63%, utility 47.73%; PromptGuard 2 86M alone ASR 7.53% (utility 47.01%); AlignmentCheck with Llama 4 Maverick ASR 2.89% (utility 43.09%); combined ASR 1.75% ("a >90% reduction from the baseline") with utility 42.68%.
- AlignmentCheck: "Without fine-tuning, these models achieved over 80% recall with a false positive rate below 4%" on indirect goal-hijacking scenarios.
- CodeShield: "precision of 96% and a recall of 79% in identifying insecure code" on a manually-labeled dataset; "approximately 90% of inputs are fully resolved by the first layer ... latency of under 70 milliseconds" (internal production deployment).

## Use in governance
Framework v2.0 (Section 4.2.1): "we deploy LlamaFirewall as a system-level mitigation to help detect and prevent risks such as prompt injection via input classifiers and chain-of-thought auditing."

## Not disclosed / limitations
AlignmentCheck is "experimental", has "significantly higher latency"; AgentDojo "focuses primarily on a narrow class" of injections; no evaluation against adaptive attackers in the paper; manually-labeled CodeShield dataset size not given in the extracted text (UNVERIFIED).
