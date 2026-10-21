# Microsoft automated RAI measurement framework (Azure AI Evaluation SDK adversarial simulation)

- Slug: microsoft-rai-adversarial-simulation
- What it measures: an LLM (GPT-4o) simulates adversarial users in single/multi-turn conversations; a second LLM judges severity (0-7) per harm category (violence, sexual, self-harm, hate/unfairness; also grounding, 3P content/IP leakage, jailbreak success). Also used with known jailbreak prefixes.
- Metric: Defect Rate DR-x = % of responses with severity >= x (Phi-4 uses DR1/DR3; Phi-4-mini reports fraction harmful).
- Open-source: partially (Azure AI Evaluation SDK / Azure AI Foundry "Risk and Safety Evaluation" is a product; framework paper Magooda et al. 2023 arXiv 2310.17750 cited as [37]/[MHJ+23])
- Runnable on a 0.5B-7B open model: y via the SDK against any endpoint (requires Azure); in-house prompt sets not released
- Source URL(s): https://arxiv.org/pdf/2412.08905 ; https://arxiv.org/pdf/2503.01743 ; https://arxiv.org/pdf/2504.21318
- Fetched: 2026-10-19

## Description
Phi-4 report §7.1: "This benchmark utilized GPT-4o to simulate multi-turn conversations in five different categories and to evaluate the model responses ... defect rates (DR-x) were computed as the percentage of samples with the severity score being greater than or equal to x." Phi-4 Table 10: 3P content harms DR1 0.121; harmful continuation DR3 0.036; harmful summarization DR3 0.102; jailbreak DR1 0.073. Phi-4-mini Table 10/11: average defect rate 3.75% (1.25% with jailbreaks). Phi-4-reasoning: "minor regression compared to the base model Phi-4" (no numbers).

## Used by
- Used by: Microsoft (Phi-3 through Phi-4-mini-flash-reasoning; https://arxiv.org/pdf/2412.08905 ; https://arxiv.org/pdf/2503.01743)
