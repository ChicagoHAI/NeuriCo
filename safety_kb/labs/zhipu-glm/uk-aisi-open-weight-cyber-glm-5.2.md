# UK AI Security Institute: "How far behind the frontier are leading open-weight models on cyber?" (Jul 17, 2026) and joint UK AISI/CAISI Kimi K3 note (Jul 23, 2026)

- URLs: https://www.aisi.gov.uk/blog/how-far-behind-the-frontier-are-leading-open-weight-models-on-cyber ; https://www.aisi.gov.uk/blog/preliminary-assessment-of-kimi-k3s-cyber-capabilities
- Fetched: 2026-10-19 ; local: `safety_kb/sources/zhipu-glm/uk-aisi-open-weight-models-cyber-gap-2026.md`, `uk-aisi-caisi-kimi-k3-cyber-2026.md`
- Evaluator: UK AISI (independent government evaluator). Capability only; no safeguard testing of GLM.

## Verbatim findings on GLM-5.2
> "Our evaluations find that GLM-5.2 (June 2026) was the most cyber-capable open weight model at time of testing. It performs similarly to Opus 4.6 (Feb 2026) on AISI's narrow cyber tasks and Opus 4.5 (Nov 2025) on our longer-horizon cyber ranges, meaning it trails the frontier by 4 to 7 months. This is narrower than the 6 to 10 month gap we measured in internal evaluations of open weight models released from January to September 2025."
> Figure 1: "Average success rate on 70 of AISI's narrow cyber tasks, given 5 attempts per task with a 2.5M token limit per attempt. ... GLM-5.2 performs comparably to the most cyber-capable models released 4 months before it (Opus 4.6 and GPT-5.3-Codex), and this holds across all four difficulty levels."
> Figure 2 ("The Last Ones" cyber range, 100M-token limit, 10 runs): "On TLO, GLM-5.2 reaches as far as Opus 4.5, a model released less than 7 months before it".
> Cost: "A 100M-token cyber range run cost roughly $85 for both Opus 4.5 and 4.6, versus an estimated $46 for GLM-5.2 ... Across tasks that both models being compared solved with 100% reliability, Opus 4.6 cost $15.17 per task versus GLM-5.2's $6.12".
> "This implies cyber defenders have a short window to prepare before today's frontier cyber capabilities may become accessible without the same safeguards."

## Joint UK AISI / CAISI Kimi K3 note — GLM-5.2 comparators (verbatim)
> "Kimi K3 outperforms GLM-5.2, the most cyber-capable open-weight model as of June 2026. Kimi K3 achieves a score of 32%, whereas GLM-5.2 achieves a score of 24% (Figure 1) [ExploitBench, 41 V8 tasks]." "Within the 100M-token limit, Kimi K3 reaches step 17 on average, compared with step 11 for GLM-5.2 [The Last Ones range]."

No UK AISI evaluation of GLM-5.3 was found on aisi.gov.uk as of 2026-10-19 (UNVERIFIED whether one exists elsewhere).
