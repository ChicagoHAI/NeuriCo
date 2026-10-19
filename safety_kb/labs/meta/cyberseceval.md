# CyberSecEval (v1-v4), Meta Purple Llama

- URLs: repo https://github.com/meta-llama/PurpleLlama (CybersecurityBenchmarks/README.md fetched raw, sources/meta/cyberseceval-readme.md); docs https://meta-llama.github.io/PurpleLlama/CyberSecEval/ (landing page only); papers arXiv:2312.04724 (v1, Dec 7 2023), arXiv:2404.13161 (v2, Apr 18 2024), arXiv:2408.01605 (v3, Jul 23 2024) - all fetched as PDF+txt under sources/meta/. CyberSecEval 4 has no standalone paper; it is described in the README and the CyberSOCEval / AutoPatchBench publications it links.
- Fetched: 2026-10-19
- License: MIT (benchmarks).

## What each version added
- v1 (2023): "propensity to generate insecure code" (Instruct and Autocomplete tests, CWE-based, Insecure Code Detector) and "level of compliance when asked to assist in cyberattacks" (MITRE ATT&CK-based prompts). Case study on 7 Llama 2 / Code Llama / GPT models: "more advanced models [tend] to suggest insecure code".
- v2 (2024): prompt injection and code interpreter abuse tests; "all tested models showed between 26% and 41% successful prompt injection tests"; introduced the False Refusal Rate (FRR) - "the percentage of benign prompts that are refused by an LLM because they are mistaken for prompts that [are malicious]"; vulnerability exploitation (four CTF-style problem types).
- v3 (2024): "visual prompt injection tests, spear phishing capability tests, and autonomous offensive cyber operations tests"; applied to Llama 3. Findings: Llama 3 405B "did not provide a statistically significant uplift in cyberattack completion rates relative to baselines where participants had access to search engines" (human co-pilot study, CTF); "most effective at solving small-scale program vulnerability exploitation challenges, surpassing GPT-4 Turbo by 23%"; insecure autocomplete failure 31%; prompt injection failure 22% (405B) / 19% (8B); malicious-code-interpreter compliance 1%-26%.
- v4 (2025): adds CyberSOCEval (with CrowdStrike: Malware Analysis and Threat Intelligence Reasoning, multiple-choice with multiple correct options, precision/recall) and AutoPatchBench ("measures an LLM agent's capability to automatically patch security vulnerabilities in native code", fuzzer-found crashes). README: "It has been applied to well-known LLMs such as Meta's Llama4 as well as OpenAI, Google, and Anthropic models" - but no Llama 4 scores are published in the README/docs.

## Benchmark families in the current repo (README list)
1 MITRE compliance + MITRE FRR; 2 Secure code generation (Instruct, Autocomplete); 3 Prompt injection (textual, visual); 4 Code interpreter abuse; 5 Vulnerability exploitation (CTF-style); 6 Spear phishing capability (LLM-simulated victims, judged); 7 Autonomous offensive cyber operations; 8 AutoPatch; 9 CyberSOCEval.

## Metrics
Insecure-code rate (%), compliance rate with malicious requests (%), FRR (%), prompt-injection success rate (%), exploit success (%), spear-phishing persuasiveness scores, SOC multiple-choice precision/recall, patch success rate.

## Use by Meta in governance
- Frontier AI Framework v1.1 cites CyberSecEval as the evaluation used "once a model demonstrates a sufficient standard of coding ability".
- Framework v2.0 lists AutoPatchBench and CyberSOCEval as defender-uplift tools; the Muse Spark reports do not use CyberSecEval scores for thresholding (they use Cybench, CyberGym, Irregular challenges, CyScenarioBench instead); "Secure Code Generation" in the Muse Spark scorecard (65.7) is plausibly the CyberSecEval secure-coding test (UNVERIFIED).

## Limitations stated in the papers (CSE3 Figure 1)
Spear-phishing victims "are simulated with LLMs and may not behave like real people"; human study has "high variance ... only large effect sizes can be detected"; autonomous ops "Does not expand with more complex RAG, tool-augmentation, fine-tuning"; exploitation tests use "toy sized vulnerable programs"; injection and compliance tests "use individual prompts without jailbreaks or iterative attacks"; insecure-code tests focus on "obviously insecure coding practices, not subtle bugs".
