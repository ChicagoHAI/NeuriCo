# BioTIER (SecureBio biosecurity refusal evaluation)

- Slug: biotier
- What it measures: whether a deployed system refuses or gives safe responses to requests for information "that could support development of biological weapons", including under an adversarial attack portfolio.
- Metric: refusal-or-safe-response rate (%), with and without adversarial attacks
- Open-source: n (available "upon request at ai@securebio.org")
- Runnable on a 0.5B-7B open model: n (request-gated; refusal grading needs the SecureBio labels)
- Source URL(s): https://ai.meta.com/static-resource/Meta_Advanced-AI-Scaling-Framework-v2 (Sec. 4.2.2) ; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/ (Sec. 2.1.3) ; https://ai.meta.com/static-resource/muse-spark-1-1-evaluation-report
- Fetched: 2026-10-19

## Description
Meta framework v2.0: "on the BioTIER refusal evaluation, which includes information that could support development of biological weapons, our risk acceptance criteria includes at least 80% refusal or safe responses, and 40% refusal or safe responses against all adversarial attacks within a typical adversarial attack portfolio." Muse Spark (deployed system) 98.0 vs GPT-5.4 75.4, Claude Opus 4.6 95.4, Gemini 3.1 Pro 59.2; Muse Spark 1.1 97.7.

## Used by
- Used by: Meta (framework v2.0 threshold; Muse Spark reports; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/)


Used by: Anthropic (SecureBio on Opus 4.6/4.7, Sonnet 4.6 (review of Anthropic Risk Report); also used by other labs). Fetched 2026-10-19; see labs/anthropic/system-cards.md.
- Used by: OpenAI (bio capability reference alongside OpenAI's four Biological & Chemical High-threshold evals; OpenAI designated GPT-6 Astra High capability in Biological & Chemical. GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
