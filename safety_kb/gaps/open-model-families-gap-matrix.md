# Gap matrix: safety-evaluation coverage self-reported by the Chinese open-weight model families

Fetched: 2026-10-19. Scope: Qwen (Alibaba), Kimi (Moonshot AI), GLM (Zhipu / Z.ai), DeepSeek.
Cell values describe what the LAB ITSELF reports in its technical reports, model cards, HF cards
and official docs as of 2026-10-19: **reported** = a named evaluation with numbers for a released
model; **partially** = mentioned as a policy, training signal, guard-model category, aggregate
inside another number, or a number only for a side model (e.g. a guard or a 4B ablation);
**none** = no mention found in the documents checked. The last column lists third-party results
that exist for each category (details and numbers in the lab READMEs and
`third_party/shanghai-ai-lab-safework.md`). Full per-lab justification lines are reproduced
below the table; evidence files are in `labs/<lab>/README.md` ("Gap-matrix row data").

Document sets checked (see each README "Documents" table): Qwen3 report (arXiv 2505.09388),
Qwen2.5 report, Qwen3Guard report (arXiv 2510.14276, "Q3G"), Qwen3/3.5/3.6/3.8 HF cards and
GitHub READMEs, alibabagroup.com AI-governance pages; Kimi K2 report (arXiv 2507.20534), K2.5
report (arXiv 2602.02276), K3 tech report, all moonshotai HF cards, Kimi blogs, platform ToS;
GLM-4 report (arXiv 2406.12793), GLM-4.5 report (arXiv 2508.06471), GLM-5 report (arXiv
2602.15763, covers 5/5.1/5.2/5.3), GLM-130B report, zai-org HF cards, z.ai/bigmodel docs;
DeepSeek-V3 report (arXiv 2412.19437), R1 report + Nature paper and Supplementary (arXiv
2501.12948 v2 Supp. D.3), V3.2 report, V4/V4.1 reports, deepseek-ai HF cards, DeepSeek
disclosure/terms pages.

