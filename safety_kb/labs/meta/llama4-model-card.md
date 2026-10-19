# Llama 4 Model Card (Scout / Maverick)

- Title: Llama 4 Model Card (models/llama4/MODEL_CARD.md)
- URL: https://github.com/meta-llama/llama-models/blob/main/models/llama4/MODEL_CARD.md (fetched raw from https://raw.githubusercontent.com/meta-llama/llama-models/main/models/llama4/MODEL_CARD.md). The Hugging Face cards (https://huggingface.co/meta-llama/Llama-4-Scout-17B-16E-Instruct, .../Llama-4-Maverick-17B-128E-Instruct) are gated (raw README HTTP 401); HF API metadata fetched instead (sources/meta/hfapi-Llama-4-*.json). UNVERIFIED whether the HF card text differs from the GitHub card.
- Fetched: 2026-10-19
- Model Release Date: "April 5, 2025". Knowledge cutoff August 2024. Scout 17B active / 109B total, 16 experts, 10M context, ~40T tokens; Maverick 17B active / 400B total, 128 experts, 1M context, ~22T tokens. Llama 4 Behemoth: NOT in this card (no Behemoth card was found; Behemoth was described as "still in training" in the April 2025 blog - UNVERIFIED whether ever released).
- Newer Llama: no "Llama 4.1" or "Llama 5" model card could be located on github.com/meta-llama, huggingface.co/meta-llama or ai.meta.com as of 2026-10-19 (web search returned only third-party speculation). Meta's 2026 frontier model is the closed-weight Muse Spark (see muse-spark-*.md). Status of further Llama releases: UNVERIFIED.
- Raw text: /data/haokun_test/neurico/safety_kb/sources/meta/llama4-model-card.raw.md
- Blog companion: https://ai.meta.com/blog/llama-4-multimodal-intelligence/ (sources/meta/webfetch-llama4-blog.md)

## Safeguards section - what the card says
Three-pronged strategy: enable developers; "Protect developers against adversarial users"; "Provide protections for the community". "Llama 4 was developed following the best practices outlined in our Developer Use Guide: AI Protections."

Model-level fine-tuning: "combining human-generated data from our vendors with synthetic data"; LLM-based classifiers for data selection. Refusals: "we put a great emphasis on driving down model refusals to benign prompts"; "included both borderline and adversarial prompts"; tone work "targeted removing preachy and overly moralizing language". The recommended system prompt instructs: "do not refuse prompts about political and social issues" and "You never lecture people to be nicer or more inclusive."

System protections: "We provide the community with system level protections - like Llama Guard, Prompt Guard and Code Shield - that developers should deploy with Llama models or other LLMs."

Evaluations: "We built dedicated, adversarial evaluation datasets and evaluated systems composed of Llama models and Llama Guard 3 to filter input prompt and output response." Capability evaluations "for which were crafted dedicated benchmarks including long context, multilingual, coding or memorization." Red teaming: "recurring red teaming exercises"; red team "consists of experts in cybersecurity, adversarial machine learning, and integrity in addition to multilingual content specialists". "We partner early with subject-matter experts in critical risk areas".

Critical risks (verbatim):
1. CBRNE: "we applied expert-designed and other targeted evaluations designed to assess whether the use of Llama 4 could meaningfully increase the capabilities of malicious actors to plan or carry out attacks using these types of weapons. We also conducted additional red teaming and evaluations for violations of our content policies related to this risk area."
2. Child Safety: "a team of experts assesses the model's capability to produce outputs resulting in Child Safety risks ... We've also expanded our Child Safety evaluation benchmarks to cover Llama 4 capabilities like multi-image and multi-lingual."
3. Cyber attack enablement: "We conducted threat modeling exercises ... we focused on evaluating the capabilities of Llama 4 to automate cyberattacks, identify and exploit security vulnerabilities, and automate harmful workflows. Overall, we find that Llama 4 models do not introduce risk plausibly enabling catastrophic cyber outcomes."

Community: member of AI Alliance, Partnership on AI, MLCommons; "We encourage the community to adopt taxonomies like the MLCommons Proof of Concept evaluation"; output reporting mechanism and bug bounty program.

Limitations: "Testing conducted to date has not covered, nor could it cover, all scenarios."

## Numbers reported anywhere for Llama 4 safety
- Model card: NONE. The card contains no refusal rates, violation rates, CyberSecEval scores, jailbreak ASRs, CBRN uplift metrics, or child-safety metrics. "all reported evaluations and testing were conducted on bf16 models" (applies to capability benchmarks).
- Blog (April 5, 2025): "Llama 4 refuses less on debated political and social topics overall (from 7% in Llama 3.3 to below 2%)"; "the proportion of unequal response refusals is now less than 1%"; political lean "comparable to Grok (and at half of the rate of Llama 3.3)". Mentions GOAT (Generative Offensive Agent Testing) for automated multi-turn adversarial testing.
- The CyberSecEval 4 README states the suite "has been applied to well-known LLMs such as Meta's Llama4" but no Llama 4 scores are in the README or docs landing page.

## What was NOT run or disclosed
- No quantitative critical-risk results (no CBRN benchmark names or scores, no cyber CTF scores, no uplift study description) - contrast with the Llama 3 paper / CyberSecEval 3 (which published Llama 3 cyber results) and with the 2026 Muse Spark reports.
- No statement of which Frontier AI Framework risk threshold Llama 4 was assigned (the Feb 2025 framework was in force; the card does not cite it).
- No external / third-party evaluator named; no pre-deployment access for government institutes mentioned.
- No fine-tuning-attack / safety-training-removal evaluation for an open-weight release.
- No Llama Guard 4 or Prompt Guard 2 results in the card (they are in their own cards).
- Child safety: process only, no metrics.
