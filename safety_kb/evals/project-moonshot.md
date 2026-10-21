# Project Moonshot (AI Verify Foundation / IMDA)

- Slug: project-moonshot
- What it measures: LLM and LLM-app benchmarking (capability and trust & safety: bias, toxicity, hallucination, undesirable content, data disclosure, prompt-injection vulnerability, Singapore/ASEAN-context factuality) plus automated and manual red teaming via attack modules.
- Metric: Per-recipe metrics (accuracy, BLEU, toxicity-classifier score, LLM-as-judge, etc.) rolled into letter grades per recipe/cookbook (example grading scale A: 0-19 ... E: 80-100), HTML report + raw JSON.
- Open-source: y (https://github.com/aiverify-foundation/moonshot , Apache-2.0; assets https://github.com/aiverify-foundation/moonshot-data ; CI/CD runner https://github.com/aiverify-foundation/moonshot-cicd)
- Runnable on a 0.5B-7B open model: y (HuggingFace/Together/OpenAI-compatible connectors; `pip install "aiverify-moonshot[all]"`, Python 3.11; some metrics need an LLM judge endpoint)
- Source URL(s): https://github.com/aiverify-foundation/moonshot ; https://aiverify-foundation.github.io/moonshot/resources/datasets/ ; https://aiverify-foundation.github.io/moonshot/resources/attack_modules/ ; https://aiverifyfoundation.sg/project-moonshot/
- Fetched: 2026-10-19

## Description
README (v0.7.6): "Moonshot is a tool to bring Benchmarking and Red-Teaming together to help AI developers, compliance teams evaluate LLM-based Apps and LLMs," with "guided workflows to implement IMDA's Starter Kit for LLM-based App Testing." moonshot-data bundles connectors (OpenAI, Anthropic, Together, HuggingFace), datasets, metrics, prompt templates, recipes, cookbooks, attack modules and context strategies. Safety datasets in the catalogue include the MLCommons AILuminate v1.0 DEMO prompt set split by its 12 hazard categories (AIVF "partners with MLCommons"), CyberSecEval prompt-injection sets in EN/CN/FR/JP/KR/Swahili/Malay and CyberSecEval-3 interpreter, SafetyBench, RealToxicityPrompts, ChallengingToxicityPrompts, in-the-wild jailbreak prompts (verazuo), jailbreak-dan, WinoBias, Chinese BBQ and Singapore-context safety/factual sets. Attack modules include character-swap, homoglyph (v1/v2), insert-punctuation, colloquial word-swap (Singapore), job-role generator and malicious-question generator. moonshot-cicd v1.1.0 (GA) runs the four Starter Kit risk areas in Docker/CI with "Automated Red Teaming Agents" and a "Process Checks (GenAI)" app for the 11 AI Verify principles. Status: "currently in beta" (core repo).

## Used by
- Used by: AI Verify Foundation / IMDA (https://github.com/aiverify-foundation/moonshot ; Starter Kit v1.0 section 4.2)
- Used by: Global AI Assurance Sandbox participants (recommended tooling; https://aiverifyfoundation.sg/ai-assurance/sandbox/)
