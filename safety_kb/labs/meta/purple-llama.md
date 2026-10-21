# Purple Llama (umbrella project)

- URL: https://github.com/meta-llama/PurpleLlama (README fetched raw: sources/meta/purplellama-readme.md); blog https://ai.meta.com/blog/purple-llama-open-trust-safety-generative-ai (not fetched).
- Fetched: 2026-10-19

"Purple Llama is an umbrella project that over time will bring together tools and evals to help the community build responsibly with open generative AI models." Name from purple teaming ("both attack (red team) and defensive (blue team) postures").

Components and licenses (README table): CyberSecEval (MIT); Llama Guard (Llama 2 Community License), Llama Guard 2 (Llama 3), Llama Guard 3-8B / 3-1B / 3-11B-vision and Prompt Guard (Llama 3.2 Community License); Code Shield (MIT). The README table has not been updated to list Llama Guard 4 / Prompt Guard 2 / LlamaFirewall, although these live in the same repo (LlamaFirewall/README.md fetched).

System-level safeguards described: Llama Guard 3 ("optimized to support the detection of the MLCommons standard hazards taxonomy ... also optimized to detect helpful cyberattack responses and prevent malicious code output"), Prompt Guard (prompt injection vs jailbreak definitions), Code Shield ("inference-time filtering of insecure code").

Evals described: CyberSec Eval v1 ("what we believe was the first industry-wide set of cybersecurity safety evaluations for LLMs", tied to the July 2023 White House voluntary commitments), v2 (code interpreter abuse, offensive capabilities, prompt injection; HF leaderboard https://huggingface.co/spaces/facebook/CyberSecEval), v3 (visual prompt injection, spear phishing, autonomous offensive ops). v4 is only described in the CybersecurityBenchmarks README (see cyberseceval.md).

Scope limits: Purple Llama covers cyber and content moderation only; no CBRN, autonomy, or alignment evaluation tooling is published under it.
