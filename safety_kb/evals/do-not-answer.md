# Do-Not-Answer

Fetched: 2026-10-19

- What it measures: 939 instructions that responsible LLMs should refuse, across a three-level risk taxonomy (information hazards, malicious uses, discrimination/toxicity, misinformation, human-chatbot interaction harms).
- Metric: % harmful responses / action-category distribution (GPT-4 or fine-tuned classifier judge).
- Open-source: yes (Apache-2.0)
- Link: https://github.com/Libr-AI/do-not-answer ; paper https://arxiv.org/abs/2308.13387
- Runnable on a 0.5B-7B open model: yes

Used by: DeepSeek (DeepSeek-R1 Nature paper safety appendix; see labs/deepseek/README.md)
