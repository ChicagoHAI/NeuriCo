# GLM-5: from Vibe Coding to Agentic Engineering (tech report, arXiv 2602.15763)

- URL: https://arxiv.org/abs/2602.15763 (PDF https://arxiv.org/pdf/2602.15763; v2 dated 24 Feb 2026)
- Document date: February 2026 (model released 2026-02-11)
- Fetched: 2026-10-19
- Local source: `safety_kb/sources/zhipu-glm/glm-5-tech-report.pdf` and `.txt` (40 pages)
- Authors: "GLM-5 Team, Zhipu AI & Tsinghua University"
- Models covered: GLM-5 (744B total / 40B active per Section 2.1 and Table in appendix: "# Total Parameters 355B [GLM-4.5] / 744B [GLM-5]; # Activated Parameters 32B / 40B"). HF: zai-org/GLM-5, zai-org/GLM-5-FP8 (MIT). The same report is cited by the GLM-5.1 / 5.2 / 5.3 model cards.

## Headline finding for this knowledge base
**The GLM-5 technical report contains no safety evaluation and no safety section.** A case-insensitive search of the full pdftotext output finds **zero** occurrences of "safe", "safety", "risk", "harm", "jailbreak", "red team", "toxic", or "refus". The only adjacent material is: (a) a General RL description that lists "knowledge hallucinations" among error types to minimise; (b) a discussion of reward hacking susceptibility of outcome reward models; (c) "Human-in-the-loop style alignment" (stylistic anchoring, not safety). Concordia AI's State of AI Safety in China (2026), Table 5.1, independently records GLM-5 (Feb 2026) as "No" safety discussion / "No" safety evaluation results (see `commitments-and-trackers.md`).

## Verbatim passages (the closest the report comes to safety/alignment)

### Abstract (p.1)
> "To advance model alignment and autonomy, we implement a new asynchronous reinforcement learning infrastructure that drastically improves post-training efficiency by decoupling generation from training."

### Section 3 Post-Training (p.11, txt lines 565-571)
> "our pipeline follows a progressive alignment strategy: starting with multi-task Supervised Fine-Tuning (SFT) that introduces sophisticated interleaved thinking modes, followed by specialized Reinforcement Learning (RL) stages for reasoning and agentic tasks, and concluding with a general RL stage for human-style alignment."

### Section 3.4 General RL (p.12-13, txt lines 730-768)
> "We decompose the optimization objectives of General RL into three complementary dimensions: foundational correctness, emotional intelligence, and task-specific quality. The foundational correctness dimension ... targets a broad spectrum of error types that undermine the usability of model outputs, including instruction-following failures, logical inconsistencies, factual inaccuracies, knowledge hallucinations, and language disfluencies."

> "Hybrid reward system. ... rule-based reward functions, outcome reward models (ORMs), and generative reward models (GRMs). ... ORMs offer low-variance signals and high training efficiency, but are more susceptible to reward hacking, where the policy exploits superficial patterns rather than genuinely improving core capability. GRMs leverage language models to produce scalar or structured evaluations and are more robust to such exploitation, but tend to exhibit higher variance."

> "Human-in-the-loop style alignment. A distinctive aspect of our General RL pipeline is the explicit incorporation of high-quality human-authored responses. ... By exposing the model to human-written exemplars, we encourage it to adopt more natural, human-aligned response patterns."

Note: "safety" is NOT listed among the General RL objectives, in contrast to the GLM-4.5 report where annotators scored "safety" as one preference dimension.

### Section 5 Adapting GLM-5 to Chinese Chip Infrastructure (p.22, txt lines 1251-1262) — context for the "trained on Ascend" question
> "we have successfully achieved full-stack adaptation for GLM-5 through close collaboration with seven mainstream Chinese chip platforms, including Huawei Ascend, Moore Threads, Hygon, Cambricon, Kunlunxin, MetaX, and Enflame. ... To fit the 750B parameter GLM-5 model onto a single Atlas 800T A3 machine, we implemented a sophisticated W4A8 mixed-precision quantization strategy."
This section describes **inference** adaptation. The report does not state that GLM-5 was pre-trained on Ascend; the "trained on Huawei Ascend" orientation claim is NOT supported by the report (UNVERIFIED / likely incorrect as stated; the z.ai GLM-5 blog text also only says "We also support deploying GLM-5 on non-NVIDIA chips, including Huawei Ascend, ...", see `sources/zhipu-glm/zai-blog-glm-5.md`).

### Section 8 "Easter Eggs" (p.30, txt lines 1794-1812) — anonymous release
> "It was a bold decision to release GLM-5 anonymously on OpenRouter [as "Pony Alpha"] ... By stripping away our brand name, we allowed the model's intrinsic capabilities to speak for themselves ... A preliminary statistic shows that 25% of the users guessed it was Claude Sonnet 5, 20% DeepSeek, 10% Grok, and the rest GLM-5."
Relevance: a pre-release public deployment with no stated safety gating.

## Evaluation section (Section 6) — safety coverage
Section 6 covers reasoning/general (HLE, AIME, GPQA, ...), coding (SWE-Bench Pro, Terminal-Bench, ...), agentic (τ²-Bench, MCP-Atlas, Tool-Decathlon, BrowseComp), real-world agentic engineering (CC-Bench-V2, long-horizon), machine translation, multilingual dialogue, instruction following, world knowledge, tool calling. **None of these is a safety evaluation.** The multilingual section (6.3.2) is helpfulness-only.

## Not reported
Everything in the safety taxonomy: safety benchmarks, red teaming, refusal, jailbreak, multilingual harm, agentic misuse, CBRN/cyber/bio, sycophancy, deception, bias, privacy, child safety, guard models, monitoring, safety framework.
