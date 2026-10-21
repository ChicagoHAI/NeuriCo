# External analysis of xAI's frameworks

- Fetched: 2026-10-19

## AI Lab Watch — "xAI's new safety framework is dreadful" (Zach Stein-Perlman, 2025-09-08)
- URL: https://ailabwatch.substack.com/p/xais-new-safety-framework-is-dreadful (raw: `safety_kb/sources/xai/ailabwatch-xai-framework-dreadful.txt`)
- Key points (summarised from fetched page; short quotes): calls the MASK <50% criterion "very silly" and argues MASK does not measure catastrophic misalignment; "upfront behavioral benchmarking is just not the right approach to misalignment risk"; the bio answer-rate <1/20 criterion is "on the right track but not effective" because jailbreaks undermine it (cites Grok 4 complying with a sarin-synthesis request shortly after release); the security claim ("motivated non-state actor") is "not credible"; missing: whether "deployment" includes internal use, red-teaming of mitigations, a misuse-detection plan, future security plans; verdict "Overall the RMF is profoundly unserious".
- AI Lab Watch scorecard (https://ailabwatch.org/companies/xai, "Up to date as of September 2025", site no longer maintained): xAI overall 4% (Anthropic 28, DeepMind 20, OpenAI 18, Meta 5, Microsoft 3, DeepSeek 1); risk assessment 6% (evals domains/quality/elicitation 10%, evals accountability 0%, adversarial evaluation for alignment 0%, model organisms 0%).

## SaferAI — "Evaluating AI Providers' Frontier Safety Frameworks" (Stelling et al., arXiv 2512.01166 v5, 30 Apr 2026)
- URL: https://arxiv.org/pdf/2512.01166 (raw: `safety_kb/sources/other-frameworks/arxiv-2512.01166-evaluating-frontier-safety-frameworks.txt`)
- 12 frameworks, 65 weighted criteria, four dimensions. Overall: Anthropic 34% ... Cohere 8%, median 18%. xAI: overall 16%; risk identification 22%; risk analysis & evaluation 21%; **risk treatment 5%** (lowest); governance 16%. Positive notes: "Only Meta (41%) and xAI (31%) publish concrete threat scenarios"; "xAI provides detailed causal pathways for specific risks (e.g. bioweapon design using AI)"; "xAI (50%) defines a quantitative threshold for misuse: 'more than one hundred deaths or ...'". Negative: "xAI's draft Framework included specific capability thresholds, but the final version removed them"; "xAI's commitment is heavily hedged: they 'may temporarily fully shut down the ...'".
- The paper assessed the Aug/Dec 2025 text; the June 2026 FAIF removed the remaining numeric criteria, benchmark list and transparency items, so these scores would likely fall further (my inference, UNVERIFIED).

## Not fetched / UNVERIFIED
TechCrunch (May 2025) on the missed RMF deadline and the Midas Project's commentary were surfaced by search but not fetched. Reports about Grok's July 2025 antisemitic outputs on X and about internal pressure to loosen safeguards (Feb 2026 commentary) are UNVERIFIED here.
