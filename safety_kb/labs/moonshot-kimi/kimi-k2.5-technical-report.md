# Kimi K2.5: Visual Agentic Intelligence — Technical Report (arXiv 2602.02276)

URL: https://arxiv.org/abs/2602.02276 (PDF https://arxiv.org/pdf/2602.02276; also https://github.com/MoonshotAI/Kimi-K2.5/blob/main/tech_report.pdf)
Document date: v1 Feb 2026; v2 dated 7 Aug 2026 (arXiv stamp). 31 pages.
Fetched: 2026-10-19
Local source: /data/haokun_test/neurico/safety_kb/sources/moonshot-kimi/kimi-k2.5-tech-report-arxiv-2602.02276.pdf (+ .txt)
Model: Kimi-K2.5 (1T total / 32B activated, native multimodal, Agent Swarm). HF: moonshotai/Kimi-K2.5 (release note in card "2026.1.29"; repo created 2026-01-01).

## Safety content: NONE
A full-text grep of the 1,918-line pdftotext output for "safety", "safe", "jailbreak", "harmful", "red team", "red-team", "refusal", "misuse", "CBRN", "bio", "responsible" returns zero safety passages. The only hits for "risk"/"align" are architectural ("vision-text alignment", "modality alignment") and reward-model wording. The independent evaluators Yong et al. (arXiv 2604.03121, §1) state: "unlike comparable closed-source models that publish detailed safety evaluations alongside their releases, Kimi K2.5's technical report contains no assessment of safety-related risks." Concordia AI (State of AI Safety in China 2026, Table 5.1) lists Kimi K2.5: dedicated safety section "No"; safety evaluations "No".

## Safety-adjacent passages (verbatim)

Reward design (Section 3.x "Reward Function", txt lines ~444–470):
> "For general-purpose tasks, we employ Generative Reward Models (GRMs) that provide granular evaluations aligned with Kimi's internal value criteria."

> "Generative Reward Models Kimi K2 leverages a self-critique rubric reward for open-ended generation [53], and K2.5 extends this line of work by systematically deploying Generative Reward Models (GRMs) across a broad range of agentic behaviors and multimodal trajectories. ... Notably, GRMs function not as binary adjudicators, but as fine-grained evaluators aligned with Kimi's values that are critical to user experiences, such as helpfulness, response readiness, contextual relevance, appropriate level of detail, aesthetic quality of generated artifacts, and strict instruction following. ... To mitigate reward hacking and overfitting to a single preference signal, we employ multiple alternative GRM rubrics tailored to different task contexts."

Pre-training data (txt ~1231):
> "Caption data [49, 19] provides fundamental modality alignment, with strict limits on synthetic captions to mitigate hallucination."

Cyber capability benchmark used as a capability metric (not a safety eval): CyberGym is cited ([66] "CyberGym: Evaluating AI Agents' Cybersecurity Capabilities with Real-World Vulnerabilities") and the HF card reports a CyberGym score (Yong et al. note "CyberGym Level 1 result (17.3%) sourced from Kimi K2.5 model card" for DeepSeek-V3.2; the K2.5 card's own CyberGym number should be read from the card table).

Agent Swarm: described as "a self-directed parallel agent orchestration framework that dynamically decomposes complex tasks into heterogeneous sub-problems and executes them concurrently" (abstract). No discussion of multi-agent safety, oversight, or sandboxing of swarm actions.

## Disclaimers / limitations
No limitations section with safety content was found (grep "limitation" returns nothing in this report).

## Kimi K2.5 blog (https://www.kimi.ai/blog/kimi-k2-5; local kimi-blog-k2.5.md)
No passages on safety, security, risk or responsible use; only benchmark notes (e.g. "Benchmarks without publicly available scores were re-evaluated under the same conditions used for Kimi K2.5 and are marked with an asterisk (*)").