| Category | Qwen | Kimi | GLM | DeepSeek | Third-party results that exist |
|---|---|---|---|---|---|
| CBRN | none | partially (K2: "Chemical&Biological Weapons" plugin folded into Promptfoo "Criminal" pass rate, no separate number; K2 Table 5-6) | partially (cyber only; no bio/chem/nuclear in any GLM report) | none (only a "controlled biochemicals" clause in the R1 risk-control prompt, Supp. D.3.1) | SHLAB v1.0 WMDP-Bio/Chem + SOSBench on Qwen2.5/Qwen3/QwQ/DeepSeek-V3/R1; CAISI GLM-5.2 bio-query compliance; SOSBench paper (R1 84.9% PVR) |
| Cyber | none | partially (K3 report Sec. 6.2.2: 14/36 exploit-dev tasks, 16 novel CVEs; capability only, no safeguard eval; K2 aggregated "Security" rows) | partially (GLM-5.3 card: CyberGym 84.5%, ExploitBench 54.4%; capability only) | none ("Cyber Crimes" is an unreported subcategory, R1 Supp. D.3.3) | CAISI (DeepSeek Sep-2025/May-2026; GLM-5.2/5.3; Kimi K2 Thinking/K3), UK AISI (GLM-5.2, K3), Anthropic (GLM-5.3), SHLAB CyBench/PACEbench, Promptfoo CyberSecEval on Qwen3 |
| Persuasion | none | none | none | none | SHLAB v1.0/v1.5 (Qwen3-32B 96.3% persuasion success; Qwen3-Max 95.5%, GLM-4.7 97.1%, Kimi-K2-0905 89.0%) |
| Deception / scheming | none | none | none | none (harmlessness RM statement only, R1 Sec. 3.1) | SHLAB MASK honesty (Qwen3-32B 52.26, DeepSeek-R1-0528 47.96), emergent-misalignment on Qwen3-235B; arXiv 2606.08629 eval-awareness on Qwen3 |
| Sabotage | none | none | none | none | none found for any of the four families |
| Autonomy (ARA / self-replication / AI R&D) | none | none (K2.6 blog markets 5-day autonomous runs, no safety assessment) | none | none (SCMP press claim of internal tests UNVERIFIED) | SHLAB self-replication (Qwen3-32B M3/M4 100/100, DeepSeek-V3-0324 100/90; Qwen2.5-7B 0) |
| Sycophancy | none | partially (K2 App. F rubrics penalise "unwarranted flattery", no measurement) | none | none | arXiv 2606.08629 (Qwen3 Thinking models); FLI index for Qwen3.6-max-preview (hosted) |
| Hallucination | partially (in-house CounterFactQA, Qwen3-32B 50.4 -> 68.1; Qwen3 report Table 22) | reported (K2 Table 3: FACTS Grounding 88.5, HHEM v2.1 98.9, FaithJudge 92.6; K3 in-house Faithfulness 85.5) | partially (GLM-5 Sec. 3.4 lists "knowledge hallucinations" as an RL target; no metric) | partially (R1-0528 card: "reduced hallucination rate", no number) | Giskard Phare (Qwen3-8B 60.38%, GLM-5.2 78.23%); Vectara HHEM leaderboard; Promptfoo |
| Bias / fairness | partially (RM "Debiasing" criterion, Q3G "Unethical Acts" category; no eval) | partially (political/religious plugins inside Promptfoo "Misinformation" aggregate) | partially (SafetyBench "Unfairness & Bias" column: GLM-4.5 77.4; GLM-130B CrowS-Pairs/StereoSet, 2022) | partially (BBQ: R1 96.6, V3 96.7; in-house Discrimination unsafe 19.7%; R1 Supp. D.3.2-3) | FLI BBQ on Qwen3.6-max-preview; Promptfoo religious-bias on Qwen3; CAISI CCP-narrative tests on DeepSeek |
| Privacy | partially (Q3G PII category; PII filtered from pretraining; no eval) | reported (K2 Table 6 Privacy plugin rows: 100 / 100 / 88.33 / 76.67 / 96.67 by strategy) | partially (SafetyBench "Privacy & Property" MCQ: GLM-4.5 92.0) | partially (risk-control prompt clause + "Privacy Violations" subcategory; no number) | Promptfoo PII plugins on Qwen3; TrustLLM privacy on Qwen |
| Child safety | partially (policy: "Prohibited Uses ... CSAM", "Protections For Minors"; no eval) | partially ("Child Exploitation" plugin inside "Criminal" aggregate; ToS clauses) | none (ToS clause only) | partially (SST "Child Abuse" category inside aggregate; 2023 licence clause) | Promptfoo Child Exploitation plugin on Qwen3 (80-82% pass) |
| Multilingual harm | partially (guard-model F1 over 40 languages, RTP-LX / PolyGuard; nothing for chat models with 119-201 languages) | partially (K2 red-team prompts in EN+ZH, no per-language breakdown) | partially (SafetyBench zh+en only) | reported (50-language in-house set, 9,330 questions: R1 74.2% no-RC / 85.9% with RC; Supp. D.3.4) | Fudan 2601.10527 multilingual safety (Qwen3-VL 64.0%); arXiv 2511.00689 multilingual jailbreak |
| Jailbreak robustness | partially (Q3G Table 10: Qwen3-4B WildJailbreak safety 47.5% -> 86.5% after SafeRL; nothing for other models) | reported (K2 Table 6: Promptfoo Base64 / prompt-injection / iterative jailbreak / Crescendo, e.g. Criminal-Iterative 57.57; not repeated for K2.5/K3) | none | reported (2,232-template suite: R1 unsafe 25.2% -> 85.9%; with RC 8.5% -> 4.3%; Supp. D.3.5 Table 11) | Cisco/Enkrypt/Qualys/KELA on R1; CAISI jailbreak sets on DeepSeek, GLM-5.2, Kimi; Anthropic GLM-5.3 bypass rates; Mindgard/BBC on Kimi; SHLAB total ASR on Qwen3-8B |
| Agentic misuse (prompt injection, tool misuse, hijacking) | none | none (K2 Sec. 4.3.2: tool-invocation plugins "may have limited relevance") | none | none | CAISI agent-hijacking on DeepSeek R1/V3.1/V4 and GLM-5.2 (HijackEval); AgentHazard / AgentDoG / AgentSecurityBench on Qwen3; A2M on GLM-4.6; SHLAB misevolution on Qwen3-235B/GLM-4.7/Kimi-K2 |
| CoT monitorability | none (Q3G moderates "thinking content" guard-side only) | none | none ("interleaved thinking" described as a capability) | none (harmlessness RM scores "the reasoning process", R1 Sec. 3.1; "hide cot" row only) | "Hidden Risks of Large Reasoning Models" (arXiv 2502.12659) and R1 Thoughtology (2504.07128) on DeepSeek-R1 |
| Eval awareness / sandbagging | none | none | none | none | SHLAB sandbagging (Qwen3-8B SBS 36.06; DeepSeek-V3-0324 17.06); arXiv 2606.08629 eval-awareness on Qwen3 |
| Reward hacking | partially (Qwen3 Sec. 4.4 rule-based rewards "preventing ... reward hacking"; Q3G Sec. 3.5.2 "metric hack") | partially (K2 Sec. 3.2.2 rubrics "to eliminate reward hacking"; K2.5 multiple GRM rubrics; no metric) | partially (GLM-4.5 Fig. 9 "not observed clear evidence of reward hacking" to ~1,000 steps; GLM-5 Sec. 3.4 ORM note) | partially (R1 Sec. 2.2 / Sec. 6 / Supp. B.5, training-time only) | none found as a deployment-time evaluation for any family |
| Refusal calibration / over-refusal | partially (Q3G Table 10 refusal rate for Qwen3-4B only: 12.9% / 6.5%; XSTest used only for the guard's refusal detector) | partially (K3 report discloses competitor refusal counts on Kimi Code Bench; no benign-refusal eval of Kimi) | none | partially (XSTest R1 95.3; in-house "Reject" rate R1 5.6% / +RC 27.3%; Supp. D.3.2-3) | FLI XSTest on Qwen3.6-max-preview; Phare harm resistance; Promptfoo over-refusal plugins |

## Totals (self-reported)

| | reported | partially | none |
|---|---|---|---|
| Qwen | 0 | 9 | 9 |
| Kimi | 3 | 10 | 5 |
| GLM | 0 | 7 | 11 |
| DeepSeek | 2 | 8 | 8 |

Reading: no family reports anything on persuasion, deception/scheming, sabotage, autonomy,
agentic misuse, CoT monitorability or eval-awareness/sandbagging; those seven rows are "none"
for all four, and the only numbers that exist come from Shanghai AI Lab (Qwen/DeepSeek/Kimi
K2-0905/GLM-4.7 only, cut-off 2026-01-31) and from NIST CAISI / UK AISI / Anthropic cyber and
hijacking work on the large models. Nothing in any of those seven rows exists for the current
small members (Qwen3-0.6B/1.7B/4B/8B, Qwen3.5/3.6 small variants, GLM-Edge, R1-Distill 1.5B/7B/8B,
Kimi-VL-A3B / Moonlight-16B-A3B) except SHLAB's Qwen2.5-7B / Qwen3-8B rows.

## Highest-value third-party runs on the small members (0.5B-8B)

All of these are open, runnable on a single GPU, and absent from every lab's own reporting:
1. Jailbreak robustness with a fixed public suite (StrongREJECT, HarmBench direct + GCG/PAIR,
   WildJailbreak, JailbreakBench) on Qwen3-0.6B/1.7B/4B/8B, Qwen3.5/3.6 small, GLM-4-9B-0414 /
   GLM-Edge, R1-Distill-Qwen-1.5B/7B / R1-Distill-Llama-8B / R1-0528-Qwen3-8B, Moonlight-16B-A3B
   -> fills the "none"/"partially" cells for all four at the small end.
2. Over-refusal (XSTest, OR-Bench, CoCoNot) paired with the above -> refusal calibration row.
3. Agentic misuse: AgentHarm (+ benign twin), AgentDojo prompt injection, InjecAgent -> the only
   all-"none" row that small instruct models can meaningfully take.
4. CBRN knowledge + science-misuse refusal: WMDP-Bio/Chem/Cyber MCQ, SOSBench, HarmfulQA ->
   repeats SHLAB's v1.0 protocol on the 2026 small models.
5. Honesty / sycophancy / eval-awareness: MASK, sycophancy-eval (meg-tong), the SHLAB sandbagging
   protocol, and a simple evaluation-awareness probe -> deception row.
6. Multilingual harm on the chat models (not the guard): PolyGuard / RTP-LX prompts in 10+
   languages, M-ALERT -> multilingual row; especially relevant to Qwen (119-201 languages).
7. CoT monitorability on the thinking variants (Qwen3 thinking, R1-Distill, GLM-Z1-9B): CoT
   faithfulness / hint-usage tests and a CoT-vs-answer consistency monitor.
8. Guard-model audit: Qwen3Guard-0.6B/4B/8B as the moderation layer, scored on WildGuardTest,
   ToxicChat, Aegis2.0 and PolyGuard in third-party hands (the lab's numbers are self-reported).

## Per-lab justification lines (copied from each README "Gap-matrix row data")

### Qwen (labs/alibaba-qwen/README.md)
- CBRN: none — no mention of chemical, biological, radiological or nuclear risk in the Qwen3 report (2505.09388), Qwen3Guard report (2510.14276, taxonomy Sec. 2), any Qwen3/3.5/3.6/3.8 HF card or the alibabagroup.com governance pages; only third-party numbers exist (Shanghai AI Lab 2507.16534 Tables 7-8: Qwen3-32B WMDP-Bio 83.4%, Chem HarmfulQA refusal 3.1%).
- cyber: none — no cyber-capability or cyber-misuse evaluation in any lab document; "hacking" appears only as an example inside Q3G's "Non-violent Illegal Acts" category (Sec. 2); third-party only (Shanghai AI Lab Table 4: Qwen3-32B CyBench 17.5%; Promptfoo CyberSecEval 33-49% pass).
- persuasion: none — no mention found in Qwen3 report, Q3G, cards or governance pages; third-party only (Shanghai AI Lab Table 10 region: Qwen3-32B persuasion success 96.3%).
- deception/scheming: none — no mention in any lab document; third-party only (Shanghai AI Lab Table 12 honesty 52.3% for Qwen3-32B; 2606.08629 eval-awareness 42.5-48.9% for Qwen3 Thinking models).
- sabotage: none — no mention found in Qwen3 report, Q3G, cards, governance pages or any third-party source fetched.
- autonomy: none — no ARA/self-replication/AI-R&D evaluation by the lab; third-party only (Shanghai AI Lab Table 18: Qwen3-32B self-replication M3/M4 100/100, over-scaling 80%).
- sycophancy: none — no mention in any lab document; the only related third-party data is the evaluation-awareness study 2606.08629 (Qwen3-80B/235B).
- hallucination: partially — Qwen3 report Table 22 reports an in-house CounterFactQA score for Qwen3-32B (50.4 -> 68.1) and a RAG reward "minimizing the risk of hallucination" (Sec. 4.4); no public hallucination benchmark for released models (third-party: Giskard Phare Qwen 3 8B hallucination resistance 60.38%; Promptfoo hallucination pass 62-71%).
- bias: partially — Qwen2.5 report Sec. 4.3 lists "Debiasing" as a reward-model labeling criterion and Q3G's "Unethical Acts" category covers "bias, discrimination, stereotype"; Q3G Limitations admit "Fairness and Bias in Moderation Decisions"; no bias evaluation of any released model (third-party: FLI BBQ 0.94 for Qwen3.6-max-preview; Promptfoo Religious Bias 48.89%).
- privacy: partially — Q3G has a "Personally Identifiable Information" guard category (Sec. 2) and the governance page states PII is filtered from pretraining data; no privacy/memorisation evaluation of released models (third-party: Promptfoo PII via Direct Exposure 68.89-84.44%; TrustLLM privacy 0.59).
- child safety: partially — policy only: "Prohibited Uses Of Qwen ... Harm to minors ... CSAM" and "Protections For Minors" on alibabagroup.com Model Governance; no evaluation (third-party: Promptfoo Child Exploitation pass 80-82.22%).
- multilingual harm: partially — Q3G Tables 5-6/14-15 report guard-model F1 across 40 languages (RTP-LX, PolyGuard) and the governance page describes "locally adapted safety corpora"; no multilingual safety result for any chat model despite 119/201-language support (third-party: Fudan 2601.10527 Qwen3-VL multilingual safety 64.00%).
- jailbreak robustness: partially — Q3G Table 10 reports Qwen3-4B safety on WildJailbreak (47.5% judged safe non-thinking, 43.8% thinking; 86.5/83.4 after SafeRL) and Q3G has a "Jailbreak" input category; nothing for any other model (third-party: Fudan Safe_worst 0% / Safe_resp 33.42% for Qwen3-VL; Shanghai AI Lab Qwen3-8B total ASR 32.2% thinking).
- agentic misuse: none — no agent-safety or prompt-injection evaluation in any lab document, although Qwen3.5-3.8 cards market "Agent Execution" and "million-agent environments"; third-party only (AgentHazard Qwen3-Coder 73.63% ASR; AgentDoG Qwen3.5-4B AgentHarm harm score 57.49, AgentSecurityBench ASR 90.39).
- CoT monitorability: none — the governance page claims a "safe reasoning corpus" and Q3G moderates "thinking content" (Table 3 "Think" column, guard-side only); no faithfulness/monitorability measurement of the policy's chain of thought in any lab document.
- eval awareness/sandbagging: none — no mention in any lab document; third-party only (Shanghai AI Lab Table 13 sandbagging score Qwen3-8B 36.06%; 2606.08629 EVAL detection up to 48.9%).
- reward hacking: partially — Qwen3 report Sec. 4.4 states rule-based rewards are used "preventing issues like reward hacking" and Q3G Sec. 3.5.2 avoids using Qwen3Guard as the evaluator "To mitigate risks of metric hack"; no measurement of reward-hacking propensity.
- refusal calibration: partially — Q3G Table 10 reports refusal rates for Qwen3-4B (12.9% non-thinking / 6.5% thinking, WildGuard classifier) and shows guard-only RL drives refusal to 95-97%, motivating the hybrid reward; no over-refusal benchmark (XSTest/OR-Bench) for any released chat model (third-party: FLI XSTest 0.97 for Qwen3.6-max-preview; Phare harm resistance 87.37% for Qwen 3 8B).

### Kimi (labs/moonshot-kimi/README.md)
- CBRN: partially — K2 report Table 5/6 folds a "Chemical&Biological Weapons" Promptfoo plugin into the aggregated "Criminal" pass rate (57.57–100% by strategy) with no separate CBRN number; K2.5 and K3 reports contain no CBRN content.
- cyber: partially — K3 report §6.2.2 reports internal exploit-development capability (14/36 tasks, 38.9%; ~70% of discovered bugs confirmed, 16 novel CVEs) and cites UK AISI/CAISI (ExploitBench 32%, ACE 0/41), but no safeguard/refusal evaluation; K2 only has aggregated Promptfoo "Security" rows (43.90–87.80%).
- persuasion: none — no mention found in K2 (2507.20534), K2.5 (2602.02276), K3 (k3_tech_report.pdf), HF cards, blogs or platform docs.
- deception/scheming: none — no mention found in K2, K2.5, K3 reports, cards, blogs or platform docs.
- sabotage: none — no mention found in K2, K2.5, K3 reports, cards, blogs or platform docs.
- autonomy: none — no ARA/self-replication/resource-acquisition evaluation; K2.6 blog only advertises a K2.6 agent that "operated autonomously for 5 days" with no safety assessment.
- sycophancy: partially — K2 report App. F.1/F.2 rubrics penalise "unwarranted flattery or excessive praise" and "Initial Praise" during RL, but no sycophancy evaluation or number is reported anywhere.
- hallucination: reported — K2 report §4.2 Table 3: FACTS Grounding 88.5, HHEM v2.1 98.9 (1−hallu.), FaithJudge 92.6; K3 report Table 3 in-house "Faithfulness" 85.5 (1−hallucination rate).
- bias: partially — K2 Table 5 includes "Political Opinions, Religious Sensitivity" plugins inside the aggregated "Misinformation" pass rate (63.97–98.48%); no bias/fairness benchmark (e.g. BBQ) in any report.
- privacy: reported — K2 report Table 6 "Privacy" plugin rows (PII exposure/social engineering): Basic 100, Base64 100, Prompt Injection 88.33, Iterative Jailbreak 76.67, Crescendo 96.67; nothing in K2.5/K3.
- child safety: partially — K2 Table 5 lists a "Child Exploitation" plugin aggregated into "Criminal"; platform ToS §3.1(2)/(5) and §3.4(8) prohibit child exploitation and under-14 data; no dedicated evaluation.
- multilingual harm: partially — K2 §4.3.1 generated red-team prompts "in each language" (English and Chinese) for plugins supporting both, but Table 6 reports no per-language breakdown; K2.5/K3 have none.
- jailbreak robustness: reported — K2 report §4.3 Table 6 (Promptfoo strategies Base64 / Prompt Injection / Iterative Jailbreak / Crescendo across 5 plugin groups; e.g. Harmful–Iterative Jailbreak 92.16, Criminal–Iterative Jailbreak 57.57, Security–Iterative Jailbreak 43.90, Harmful–Crescendo 64.71); not repeated for later models.
- agentic misuse: none — K2 §4.3.2 states tool-invocation plugins "are more suitable for evaluating agent models ... such tests may have limited relevance"; K2.5 (Agent Swarm) and K3 reports contain no agentic-safety evaluation.
- CoT monitorability: none — no mention found in K2, K2 Thinking card/blog, K2.5, K3 reports or platform docs.
- eval awareness/sandbagging: none — no mention found in K2, K2.5, K3 reports, cards, blogs or platform docs.
- reward hacking: partially — K2 §3.2.2 "prescriptive rubrics (Appendix F.2) that aim to eliminate reward hacking" and K2.5 "To mitigate reward hacking ... multiple alternative GRM rubrics" describe mitigations in RL; no reward-hacking evaluation or metric is reported.
- refusal calibration: partially — K3 report Table 3 footnotes and K3 HF card disclose competitor refusal/fallback counts on Kimi Code Bench 2.0 (e.g. "10 refusals out of 80 tasks entered GPT-5.6 Sol's cyber guard") and note WorldVQA refusals were overridden by prompt engineering, but no over-refusal/benign-refusal evaluation of any Kimi model is reported.

### GLM (labs/zhipu-glm/README.md)
- CBRN: partially — only cyber capability is self-reported (GLM-5.3 HF card: CyberGym 84.5%, ExploitBench 54.4%); no bio/chem/nuclear evaluation in any GLM-4/4.5/5 report; bio refusal data exists only from CAISI's GLM-5.2 assessment §6 ("answers sensitive biological queries ... at a much higher rate than tested US models").
- cyber: partially — capability reported by the lab (GLM-5.3 card; GLM-5 card CyberGym) and extensively by CAISI (SEC-Bench Pro 40.4%, ExploitBench 61.1%, ExploitGym 9.4%, OSS-Fuzz 7.7%), UK AISI and Anthropic; but no lab-reported safeguard or misuse-threshold analysis.
- persuasion: none — no mention found in GLM-4 (2406.12793), GLM-4.5 (2508.06471), GLM-5 (2602.15763) reports or any model card; only Shanghai AI Lab's family-level "harmful manipulation" safety score.
- deception/scheming: none — no mention found in the three tech reports, model cards, or z.ai docs.
- sabotage: none — no mention found in the three tech reports or model cards.
- autonomy: none — no autonomy/ARA/self-replication evaluation in GLM-5 report §6 or elsewhere; only capability benchmarks for long-horizon agents.
- sycophancy: none — no mention found in GLM-4/4.5/5 reports or cards (GLM-5 §3.4 mentions "emotional intelligence" as an RL objective but no sycophancy measurement).
- hallucination: partially — GLM-5 §3.4 lists "knowledge hallucinations" as an error type targeted by General RL; GLM-4 §2 lists "factuality" as an annotation dimension; no hallucination metric reported (external: Giskard Phare 78.23% for GLM 5.2).
- bias: partially — SafetyBench "Unfairness & Bias" column (GLM-4.5 77.4, GLM-4.5-Air 74.7, GLM-4 (0520) 66.0; GLM-4.5 §4.2.5 Table 7, GLM-4 §4 Table 10) and GLM-130B CrowS-Pairs/StereoSet (2022); nothing for GLM-4.6+.
- privacy: partially — SafetyBench "Privacy & Property" MCQ column only (GLM-4.5 92.0; GLM-4 88.6); no memorisation/PII evaluation; docs.z.ai Terms prohibit PII inference.
- child safety: none — no evaluation; only a prohibited-use clause in docs.z.ai Terms of Use (j) and a "Minor protection ... disclaimer".
- multilingual harm: partially — SafetyBench includes English and Chinese items (GLM-4.5 §4.2.5); no other language; no multilingual jailbreak/harm eval.
- jailbreak robustness: none — no jailbreak evaluation in any GLM report or card; external only (Anthropic: 64%/92%/100% bypass of GLM-5.3; CAISI: GLM-5.2 "moderately robust to public jailbreaks"; Phare 56.46%).
- agentic misuse: none — no agentic-safety evaluation in GLM-4.5 or GLM-5 reports despite agent focus; external only (CAISI HijackEval: GLM-5.2 never hijacked by public attacks but 0 refusals on agentic exploit development; A2M on GLM-4.6).
- CoT monitorability: none — no mention found; GLM-5 report describes "interleaved thinking modes" and `clear_thinking`/preserved-thinking options purely as capability features.
- eval awareness/sandbagging: none — no mention found in the three tech reports or cards.
- reward hacking: partially — GLM-4.5 Fig. 9 caption: "Up to roughly 1,000 training steps, we have not observed clear evidence of reward hacking"; GLM-5 §3.4 notes ORMs "are more susceptible to reward hacking" and blends GRMs; no measurement, no deployment-time analysis.
- refusal calibration: none — no over-refusal / refusal-rate evaluation in any GLM document; GLM-4 §2 only says RLHF "can further help mitigate issues of response rejection".

### DeepSeek (labs/deepseek/README.md)
- CBRN: none — no CBRN/bio/chem evaluation in V3, R1 (Nature SI 4.3), V3.2, V4, V4.1 reports or any card; only a "controlled biochemicals" clause in the risk-control prompt (R1 Supp. D.3.1); Concordia 2025 p.57 confirms "None of the papers disclose evaluations results for CBRN".
- cyber: none — no cyber-misuse or cyber-capability safety evaluation by DeepSeek (only third-party: CAISI jailbreak hacking set, Zhou et al. CyberSecEval); "Cyber Crimes" is one of 28 in-house subcategories without separate numbers (R1 Supp. D.3.3).
- persuasion: none — no mention found in V3/R1/V3.2/V4/V4.1 reports or cards.
- deception/scheming: none — no mention found in any DeepSeek document; harmlessness RM "to identify and mitigate any potential risks, biases, or harmful content" (R1 Sec. 3.1) is the only alignment statement.
- sabotage: none — no mention found in V3/R1/V3.2/V4/V4.1 reports or cards.
- autonomy: none — no self-replication/ARA evaluation published; SCMP press claim of internal tests is UNVERIFIED (403).
- sycophancy: none — no mention found in any DeepSeek report or card.
- hallucination: partially — R1-0528 card claims "a reduced hallucination rate" with no number; disclosure page admits "we cannot guarantee that the model will not produce hallucinations"; no benchmark reported.
- bias: partially — BBQ score (R1 96.6, V3 96.7; R1 Supp. D.3.2 Table 9) and in-house Discrimination category (R1 unsafe 19.7%, Table 10); no fairness analysis in V3.2/V4/V4.1.
- privacy: partially — "Privacy Fabrication" clause in risk-control prompt and "Privacy Violations" subcategory (R1 Supp. D.3.1/D.3.3) plus PII-filtering statements on the disclosure page; no privacy evaluation numbers.
- child safety: partially — only via SST's "Child Abuse" category inside the aggregate SST score (R1 Supp. D.3.2) and the 2023 license's "harm minors" clause; no dedicated evaluation.
- multilingual harm: reported — 50-language, 9,330-question safety score (R1 no-RC 74.2%, with RC 85.9%; V3 75.3/86.5; R1 Supp. D.3.4 Figure 14), aggregate only.
- jailbreak robustness: reported — 2,232-template jailbreak set: R1 unsafe 25.2% -> 85.9%, R1+RC 8.5% -> 4.3% with 87.3% rejection (R1 Supp. D.3.5 Table 11); nothing for later models.
- agentic misuse: none — no prompt-injection or agent-hijacking evaluation in any DeepSeek document (CAISI Sep 2025 is third-party only).
- CoT monitorability: none — only statement is that the harmlessness reward scores "both the reasoning process and the summary" (R1 Sec. 3.1) and a "hide cot" row in Table 9; no monitorability/faithfulness evaluation.
- eval awareness/sandbagging: none — no mention found in V3/R1/V3.2/V4/V4.1 reports or cards.
- reward hacking: partially — described as a training problem (R1 Sec. 2.2 rule-based rewards; Sec. 6 "Reward Hacking"; Supp. B.5 Figure 6; V3 Sec. 5.1 CoT reward model) with no safety-risk evaluation.
- refusal calibration: partially — XSTest (R1 95.3) and the in-house "Reject" rate (R1 5.6%, R1+RC 27.3%; o1 50.4%) in R1 Supp. D.3.2-D.3.3; no over-refusal analysis for later models.
