# Other Moonshot technical reports checked for safety content

Fetched: 2026-10-19. All PDFs under /data/haokun_test/neurico/safety_kb/sources/moonshot-kimi/ with pdftotext .txt alongside.

| Report | URL | Date | Local file | Safety content |
|---|---|---|---|---|
| Kimi-VL Technical Report | https://arxiv.org/abs/2504.07491 | Apr 2025 (v updated Jun 2025) | kimi-vl-tech-report-arxiv-2504.07491.pdf/.txt (24 pp) | None. Only "we strictly limit the proportion of synthetic caption data to mitigate the risk of hallucination" (§ data) and "strictly limit the proportion of the synthetic dense video description data to reduce the risk of hallucinations"; OSWorld-G "full set with refusal samples" is a benchmark subset name. Concordia 2025 Table 5.1 characterised it as "Very brief mention of the need for alignment with human values; safety evaluations: None mentioned." (The phrase actually found in the text: "a robust OCR capability is deemed essential for better aligning the model with human...".) |
| Kimi Linear: An Expressive, Efficient Attention Architecture | https://arxiv.org/abs/2510.26692 | Nov 2025 | kimi-linear-arxiv-2510.26692.pdf/.txt (11 pp) | None (0 hits for safety/harmful/jailbreak). GitHub tech_report.pdf is an LFS pointer (not downloadable raw). |
| Kimi-Audio Technical Report | https://raw.githubusercontent.com/MoonshotAI/Kimi-Audio/master/assets/kimia_report.pdf | Apr 2025 | kimi-audio-tech-report-github.pdf/.txt (26 pp) | None. Single "harmful" hit is about noise data "harmful to audio understanding". No content-safety filtering of audio generation described. |
| Moonlight / Muon is Scalable for LLM Training | https://arxiv.org/abs/2502.16982 | Feb 2025 | moonlight-muon-arxiv-2502.16982.pdf/.txt (19 pp) | None. |
| Kimi k1.5: Scaling Reinforcement Learning with LLMs | https://arxiv.org/abs/2501.12599 | Jan 2025 | kimi-k1.5-arxiv-2501.12599.pdf/.txt | Only reward-hacking mentions: "...mitigates the risk of reward hacking and overfitting to superficial patterns" and "To avoid potential reward hacking (Everitt et al. 2021; Pan et al. 2022), we need to ensure that both the reasoning..." (Concordia 2025 Table 5.1: "Very brief safety mention: mitigates reward-hacking in RL"; safety evaluations "None mentioned"). |
| Kimi-Dev-72B | https://github.com/MoonshotAI/Kimi-Dev | Jun 2025 | Kimi-Dev-72B.hf-card.md | Card says "Tech Report (Coming soon...)"; no report found; no safety text. |
| Kimi K2 Thinking | https://www.kimi.ai/blog/kimi-k2-thinking (no paper) | Nov 2025 | kimi-blog-k2-thinking.md, Kimi-K2-Thinking.hf-card.md | None. |
| Kimi K2.6 | https://www.kimi.ai/blog/kimi-k2-6 (no paper; card says test prompts identical to K2.5 report) | Apr 2026 | kimi-blog-k2.6.md, Kimi-K2.6.hf-card.md | One sentence: "enhanced safety awareness during extended research tasks" — no metric. |
| Kimi K2.7 Code | HF card only | Jun 2026 | Kimi-K2.7-Code.hf-card.md | None. |
