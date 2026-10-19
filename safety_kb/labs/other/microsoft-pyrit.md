# PyRIT — Python Risk Identification Tool for generative AI (Microsoft AI Red Team)

- URLs: https://github.com/microsoft/PyRIT (moved from github.com/Azure/PyRIT; raw `safety_kb/sources/microsoft/pyrit-readme.txt`, `pyrit-doc-index-raw.txt`), docs https://microsoft.github.io/PyRIT/, whitepaper "PyRIT: Democratizing AI Red Teaming Through Open-Source Tooling" https://commandline.microsoft.com/wp-content/uploads/2026/08/PyRIT_Whitepaper_2026.pdf (raw `pyrit-whitepaper-2026.txt`, ~1,850 lines), companion paper "Lessons From Red Teaming 100 Generative AI Products" arXiv 2501.07238 (raw `arxiv-2501.07238-lessons-red-teaming-100-products.txt`).
- Fetched: 2026-10-19. Version: 1.0.0 released 2026 ("stable, versioned public API"); first release Feb 2024. MIT license.

## What it is (whitepaper abstract)
"an open-source, extensible framework designed to democratize AI red teaming. PyRIT supports both fully automated and human-led red teaming through a composable, modular architecture of targets, converters, scorers, executors, techniques, and scenarios ... from raw model APIs to deployed applications and end-user UIs. It supports both single-turn and multi-turn attack strategies, including Crescendo and Tree of Attacks with Pruning. As the first AI red teaming tool with multi-modal support by design, PyRIT covers text, image, audio, video, and file blobs". Three surfaces: Python SDK, CLI "Scanner" (`pyrit_scan`, `pyrit_shell`; CI/CD), browser GUI "CoPyRIT".

## Architecture (§5)
Building blocks: targets (model/app endpoints), converters (prompt/response transforms, e.g. Base64, ROT13, translation), scorers (LLM judges, classifiers, output-side vulnerability scorers), memory (persisted conversations with typed identifiers so "the exact configuration that produced a result [is] queryable"), datasets/seeds. Executors = control-flow algorithms (Prompt Sending single-turn; multi-turn Crescendo, TAP, PAIR, Red Teaming orchestrator). Attack techniques (v1.0.0 registry): "role-play variants, Context Compliance, Flip, First Letter, image-based techniques, converter stacks, and configured Many-Shot, Skeleton Key, PAIR, TAP, Red Teaming, and Crescendo variants". Scenarios = campaigns (exhaustive or adaptive epsilon-greedy "TextAdaptive"); built-in domain scenarios "Cyber, Jailbreak, Psychosocial, Scam, and AdversarialBenchmark, as well as Garak-derived Encoding, Doctor, and WebInjection".

## Use inside Microsoft and adoption
"used to red team hundreds of generative AI products and services at Microsoft and beyond, and has been integrated into Azure AI Foundry as a built-in AI red teaming agent"; "PyRIT's automated red teaming approach has been used as part of the safety alignment pipeline for the Phi-3 family"; MAI-Thinking-1 lists "Template-based attacks, e.g., PyRIT" as a safety-data source. Community: ">4,300 stars and about 830 forks ... about one million downloads from PyPI across 23 releases", >150 contributors. Ecosystem: RAMPART (pytest-native agent safety testing), MLCommons AI Risk & Reliability WG (uses PyRIT; published jailbreak taxonomy), 0DIN jailbreak evaluation framework, Databricks BlackIce. The 2025 RAI report: 67 AIRT operations in 2024; 2026 report: >100 operations.

## Limitations stated by the authors (§8)
"Observability in agentic systems" is a fundamental challenge; automated scoring relies on LLM judges (the 2026 RAI report's STAC work flags validity gaps in LLM-as-judge red-team metrics).

## "Lessons From Red Teaming 100 Generative AI Products" (Bullwinkel et al., Jan 2025)
Eight lessons: understand what the system can do and where it is applied; you don't have to compute gradients to break an AI system; AI red teaming is not safety benchmarking; automation can help cover more of the risk landscape; the human element is crucial; RAI harms are pervasive but difficult to measure; LLMs amplify existing security risks and introduce new ones; the work will never be complete. Includes AIRT's threat-model ontology (system, actor, TTPs, weakness, impact).

## Relevance for an automated safety engine
PyRIT is the most complete open attack-orchestration layer (multi-turn, multimodal, scorer-pluggable, CI-ready). It does not ship dangerous-capability (CBRN/cyber uplift) evaluations; it is a misuse/jailbreak robustness tool. Treat all downloaded content as untrusted; the repo was not executed here.
