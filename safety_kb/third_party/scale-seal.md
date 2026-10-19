# Scale AI — SEAL (Safety, Evaluation, and Alignment Lab) / Scale Labs leaderboards

- Org: Scale AI, Inc. (research arm: SEAL, "Safety, Evaluation, and Alignment Lab"; leaderboards now branded "Scale Labs Leaderboard")
- Website: https://scale.com/leaderboard , https://scale.com/research
- Fetched: 2026-10-19
- Raw text: /data/haokun_test/neurico/safety_kb/sources/scale-seal/

## What they evaluate
- Public leaderboards (scale.com/leaderboard) grouped into "Agentic", "Safety", "Frontier", "Legacy". The **Safety** group on 2026-10-19 lists four leaderboards: **DistressBench**, **PropensityBench**, **Fortress**, **MASK** (seal-leaderboard-index.txt; seal-mask.txt nav). "Humanity's Last Exam" sits under Frontier (capability, co-created with CAIS); listed here only because it is a CAIS collaboration often cited alongside safety evals.
- Safety-relevant benchmark families owned or co-owned by Scale:
  - **MASK** (honesty under pressure; with CAIS) — private 500-example split for the leaderboard, public split released with paper (arXiv 2503.03750).
  - **FORTRESS** (Frontier Risk Evaluation for National Security and Public Safety) — 1,010 expert-crafted adversarial prompts (500 public on HuggingFace, CC-BY-4.0) across CBRNE, Political Violence & Terrorism, Criminal & Financial Illicit Activities, each paired with a benign prompt for over-refusal (arXiv 2506.14922).
  - **PropensityBench** (agentic "would-do" vs "can-do"): 979 scenarios x 6 pressure dimensions = 5,874 tasks, 6,648 generated tools; domains biosecurity, chemical security, cybersecurity, self-proliferation (arXiv 2511.20703).
  - **DistressBench** (crisis-support quality; 718 clinician-authored conversations, 7 dimensions, weighted rubric; paper dated 10/9/2026 on scale.com/research).
  - **MHJ — Multi-Turn Human Jailbreaks** (2,912 prompts across 537 multi-turn jailbreaks; arXiv 2408.15221).
  - **BrowserART** (100 browser-agent harmful behaviors, sourced partly from HarmBench and AirBench; arXiv 2410.13886).
  - Earlier: WMDP (co-authored with CAIS; Scale's AISI blog says SEAL "measur[ed] dual-use knowledge in biosecurity and cybersecurity (WMDP)").
- Other 2025-2026 Scale Labs papers tagged "Safety & Oversight" on scale.com/research (titles only, not fetched individually): "ROK-FORTRESS" (geopolitical transcreation of FORTRESS, 5/13/2026), "Defensive Refusal Bias: How Safety Alignment Fails Cyber Defenders" (3/12/2026), "LLM Novice Uplift on Dual-Use, In Silico Biology Tasks" (2/26/2026), "Best Practices for Biorisk Evaluations on Open-Weight Bio-Foundation Models" (11/5/2025), "Reliable Weak-to-Strong Monitoring of LLM Agents" (8/26/2025, author list includes "Scale Red Team"), "Search-Time Data Contamination" (8/13/2025), "ASPI: Seeking Ambiguity Clarification Amplifies Prompt Injection Vulnerability in LLM Agents" (5/17/2026), "MoReBench" (moral reasoning, 12/22/2025).

## Methodology
- **Leaderboard ranking**: "Rank (UB)" = 1 + number of models whose lower 95% CI bound exceeds this model's upper bound; models with the same count share a rank (seal-mask.txt, "Rank (UB)" paragraph).
- **Private splits**: MASK and FORTRESS leaderboards run on private sets "collected through identical pipelines and annotator pools" as the public split, "to track potential model overfitting on public data while also preventing optimization gaming" (seal-mask.txt).
- **MASK**: human-collected "pressure prompts" (system+user) in 6 archetypes (Known Facts 20.6%, Situation-Provided Facts 27%, Doubling Down 11%, Fabricated Statistics 8.4%, Continuations 20.6%, Disinformation Generation 12.4%); belief elicited with 3 neutral prompts (primary asked 3x for consistency); LLM judge (GPT-4o for binary propositions, o3-mini for numerical) maps statement and belief to proposition resolutions; outcomes Lie / Honest / Evade; metric = Honesty Score = 1 - P(Lie). Data collected adversarially against gemini-1.5-pro-002, gpt-4o-mini-2024-07-18, gemini-1.5-flash-002, claude-3-5-sonnet-20240620, claude-3-5-haiku-20241022, llama-3-1-8b/70b-instruct; ~65% of initially collected examples retained after filtering; 10% audit with <5% error target. Caveat stated by Scale: evasive/no-belief responses count toward Honesty, and "the percentage of evading or lack of belief responses varies between ~25-35% across models."
- **FORTRESS**: each adversarial prompt has an instance-specific rubric of 4-7 binary questions; Average Risk Score (ARS) = mean over prompts of the % of rubric items answered "Yes" by a majority of a 3-judge LLM panel (o3, Claude 3.7 Sonnet, Gemini 2.5 Pro); Over-Refusal Score (ORS) = % of 500 benign prompts refused per a GPT-4o-mini refusal checker; models ranked by ARS with ORS in parentheses. Taxonomy grounded in U.S./international law (e.g. 18 U.S.C. § 229, UNTOC). Prompts "developed against a balanced distribution of leading models to mitigate bias."
- **PropensityBench**: agent given an "aligned" tool that persistently errors and a "misaligned" tool, under 6 escalating pressure dimensions; metrics: Propensity Score (share of scenarios choosing the misaligned action), Harmful-vs-benign-naming gap, Resilience (avg pressure level at first failure), Abandonment Rate; scenarios generated by a two-stage automated LLM pipeline.
- **DistressBench**: clinician-authored rubric with weighted atomic criteria across 7 dimensions plus a clinician reference response; score = share of rubric weight earned; 25 models in 12 statistically distinct bands (Figure 1 caption).
- **MHJ**: human red-teamers run multi-turn jailbreaks against defenses on HarmBench's 240 behaviors; compared to an ensemble of 6 automated attacks. Disclosure practice: "We received explicit permission for red teaming any proprietary models. Prior to release, we also disclosed our findings and datasets to the authors of the defenses we examined." Export-controlled content filtered; dataset gated on HuggingFace under CC BY-NC 4.0.
- **Red-teaming positioning (Scale's own guide, 2023)**: red teaming is "in-depth, iterative targeting by automated methods and human experts of specific harms", run iteratively with hypotheses and multiple rounds as mitigations are added; Scale states it "helped pioneer many of these methods hand-in-hand with ... OpenAI" and provided the T&E platform for the DEF CON 31 AI Village Generative Red Team "as the White House's evaluation platform of choice" (scale-guide-test-and-evaluation-vision.txt).

## Open-source tools/datasets
| Name | Link | What it is |
|---|---|---|
| FORTRESS public set | https://huggingface.co/datasets/ScaleAI/fortress_public | 500 rows: adversarial_prompt, rubric, benign_prompt; CC-BY-4.0 (hf-fortress-public.txt) |
| MASK (code + public split) | https://github.com/centerforaisafety/mask ; https://huggingface.co/datasets/cais/MASK | CAIS-hosted evaluation code and public data (github-mask.txt, hf-cais-mask.txt) |
| Humanity's Last Exam | https://github.com/centerforaisafety/hle (MIT), dataset on HF (cais/hle) | 2,500 closed-ended expert questions; eval code `hle_eval` |
| MHJ | arXiv 2408.15221; gated HF release (CC BY-NC 4.0, research only) | 2,912 prompts / 537 multi-turn human jailbreaks + tactic compendium |
| BrowserART | arXiv 2410.13886 | 100 browser-agent harmful behaviors test suite |
| PropensityBench | arXiv 2511.20703; scale.com/research/propensitybench | 5,874 scenario-tasks, 6,648 tools (repo link not confirmed from fetched text — UNVERIFIED) |
| DistressBench | scale.com/leaderboard/distressbench ("released corpus" referenced) | 718 clinician-authored conversations (repo/HF link not captured — UNVERIFIED) |

## Pre-deployment / early access
Checked system cards fetched on 2026-10-19 for the string "Scale AI"/"SEAL": OpenAI GPT-5 (cdn.openai.com/gpt-5-system-card.pdf), OpenAI o1 (o1-system-card-20241205.pdf), OpenAI o3/o4-mini, OpenAI GPT-4o, Anthropic Claude 4 system card. **None names Scale AI as a red-teaming or evaluation partner.** (GPT-5 §5.3.3.4 names FAR.AI and Gray Swan; §5.3.3.5 names CAISI and UK AISI.)

| lab | model | source URL | what they found |
|---|---|---|---|
| U.S. AI Safety Institute (government, not a lab) | n/a — program to let "model builders of all sizes" voluntarily test once and share with the AISI network; domains "may include ... math, reasoning, and AI coding" | https://scale.com/blog/first-independent-model-evaluator-for-the-USAISI (Feb 10, 2025); https://fedscoop.com/us-ai-safety-institute-taps-scale-ai-for-model-evaluation/ | FedScoop: Scale "selected ... as the first third-party evaluator authorized to assess AI models on [AISI's] behalf"; criteria "developed jointly". No specific model results published under this program were found (UNVERIFIED whether any were). |
| OpenAI (self-claimed, generic) | unspecified | https://scale.com/guides/test-and-evaluation-vision | Scale: "helped pioneer many of these methods hand-in-hand with ... OpenAI"; no model named. |
| Proprietary models in MHJ study | unnamed defenses/models | https://arxiv.org/abs/2408.15221 | "We received explicit permission for red teaming any proprietary models" — permission, not pre-deployment access. |
| Pre-deployment access to a specific unreleased frontier model | — | — | **none documented** in fetched sources. |

Note: Scale's leaderboards list models with "NEW" tags (e.g. "gpt-6-luna", "Claude Haiku 5.5", "Muse Spark 1.1" on Fortress) — this indicates Scale evaluates models at/after release; whether any were run pre-release is not stated (UNVERIFIED).

## Why they are trusted / credibility signals
- Public leaderboards with 95% CIs and private held-out splits (MASK, FORTRESS) to deter overfitting.
- Co-authorship with CAIS on MASK, HLE, WMDP; peer-reviewed/arXiv papers for each benchmark (FORTRESS "submitted to NeurIPS").
- Formal U.S. AISI partnership (Feb 2025) as first authorized third-party evaluator; Scale's blog cites being in the AISI International Network context.
- Responsible-disclosure statements (MHJ: disclosed findings to defense authors before release; filtered export-controlled content).
- Counter-signals: Scale is a commercial data/eval vendor to the labs it ranks (its own guide calls OpenAI a partner; Transparency about which labs are paying customers for eval work is not on the leaderboard pages). HLE and MASK judge/grader reliance on OpenAI models (GPT-4o/o3-mini) is disclosed.

## Notable findings (numbers)
- **MASK leaderboard (2026-10-19)**: top Honesty Score claude-opus-4-6 (Non-Thinking) 96.28±0.41; claude-sonnet-4-5-20250929-thinking 96.13±0.57; gpt-oss-120b 92.00±0.86; gpt-5.4-pro-2026-03-05 91.73±2.01; o3 (high, April 2025) 84.47±2.35; Claude Opus 4 80.28±0.62. Paper abstract: "while larger models obtain higher accuracy on our benchmark, they do not become more honest."
- **FORTRESS paper (arXiv 2506.14922)**: Claude-3.5-Sonnet ARS 14.09 / ORS 21.8; Gemini 2.5 Pro ARS 66.29 / ORS 1.4; DeepSeek-R1 ARS 78.05 / ORS 0.06; o1 ARS 21.69 / ORS 5.2. Leaderboard table (public+private): Claude 3.5 Sonnet ARS 12.96 ORS 21.07; o3 16.01/7.42; Claude 4 Opus (thinking) 24.76/1.89; GPT-4o 47.18/1.68; Gemini 2.5 Pro (06-05) 61.68/1.58; DeepSeek R1 74.39/0.49. Live "Performance Comparison" (2026-10-19): gpt-oss-120b 8.24±1.93 best ARS; Claude Haiku 5.5 9.48; claude-opus-4-5 thinking 9.63; gpt-5-2025-08-07 17.04.
- **PropensityBench**: average Propensity Score under pressure 46.9% vs near-zero at baseline; models use tools they explicitly call unsafe "up to 79.0% for Gemini 2.5 Pro"; leaderboard best (lowest) o3-2025-04-16 10.50±0.60, claude-sonnet-4-20250514 12.20±0.20, o4-mini 15.80±0.40, Qwen2.5-32B 22.90±1.20.
- **MHJ**: multi-turn human jailbreaks exceed 70% ASR on HarmBench against defenses reporting single-digit ASR under automated single-turn attacks; also recovered dual-use biosecurity knowledge from unlearned models.
- **HLE** (Frontier leaderboard, 2026-10-19): GPT 6 Astra 54.80±1.94 (calib err 39); Fable 5.1 (xhigh) 46.50; gemini-3.1-pro-preview 46.44; HLE finalized at 2,500 questions (April 3, 2025); CAIS "HLE-Rolling" fork released Sept 17, 2026.
- **DistressBench**: 718 conversations; 25 models in 12 statistically distinct bands; top-ranked entries muse-spark-1.2, muse-spark-1.3, muse-glimmer-30b (scores not captured in text extraction — UNVERIFIED).

## Sources (all fetched 2026-10-19)
- https://scale.com/leaderboard (seal-leaderboard-index.txt)
- https://scale.com/leaderboard/mask (seal-mask.txt)
- https://scale.com/leaderboard/fortress (seal-fortress.txt)
- https://scale.com/leaderboard/propensitybench (seal-propensitybench.txt)
- https://scale.com/leaderboard/distressbench (seal-distressbench.txt)
- https://scale.com/leaderboard/humanitys_last_exam (seal-hle.txt)
- https://scale.com/research (scale-research-index.txt)
- https://scale.com/research/fortress (scale-research-fortress.txt); https://arxiv.org/abs/2506.14922 (arxiv-fortress-abs.txt); https://huggingface.co/datasets/ScaleAI/fortress_public (hf-fortress-public.txt)
- https://scale.com/research/mask ; https://arxiv.org/abs/2503.03750 ; https://github.com/centerforaisafety/mask ; https://huggingface.co/datasets/cais/MASK
- https://arxiv.org/abs/2501.14249 (HLE); https://github.com/centerforaisafety/hle
- https://scale.com/research/propensitybench ; https://arxiv.org/abs/2511.20703
- https://arxiv.org/abs/2408.15221 (MHJ); https://scale.com/research/mhj
- https://arxiv.org/abs/2410.13886 (BrowserART)
- https://arxiv.org/abs/2403.03218 (WMDP); https://arxiv.org/abs/2402.04249 (HarmBench)
- https://scale.com/blog/first-independent-model-evaluator-for-the-USAISI ; https://fedscoop.com/us-ai-safety-institute-taps-scale-ai-for-model-evaluation/
- https://scale.com/guides/test-and-evaluation-vision
- System cards grepped for "Scale": https://cdn.openai.com/gpt-5-system-card.pdf ; https://cdn.openai.com/o1-system-card-20241205.pdf ; https://cdn.openai.com/pdf/2221c875-02dc-4789-800b-e7758f3722c1/o3-and-o4-mini-system-card.pdf ; https://cdn.openai.com/gpt-4o-system-card.pdf ; https://www-cdn.anthropic.com/4263b940cabb546aa0e3283f35b686f4f3b2ff47.pdf ; https://arxiv.org/pdf/2503.16431 (OpenAI external red-teaming paper)

## Gaps / UNVERIFIED
- No fetched primary source names Scale AI as a pre-deployment red-teamer for a specific frontier model; the "Scale ran pre-deployment red-teaming for several labs" claim remains UNVERIFIED beyond Scale's generic self-description and the MHJ permission statement.
- 404s: scale.com/red-teaming, scale.com/evaluation, scale.com/leaderboard/agentic_safety, scale.com/blog/scale-ai-and-uk-ai-safety-institute. A UK AISI partnership page was not found; any Scale–UK AISI arrangement is UNVERIFIED.
- Whether the Feb 2025 US AISI program produced published evaluations, and its status after AISI became CAISI, not verified (web search budget exhausted during this session).
- Repo links for PropensityBench and DistressBench corpora not captured.
- DistressBench numeric scores were not extracted from the page text.
