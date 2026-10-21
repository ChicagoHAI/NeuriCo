# Chinese governance context for the open-model labs (Alibaba/Qwen, Moonshot/Kimi, Zhipu/GLM, DeepSeek)

Fetched: 2026-10-19

Purpose: one place for the voluntary commitments, state frameworks and the Concordia AI
disclosure survey that the four lab READMEs cite. Everything below is from the fetched files in
`sources/china-governance/`.

## 1. Voluntary industry commitments

### AIIA / CAICT "Artificial Intelligence Safety Commitments" (2024-12-01)
Source: AGORA/ETO record of the WeChat announcement, https://agora.eto.tech/instrument/1831
(`sources/china-governance/aiia-ai-safety-commitments-dec-2024-agora-eto.md`), official text at
https://mp.weixin.qq.com/s/s-XFKQCWhu0uye4opgb3Ng (not fetched; WeChat).
First 17 signatories (AGORA list): Alibaba (China) Co., Ltd.; Baidu; Volcano Engine (ByteDance);
Megvii; Zero One Everything (01.AI); Beijing DeepQuest AI Basic Technology Research Co. (= DeepSeek's
registered entity, per Carnegie, Singer 2025-01-28, which says "DeepSeek ... joined sixteen other
Chinese companies"); Beijing Zhipu Huazhang Technology Co., Ltd. (Zhipu / Z.ai); 4Paradigm; Huawei;
iFlytek; Ant Group; 360; SenseTime; Shanghai Xiyu Technology (= MiniMax); Tencent; China Telecom AI;
China Mobile. **Moonshot AI is NOT on the AGORA list of the first 17**; Concordia AI's State of AI Safety in
China (2025) confirms Moonshot had not signed the Dec-2024 version (see
`labs/moonshot-kimi/concordia-state-of-ai-safety-china-moonshot-and-cac-filing.md`); it is not
among the five companies added at WAIC 2025 either (Honor, Sangfor, Vivo, Qi An-Xin, ZTE), so
as of 2026-10-19 Moonshot appears to be a non-signatory (UNVERIFIED beyond these two sources).
Six commitments (AGORA summary): (1) AI safety lead + risk-assessment teams + lifecycle risk
management; (2) pre-release safety testing "using simulation and red-teaming"; (3) data security;
(4) infrastructure security, penetration tests, incident response; (5) model transparency:
"Disclose safety and security governance measures, and clearly communicate model capabilities,
applicable fields, limitations, and risks through documentation or service agreements"; (6)
frontier safety research (agents, embodied AI, bias) with public sharing of findings.
Carnegie (Singer, 2025-01-28): wording "sometimes identical" to the Seoul Frontier AI Safety
Commitments, but the Seoul commitments "center on redlines for frontier risks and the steps
companies would take if those thresholds were crossed", which the Chinese text lacks; "only one
Chinese company, Zhipu.ai, signed" Seoul.

### WAIC 2025 re-issue under CnAISDA ("China AI Security and Safety Commitments Framework", 2025-07)
Source: Concordia AI WAIC recap, 2025-08-04
(`sources/china-governance/concordia-waic-2025-recap-substack.md`). Commitments 1-5 unchanged;
commitment 6 broadened to "preventing safety and security risks in frontier fields" (drops the
explicit agents/embodied-AI references, does not define frontier risks); new commitment 7 on
"actively participating in global dialogues on AI safety, security, and governance". Five companies
added: Honor, Sangfor, Vivo, Qi An-Xin, ZTE. AI Frontiers (Elmgren/Singer/Guest, 2025-10-14): "some
key stakeholders, notably including DeepSeek, were conspicuously absent from the second round of
commitments"; the same piece states that none of the Seoul-commitment signatories in China has
published the promised framework ("none of the Chinese companies that signed them have fulfilled
them"). Implementation disclosures: CAICT/AIIA site lists "43 common practices"; Concordia calls
them "generic".

### Seoul Frontier AI Safety Commitments (2024-05)
Zhipu AI is the only one of the four labs that signed. Concordia 2026 (sec. 5.2, p.72): "although
Z.AI prominently cites its signing of the Seoul Frontier AI Safety Commitments in its IPO documents,
it has not followed through on the requirement to publish a frontier AI safety policy." No
frontier-safety / responsible-scaling policy was found for Alibaba, Moonshot or DeepSeek either
(searched 2026-10-19; see lab READMEs).

## 2. State frameworks and standards (TC260 / CAC)

### AI Safety Governance Framework 2.0 (TC260 technical document, released 2025-09-15)
Source: CAC announcement https://www.cac.gov.cn/2025-09/15/c_1759653448369123.htm; bilingual PDF
https://www.cac.gov.cn/rootimages/uploadimg/1759653474200838/1759653474200838.pdf (31 MB, kept out of
git; text in `sources/china-governance/tc260-ai-safety-governance-framework-2.0-2025-09-15.txt`).
Drafted by CNCERT under CAC guidance; v1.0 was 2024-09. Relevant English clauses (page numbers as
printed):
- Risk "(c) Loss of control over knowledge and capabilities of nuclear, biological, chemical, and
  missile weapons" (p.45): training corpora include "fundamental theoretical knowledge related to
  nuclear, biological, chemical, and missile weapons ... extremist groups and terrorists may be able
  to acquire relevant knowledge".
- 5.8 "Establishing an AI safety assessment system ... evaluations for model and algorithm safety,
  general application safety, and scenario-specific safety ... accuracy of generated content,
  resilience to interference, transparency of its decision-making logic, and its defense against
  adversarial attacks ... organize crowdsourced safety testing" (p.58).
- 5.11: "Developers will be required to conduct regular testing to determine whether a model would
  pose a potential risk of loss of control" (p.~61). This is the clearest state-level
  frontier-risk testing expectation; it does not specify evaluations or thresholds.
- "AI systems applied in critical information infrastructure will be subject to registration and
  filing" (p.~57).
- 6.1.9 "Regularly conduct safety assessment tests and establish a risk classification, grading, and
  optimization mechanism"; 6.1.11 "Use technologies like sandbox simulations ... Developers creating
  products for commercial use should generate detailed test reports"; 6.1.13 "Regularly disclose
  information on the auditing and anomaly handling of AI models and algorithms".
None of the four labs' public model cards cite this framework (checked by the lab agents; see
READMEs). It is a technical document (guidance), not a binding standard.

