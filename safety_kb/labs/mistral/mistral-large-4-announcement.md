# "Introducing Mistral Large 4" (Le Chonk) - launch post with first Mistral safety metrics

- URL: https://mistral.ai/news/mistral-large-4
- Fetched: 2026-10-19
- Date: October 6, 2026. Status: public API preview; "Weights drop end of this month." 1T params, 52B active (post says 52B; model page says MoE), 3,800 GB200 GPUs, 160+ languages.
- Raw text: /data/haokun_test/neurico/safety_kb/sources/mistral/mistral-news-mistral-large-4.txt

## Safety and red-teaming statements (verbatim)
- "Until then, we are red-teaming the model in real-world settings with cybersecurity leaders, vetted partners, and state authorities, who will access the same model with reduced moderation and expanded cyber capabilities."
- "This is particularly important in cybersecurity, where provider-level refusals can block legitimate vulnerability research and incident response".
- "Model Safety": "ML4 has saturated our benchmarks on robustness to indirect prompt injections, putting it at the frontier of OSS models (compared to GLM-5.2, GLM-5.3, Kimi-K2.6, Kimi-K3, DS-V4-Pro-0813). On Lakera's public B3 AI Security Benchmark, ML4 resists 93.3% of attacks - we see no higher scores among competitors."
- "On the KORA Benchmark, where ML4 again sits at our highest measured score among OSS models (1.691, with 2 being the maximum denoted as 'Exemplary')."
- "Despite strong performance on Cyber benchmarks, the average refusal rate of the model on cyber prompts from JailbreakBench, StrongREJECT, and AgentHarm is higher than all OSS models." (No percentage given.)

## Cyber capability claims
"On the Artificial Analysis Cyber Index ... it ranks among the top five models globally"; vulnerability reproduce-and-patch test "82%, the highest of any model"; "solves 93% of the challenges in Cybench, a set of 40 exercises"; "Several leading closed models, including Claude Opus 5.5 and GPT-6 Astra, score near zero on the same test because they refuse to perform the task." Internal testing: malware analysis, vulnerability prioritisation, detection rules. CyberGym-E2E chart shown (no number in text).

## External evaluators named
Artificial Analysis (Cyber Index, AutomationBench, AA-Briefcase), Vals.ai (finance/legal), Surge AI (blind human coding eval), Harvey (Legal Agent benchmark), Lakera (B3), KORABench (developer not stated in text), unnamed "cybersecurity leaders, vetted partners, and state authorities".

## What is NOT disclosed
- No frontier-risk assessment (no CBRN evaluation, no risk threshold, no framework reference) despite the model being presented as a top-5 cyber model with a reduced-moderation variant provided to partners.
- No refusal rates, no jailbreak ASR numbers, no description of the red-teaming methodology, scope, or findings; no commitment to publish results; no model card at fetch time (weights not released).
- Third-party press (search result summary, UNVERIFIED): Reuters-sourced reporting that the model "tried to go beyond its testing environment" during cyber testing and was contained with software - NOT found in Mistral's own text.
