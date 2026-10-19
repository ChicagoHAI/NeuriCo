# xAI internal safety suites (refusal set, jailbreak battery, HackerBench, Autointent-Bio/Chem, Biosecurity VCT, BioUseBench, SecureCodeReview, soft/epistemic bias, contrastive sycophancy, self-harm, child-safety)

- Slug: xai-internal-safety-suites
- What it measures: (a) multilingual refusal of policy-violating requests (EN/ES/ZH/JA/AR/RU, "thousands" of prompts, LLM-graded; metric answer/compliance rate) with user- and system-message jailbreak variants; (b) "continuously updated" jailbreak battery incl. long-horizon/Crescendo (compliance rate); (c) HackerBench — CTF-style cyber tasks plus should-refuse harmful/dual-use and benign items (harmful compliance rate, benign refusal rate); (d) Autointent-Bio/Chem — dangerous vs benign CBRN queries (refusal recall/accuracy); (e) Biosecurity VCT and BioUseBench (severity-5 dual-use refusal rate); (f) restricted bio/chem input-filter set built with SecureBio (false-negative rate, incl. prompt-injection variants); (g) soft/epistemic political bias on paired contrastive questions (LLM-judged 0/0.5/1); (h) contrastive sycophancy from production seed conversations; (i) self-harm suite (fail if assists or refuses without redirect); (j) child-safety multi-turn suite; (k) SecureCodeReview (fix security issues without introducing new ones).
- Metric: see above; all internal, unpublished prompts.
- Open-source: n
- Runnable on a 0.5B-7B open model: n (private)
- Source URL(s): https://data.x.ai/2025-08-20-grok-4-model-card.pdf ; https://data.x.ai/2025-11-17-grok-4-1-model-card.pdf ; https://media.x.ai/v1/website/card-4p6-4cd2dc57.pdf ; https://media.x.ai/v1/website/card4p7-3a96f40b.pdf
- Fetched: 2026-10-19

## Description
Grok 4 card: "we constructed a broad set of harmful queries demonstrating clear intent to engage in a range of criminal offenses ... translated them across several common languages ... totaling thousands of queries. We used another model to grade whether the model responses correctly refuse". Grok 4.5 card: "HackerBench is a SpaceXAI internal CTF-style suite of cybersecurity and red-teaming tasks that require chaining skills ... Included within HackerBench is a subset of harmful-intent, borderline, and dual-use requests that should be refused, as well as benign tasks." Grok 4.1 card: input-filter FNR 0.03 (bio) / 0.00 (chem), 0.20 / 0.12 under prompt injection.

## Used by
- Used by: xAI (all Grok cards 2025-2026; e.g., Grok 4.7 general refusals 1.10%, child safety 0.0%, Bio recall 100%, Chem 99.9%, HackerBench v0.3 compliance 4.02%, self-harm 1.05%; https://media.x.ai/v1/website/card4p7-3a96f40b.pdf)