### Other instruments (not fetched in full; context only)
- Interim Measures for the Management of Generative AI Services (CAC, effective 2023-08-15) and the
  algorithm/large-model filing ("备案") regime: pre-deployment safety assessment is mandatory for
  public-facing generative services in China. Concordia 2026 ("What's missing"): the report cannot
  capture "private pre-deployment evaluations conducted via China's mandatory algorithm registry".
  Effect for this KB: the labs' domestic deployments are tested, but the results are not public, so
  open-weight users get nothing from it.
- GB/T 45654-2025 "Generative AI service security requirements" (TC260): UNVERIFIED content here;
  the SESEC Sep-2025 TC260 report (`sources/china-governance/sesec-tc260-ai-standardization-sep-2025.pdf`)
  summarises TC260's AI standard pipeline.
- CAICT/AIIA "AI Safety Benchmark 2.0" (2026-02): per Concordia 2026 (sec. 5.1.1) adds
  "self-awareness, model deception, dangerous domain misuse, loss of control" and agentic risks;
  results are anonymised and voluntary; "CAICT has not yet provided detailed descriptions of how they
  define or operationalize evaluations". CAICT published "security assessments of 15 open source
  coding models" (2025-11) - model names not given in Concordia's summary (UNVERIFIED which).

## 3. Concordia AI, State of AI Safety in China (2026) - what it says about these four labs
Source: PDF via AI Governance Library,
https://www.aigl.blog/content/files/2026/08/State-of-AI-Safety-in-China--2026-.pdf
(`sources/china-governance/concordia-state-of-ai-safety-in-china-2026.pdf`, text extracted). Covers
July 2025 - June 2026. Key passages (sec. 5.2.1, pp.72-75, Table 5.1 "Overview of safety disclosure in
model cards of ten major Chinese foundation developers", June 2025 - May 2026):
- "Of the ten companies, only five (Bytedance, DeepSeek, Meituan, Moonshot AI, and Z.AI) provided
  safety evaluation results alongside any model release during the year in question, and even those
  five did not do so consistently across releases." (Last year's survey: 3 of 13.)
- Alibaba: Qwen3-Max (Sep 2025) - dedicated safety section: No; safety evaluations: No. Qwen3.5
  (Feb 2026) - No / No. "this investment in a dedicated guardrail product [Qwen3Guard] did not
  translate into detailed safety reporting in Qwen's own foundation model releases" (p.77).
- DeepSeek: DeepSeek-R1 (Nature, Sep 2025) - "10-page 'Safety Report' in the Appendix, including full
  disclosure of the 'The Risk Review Prompt for DeepSeek-R1'"; evals: "Simple Safety Tests; Bias
  Benchmark for QA; Anthropic Red Team; XSTest; Do-Not-Answer; HarmBench; an in-house benchmark
  covering 'discrimination and prejudice, illegal and criminal behavior, harmful behavior, and moral
  and ethical issues.'" DeepSeek-V3.2 (Dec 2025) - "No. Briefly mentions 'human alignment training'
  during the RL stage." DeepSeek-V4 (Apr 2026) - "No. The only safety-adjacent mention is operational
  sandbox isolation/security for running agentic tasks."
- Moonshot AI: Kimi K2 (Jul 2025) - "No [dedicated section]. Briefly describes seed prompts aimed at
  reducing 'violence, fraud, and discrimination,' with an automated prompt evolution pipeline to
  simulate jailbreaking attempts." Evals: "Safety evaluation performed with Promptfoo, covering:
  harmful, criminal, misinformation, privacy, security (each with multiple sub-categories)." Kimi K2.5
  (Feb 2026) - No / No. Kimi K2.6 (Apr 2026) - "No. Briefly mentions that the model has 'enhanced
  safety awareness during extended research tasks.'" / No.
- Z.AI/Zhipu: GLM-4.5 (Aug 2025) - "Very briefly discusses safety as one dimension in RL." Evals:
  "SafetyBench (includes ethics and morality, illegal activities, mental health, offensiveness,
  physical health, privacy and property, and unfairness and bias)." GLM-5 (Feb 2026) - No / No.
- "flagship follow-ups like DeepSeek-V4 and Kimi K2.5 included no safety evaluation results at all."
- Research output (sec. 5.2.2): Alibaba 29 safety papers Jan 2025 - Apr 2026 (largest industry
  contributor), Z.AI 2 ("long-context safety evaluation and multimodal jailbreaks"); "DeepSeek,
  MoonShot, and MiniMax have no safety papers in our dataset since January 2025 at all."
- Public statements (sec. 5.2): Qwen tech lead Lin Junyang (Jan 2026) - worry has moved from a model
  that "says something it shouldn't" to one that "does something it shouldn't"; Alibaba security
  executive Xue Hui argued evaluations "should include novel risks like self-replication and loss of
  control"; Z.AI IPO prospectus: AI could cause "grave harm, even catastrophe".

## 4. Shanghai AI Lab frontier-risk evaluations
See `third_party/shanghai-ai-lab-safework.md` (covers Qwen2.5/Qwen3/QwQ, DeepSeek V3/R1, Kimi
K2-0905, GLM-4.7, Qwen3-235B/Max with numbers on CBRN knowledge, MASK honesty, sandbagging,
self-replication, persuasion, cyber, agent misevolution).
