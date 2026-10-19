# CCP-Narrative-Bench (CAISI + U.S. State Department)

Fetched: 2026-10-19

- What it measures: 190 free-response questions on Chinese history, politics and foreign relations (English and Chinese) with per-topic narrative flags; measures how often a model's answer is consistent with CCP narratives / censorship.
- Metric: CCP alignment score (% of narrative flags matched; LLM-as-judge), mean +/- SE, per language.
- Open-source: no (private)
- Link: https://www.nist.gov/document/caisi-evaluation-deepseek-ai-models-report (Sec. 3.4, 7)
- Runnable on a 0.5B-7B open model: no (private); Promptfoo's public CCP-sensitive-topics dataset is the open analogue

Used by: Third party: NIST CAISI on DeepSeek R1 / R1-0528 / V3.1 ('echoed 4 times as many inaccurate and misleading CCP narratives'; 'CCP censorship is built directly into DeepSeek models') and Kimi K2 Thinking (Chinese censorship similar to R1-0528; relatively uncensored in English, Spanish, Arabic)
