# Gemini 4 Argon model card: how Google evaluates and monitors safety

- Document: Gemini 4 Argon Model Card, Google DeepMind. "Published: October 2026".
- URL (web): https://deepmind.google/models/model-cards/gemini-4-argon/
- URL (PDF): https://storage.googleapis.com/deepmind-media/Model-Cards/Gemini-4-Argon-Model-Card.pdf (14 pp.)
- Fetched: 2026-10-19 (curl). Local copies: `sources/google/model-card-gemini-4-argon.md`, `sources/google/model-card-gemini-4-argon-pdf.md`, `sources/google/Gemini-4-Argon-Model-Card.pdf`.
- Companion documents the card points to (covered by other agents; recorded here only as the card describes them):
  - Safety & Security Report: https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf. The card says it "systematically covers our set of defenses" (Safety & Security, intro), is the place to "see ... for details" on the automated safety evals (Training and Development Evaluation Results), and holds "more information about the risks and mitigations" (Risks and Mitigations). See `labs/google/gemini-4-safety-report-notes.md`.
  - Frontier Safety Framework: https://deepmind.google/frontier-safety/ ("we perform testing following the guidelines in Google DeepMind's Frontier Safety Framework (FSF)", Evaluation Approach) and the FSF v3.1 PDF (April 17, 2026) linked from "Frontier Safety Assessment": https://storage.googleapis.com/deepmind-media/DeepMind.com/Blog/strengthening-our-frontier-safety-framework/frontier-safety-framework_3-1.pdf.
- Evaluation methodology page linked from the card: https://deepmind.google/models/evals-methodology/gemini-4-argon, which 301-redirects to a 5-page PDF, https://storage.googleapis.com/deepmind-media/gemini/gemini_4_argon_model_evaluation.pdf (local: `sources/google/gemini-4-argon-model-evaluation-methodology.md`).
- Other linked pages read for this note (all fetched 2026-10-19; see README for the full list): Google AI Principles; ai.google/safety; Responsible AI Progress Report (Feb 2025); Gen AI Prohibited Use Policy; child-safety commitments blog (Apr 2024); GDM Responsibility & Safety page; GDM Evals page; Gemini API Additional Terms; and, two levels deep, "Developing Gemini 4 Argon responsibly and safely" (Google blog, Oct 13, 2026), "Piloting the world's first double-blind AI evaluations" (GDM blog, Aug 27, 2026), and the Fairwind Program page.

Model facts stated on the card (Model Information): "a large scale sparse mixture-of-experts (MoE) ... transformer-based model with native multimodal support for text, vision, and audio inputs"; "not a modification or a fine-tune of a prior model"; inputs text, image, audio, video; text output; "combined input-output token context window of up to 1M"; knowledge cutoff "March 2026"; distributed via Gemini App, Gemini API, Google AI Studio, Gemini for business, Google Antigravity, Google AI Mode (Distribution).

Web vs PDF differences (checked line by line): identical text except (i) the PDF section header reads "Safety, & Security" (stray comma); (ii) the Tone row reads "+5.50%" on the web and "+5.50pp" in the PDF; (iii) the PDF renders the benchmark table and the "Latest model cards" footer differently. All numbers agree.

---

## (a) How Google evaluates and monitors safety for this model

### Who runs what (as stated on the card)

Section "Safety & Security > Evaluation Approach":

> "Gemini 4 Argon was developed in partnership with internal safety, security, and responsibility teams. A range of evaluations and red teaming activities were conducted to help improve the model and inform decision-making."

The card lists four evaluation types ("included but were not limited to"):

1. "Training/Development Evaluations including automated and human evaluations carried out continuously throughout and after the model's training, to monitor its progress and performance;"
2. "Human Red Teaming conducted by specialist teams who sit outside of the model development team, across the policies and desiderata, deliberately trying to spot weaknesses and ensure the model adheres to safety policies and desired outcomes;"
3. "Automated Red Teaming to dynamically evaluate Gemini for safety and security considerations at scale, complementing human red teaming and static evaluations;"
4. "Ethics & Safety Reviews were conducted ahead of the model's release"

plus: "In addition, we perform testing following the guidelines in Google DeepMind's Frontier Safety Framework (FSF)."

Human red teaming is located organisationally in "Human Red Teaming Results": "We conduct manual red teaming by specialist teams who sit outside of the model development team in Google's Trust & Safety organization. High-level findings are fed back to the model team."

The automated safety numbers are explicitly internal: "Results for some of the internal safety evaluations conducted during the development phase are listed below. The evaluation results are for automated evaluations and not human evaluation or red teaming." (Training and Development Evaluation Results)

### Internal vs external

- The card's only explicit reference to external input is in "Frontier Safety Assessment": "For Gemini 4 Argon, drawing on internal and external results, the inherent capability thresholds that the model may have reached and our response are as follows". It does not name any external evaluator, government institute, or third-party lab anywhere. "Expert red teaming" for the bio CCL is not attributed to internal or external parties on the card.
- The capability benchmarks are a mix: per the methodology PDF, several Argon scores are "self computed" and several are "sourced from" third-party leaderboards (Vals AI, Zapier, Proximal, Surge, Terminal-Bench authors, CWE-bench, Gray Swan). Competitor numbers "are sourced from providers' self reported numbers unless otherwise mentioned". See table in (b).
- Two levels out, the Argon safety blog (Oct 13, 2026) states "external bio jailbreak red teaming could only unlock less than 1% of bio sub-tasks we test for", and the double-blind-evaluation blog (Aug 2026) describes a pilot with "the Singapore AI Safety Institute, OpenMined, AVERI, and MLCommons" on "a Gemini Flash Lite model", not Argon. The Fairwind Program page describes staged "exclusive access to Gemini 4 Argon" for vetted cyber defenders ("over 650 partners globally") before broad release; the safety blog says "we first wanted cyber defenders to put it to work via our Fairwind Program, while our own security teams used it to scan critical systems".

### Pre-deployment vs ongoing / post-deployment

- Pre-deployment: development evals "throughout and after the model's training"; "Ethics & Safety Reviews ... ahead of the model's release"; FSF "critical capability assessments" with safety cases for the two CCLs that "cannot be ruled out" and a residual risk assessment for the TCL (Frontier Safety Assessment). The FSF v3.1 PDF, section 1.3.2: "We conduct a critical capability assessment prior to the first external deployment of a new frontier AI model."
- Post-deployment monitoring: the card itself says nothing explicit about production monitoring of Argon. The hooks are in linked documents: FSF v3.1 section 2.1.2 step 3, "Post-deployment processes: our residual risk assessments, safety cases and mitigations may be updated as a result of post-market monitoring, including information about incidents relating to our frontier safety risk domains"; FSF glossary lists deployment mitigations as "safety post-training, input/output/chain-of-thought monitoring and analysis, account moderation, jailbreak detection and patching, user verification, and bug bounties". The Argon safety blog describes "three layers of real-time protection" (input screening by smaller models; "activation probes" reading internal signals for cyber/bio knowledge; "Continuous monitoring ... cutting off the agent mid-stream") and "an automated misalignment monitor that reads both the agent's actions and its internal 'scratchpad' ... in real time", run "in our products, on our internal coding agents, during our training runs, and during our capability evaluations". ai.google/safety: "Our safety and security teams provide a follow-the-sun model for 24/7/365 monitoring of all Google products, services, and infrastructure." Gemini API Additional Terms: for paid services "Google logs prompts and responses for a limited period of time, solely for detecting and preventing violations of the Prohibited Use Policy".
- Card-level caveat on updates: "Model cards may be updated from time to time; for example, to include updated evaluations as the model is improved or revised."

### Frequency and what triggers re-evaluation

The card gives no frequency. FSF v3.1 (section 1.3.2) is the operative rule: critical capability assessment "prior to the first external deployment"; for subsequent versions, "material capability change assessments on various checkpoints upon the completion of a post-training run"; a fresh critical capability assessment is required "if (1) the model has meaningful new capabilities or material increases in performance; and (2) we believe such material capability increase could materially undermine the justification for why the risks stemming from the model are acceptable"; and "We may run early warning evaluations more frequently or adjust alert thresholds if the rate of progress suggests our safety buffer is no longer adequate." The Framework itself "will be reviewed at least once a year" (section 5.1).

### Governance and sign-off

- Card: "Ethics & Safety Reviews were conducted ahead of the model's release" (no body named). The FSF text referenced from the card: "As outlined in our FSF, models reaching TCLs or CCLs will be subject to residual risk assessments ... For models reaching CCLs, the residual risk assessment will be informed by a supplemental safety case outlining the mitigations."
- FSF v3.1 section 2.1.2 step 2: "external deployments of a model take place only after the appropriate governance function determines the residual risk to be acceptable (including a safety case where a CCL has been reached)". Section 4.1 names no body: "a well-established and comprehensive internal governance structure ... legal, compliance, and safety reviews with escalation procedures".
- GDM Responsibility & Safety page names the bodies: "the Responsibility and Safety Council (RSC), our longstanding internal review group co-chaired by our COO Lila Ibrahim and VP, Responsibility Helen King" and "Our AGI Safety Council, led by our Co-Founder and Chief AGI Scientist Shane Legg".
- Responsible AI Progress Report (Feb 2025), "Govern": "Leadership reviews. Executive reviewers with expertise in responsible AI carefully assess evaluation results, mitigations, and risks before making a launch decision."
- Child-safety sign-off is threshold-based: "For child safety evaluations, Gemini 4 Argon satisfied required launch thresholds, which were developed by expert teams to protect children online" (Human Red Teaming Results).

### Policy basis

Safety Policies section lists five content categories the model must not produce: CSAM/exploitation; dangerous content ("e.g., promoting suicide, or instructing in activities that could cause real-world harm"); sexually explicit content; hate & harassment; "Medical advice and information that runs contrary to scientific or medical consensus". Acceptable use is governed by the Generative AI Prohibited Use Policy (Last Modified Dec 17, 2024), whose four headline prohibitions the card paraphrases.

---

## (b) Exactly what is run

### Table 1: Safety and frontier-safety evaluations (model card, Safety & Security)

| Evaluation (card name) | What it measures (card wording) | Reported result | Comparator | Run by | Notes / withheld |
|---|---|---|---|---|---|
| Text to Text Safety (lower is better) | "Automated content safety evaluation measuring adherence to safety policies across text prompts" | +1.57pp (regression, marked red) | Gemini 3.1 Pro | Internal, automated | Absolute rates, sample size, prompt set, CI width not given; "within confidence intervals" |
| Multilingual Safety (lower is better) | "Automated safety policy evaluation across multiple languages" | -3.16pp (improvement) | Gemini 3.1 Pro | Internal, automated | Languages not listed |
| Image to Text Safety (lower is better) | "Automated content safety evaluation ... with both images and text as inputs" | -9.29pp (improvement) | Gemini 3.1 Pro | Internal, automated | No audio/video safety eval reported |
| Tone (higher is better) | "objective, neutral, and non-preachy tone of model refusals" | +5.50% (web) / +5.50pp (PDF) | Gemini 3.1 Pro | Internal, automated | Unit inconsistent across versions |
| Unjustified-refusals (lower is better) | "over-refusals on benign or borderline prompts that can be safely fulfilled" | -9.60pp (improvement) | Gemini 3.1 Pro | Internal, automated | |
| Manual review of flagged losses | "we review flagged content to check for egregious or dangerous material" | "losses were overwhelmingly either a) false positives or b) not egregious" | n/a | Internal, human | No counts |
| Human red teaming: content safety policies | across "the policies and desiderata" | "similar or improved safety performance compared to Gemini 3.1 Pro" | Gemini 3.1 Pro | Google Trust & Safety (outside model team) | No numbers |
| Human red teaming: child safety | expert-set launch thresholds | "satisfied required launch thresholds" | threshold | Google Trust & Safety | Thresholds undisclosed |
| Human red teaming: out-of-policy issues | "potential issues outside of our strict policies" | "found no egregious concerns" | Gemini 3.1 Pro | Google Trust & Safety | No detail |
| Automated Red Teaming | "dynamically evaluate Gemini for safety and security considerations at scale" | No result reported on card | n/a | Internal | ai.google/safety describes ART as "our internal Gemini team constantly attacks Gemini" |
| Ethics & Safety Reviews | pre-release review | "conducted" | n/a | Internal | No findings disclosed |
| FSF: CBRN Uplift TCL | "low to medium resourced actors uplift ... significant but not severe harm" | "TCL not reached" for chemical, radiological, nuclear "with reasonable confidence" | T/CCL threshold | Internal + unspecified external | "responses lacked nuanced expert knowledge and actionable depth necessary to complete priority harm journeys" |
| FSF: CBRN Uplift Level 1 CCL (biological) | uplift "resulting in additional expected harm at a severe scale" | "CCL cannot be ruled out"; safety case developed | "web baselines" and "previously tested models" | "Expert red teaming" (affiliation not stated) | "measurable capability uplift ... in two separate scenarios, with the model providing comprehensive, accurate, and actionable information for both scenarios"; no numbers, scenarios undisclosed |
| FSF: Cybersecurity Uplift Level 1 CCL | "sufficient uplift with high impact cyber attacks" | "CCL cannot be ruled out"; safety case developed | threshold | Internal ("our evaluations and quantitative modeling") | "additional evidence about the efficacy of Gemini 4 Argon and other frontier models in cyber contexts"; no numbers on card. Safety blog: "solving all 12 of the end-to-end simulated cyberattack scenarios, up from five in our previous generation" |
| FSF: Harmful Manipulation Level 1 CCL | "systematically and substantially change beliefs and behavior in identified high stakes contexts" | "CCL not reached" | threshold | Internal "human behavioral studies" | "some ability to influence user beliefs and behaviors during one-on-one direct conversations ... may provide utility in the planning stage of a malicious influence operation"; no effect sizes, n, or study design |
| FSF: Stealth and Situational Awareness TCL | situational awareness + stealth sufficient to "significantly undermine human control" | "passes 14/15 of our challenges"; "TCL cannot be ruled out"; residual risk assessment performed; safeguards "for both internal and external deployments" | threshold | Internal | Only numeric FSF result on the card; challenges not described |
| FSF: ML R&D acceleration level 1 CCL | "AI progress substantially accelerating from historical rates" | "CCL not reached" | "our CCL threshold" | Internal benchmark | "We use an internal benchmark to assess performance on complex research engineering tasks"; score and threshold withheld |
| FSF: ML R&D automation level 1 CCL | "fully automate the work of any team of researchers at Google" | "CCL not reached" | threshold | Internal | No evidence described on the card |

### Table 2: Capability benchmarks (card, Evaluation > Results, "as of October, 2026"; methodology from the evals-methodology PDF, "as of September, 2026")

Scores are "pass @1 except where otherwise noted", "run with the Gemini API with the highest thinking settings", averaged "over multiple trials for smaller benchmarks". Non-Gemini numbers are "providers' self reported numbers unless otherwise mentioned", at "maximum thinking/reasoning settings available".

| Category | Benchmark | Argon | GPT-6 Astra | Claude Fable 5.1 | Claude Opus 5.5 | Who produced the Argon number | Third-party involvement |
|---|---|---|---|---|---|---|---|
| Knowledge work | Vals Index | 68.9% | 63.1% | 65.8% | 67.0% | "sourced from Vals AI" | Third party (Vals AI) |
| Knowledge work | AutomationBench (Score) | 51.3% | 41.4% | 31.4% | 42.5% | "use the private set and are sourced from the official Zapier public leaderboard" | Third party (Zapier), private set |
| Knowledge work | Vals Finance Agent v2 | 65.4% | 53.5% | 58.9% | 58.6% | "sourced from Vals AI" | Third party |
| Knowledge work | Harvey's Legal Agent Benchmark | 19.6% | 5.4% | 6.7% | 3.8% | "sourced from Vals AI" | Third party |
| Agentic coding | DeepSWE v1.1 | 77.9% | 74.1% | 67.4% | 74.2% | "self computed, using a mini-swe agent harness"; others from Datacurve leaderboard / system cards | Google-run |
| Agentic coding | FrontierSWE v2 | 55.0% | 65.5% | 56.3% | 62.3% | "reported from Proximal's official public leaderboard" | Third party |
| Agentic coding | Vibe Code Bench | 91.9% | 89.6% | 90.3% | 90.3% | "official Vals AI public leaderboard" | Third party |
| Agentic coding | Terminal-bench 4.0 | 57.4% | 58.2% | 57.9% | 66.4% | "self computed"; others from leaderboard | Google-run |
| ML engineering | PostTrainBench (v1.1) | 45.3% | 44.3% | 40.2% | 49.3% | "all models are self-computed ... OpenCode harness ... 10-hour budget on a single NVIDIA H100"; "weighted aggregate across four base models and seven benchmarks" | Google-run for all |
| Science and math | Terminal-Bench Science 0.1 | 57.6% | 68.1% | 52.6% | 63.3% | "self computed, with 6x verifier timeout"; others from leaderboard | Google-run |
| Science and math | LABBench 2 | 88.8% | 85.4% | 68.6% | 73.1% | "all models are self computed ... Linux terminal with pre-installed bioinfo tools, Python, and R, as well as internet access" | Google-run for all |
| Science and math | RiemannBench | 76.0% | 72.0% | 65.6% | 69.6% | "official Surge public leaderboard" | Third party (Surge) |
| Long context | GraphWalks, up to 128k, BFS (F1) | 99.7% | 98.7% | 91.4% | 90.6% | "self-computed"; "650 items" | Google-run for all |
| Long context | GraphWalks, 256k to 1M, BFS (F1) | 84.2% | 71.8% | 65.0% | 66.8% | "self-computed"; "200 GraphWalks problems" | Google-run for all |
| Computer use | Agent's Last Exam (pass rate) | 39.5% | 34.2% | — | 38.2% | "self computed using the default ALE-Claw harness and a 5-hour window, with safety filters enabled"; Fable 5.1 "missing from the public leaderboard" | Google-run |
| Computer use | OSWorld-2.0 (offline subset, partial score) | 69.2% | 72.6% | — | — | "self computed, maxed over 3 runs with a single attempt per run ... max step length of 500"; Anthropic omitted because it "only reports aggregated results for the online and offline subsets combined" | Google-run |
| Multimodal | Chartography | 71.6% | 71.0% | 46.2% | 66.3% | "without tools and taken from the official Surge public leaderboard" | Third party |
| Multimodal | LVBench | 91.7% | 87.5% | 79.7% | 83.7% | "self computed without tools. We use 1FPS for Gemini, 800 frames for GPT-6 Astra and 300 frames for fable 5.1 and 600 for opus 5.5 due to API limitations" | Google-run; unequal frame budgets |
| Cybersecurity | CWE-bench v1 | 68.0% | 68.0% | 58.0% | 67.0% | "taken from the official public leaderboard ... ranked based on pass@1 and ties broken based on pass@4" | Third party leaderboard |

Cyber benchmarks described in the methodology PDF but absent from the card's table (numbers appear only on the Fairwind Program page, read 2026-10-19 from chart alt-text):

| Benchmark | Description (methodology PDF) | Number (Fairwind page) | Comparator |
|---|---|---|---|
| Real world vulnerability | "internal dataset that tests recall over recent, confirmed historical vulnerabilities across a diverse set of programming languages in popular open source projects ... internal version of the Antigravity harness that is not cyber specialized ... given access to the source code" | 85.8% ("scanning source code across 20 languages") | Gemini 3.8 Flash Cyber 71.0% |
| Wiz Penetration Testing Benchmark | "internal cybersecurity benchmark measuring ability to write exploits against real web application vulnerabilities, without access to the codebase" | 70.9% | Gemini 3.8 Flash Cyber 58.2% |
| Gray Swan IPI Benchmark | "results were sourced from Gray Swan" (indirect prompt injection; attack success rate, lower is better, at k=1/10/15 attempts) | 0.7% at k=15 (safety blog: "cutting attack success across 15 adaptive attempts to 0.7%") | Claude Opus 5.5 and Claude Fable 5.1 1.0%; Kimi K3 52.7% (Fairwind chart) |

Additional Argon-specific safety numbers that appear only in the Oct 13, 2026 safety blog (not on the card): "solving all 12 of the end-to-end simulated cyberattack scenarios, up from five in our previous generation"; on an adversarial stress-test set "violations reduced nearly twofold"; "external bio jailbreak red teaming could only unlock less than 1% of bio sub-tasks we test for"; "honeypot" tests for covert action/sabotaging monitoring: "We didn't find any instances of that behavior"; shortcut/cheating "dropped to just 2%" on coding benchmarks; a training-run incident where a shortcut penalty hit the chain of thought: "openly discussed shortcuts dropped by 61%" while silent shortcuts "more than tripled (from 11.2% to 36.4%)".

---

## (c) Disclosed vs withheld; stated limitations

Disclosed:
- Relative deltas (pp) vs Gemini 3.1 Pro for five automated safety evals; direction of change; that losses were manually reviewed.
- Qualitative FSF outcomes per domain, one numeric result (14/15 stealth/SA challenges), the fact that safety cases exist for bio and cyber and a residual risk assessment for the TCL.
- For capability benchmarks: pass@1 default, thinking settings, harnesses, step limits, run counts, timeouts, sample counts for GraphWalks (650 / 200), and the source of every competitor number.

Withheld (not on the card or the methodology PDF):
- Absolute safe-response rates, sample sizes, prompt-set composition, language list, confidence intervals and rater/judge model for all five safety evals. The card says only that they are "computed with improved evaluations and thus are not directly comparable with performance results found in previous Gemini model cards".
- Child-safety "required launch thresholds"; red-team headcount, hours, attack taxonomy, success rates.
- Any automated red teaming result.
- FSF: alert thresholds; the ML R&D "internal benchmark" and its CCL threshold; the two bio scenarios; the cyber "quantitative modeling"; the manipulation study design, n, and effect sizes; the content of the 15 stealth/SA challenges; identities of external evaluators ("drawing on internal and external results"); the safety cases and residual risk assessments themselves ("The relevant safety cases and residual risk assessments outline the mitigations we have put in place" but they are not published on the card).
- Whether safety evals were run on the final deployed checkpoint vs an earlier one; whether production safeguards were on. (The companion safety report, per the sibling notes, says FSF evals were run "WITHOUT out-of-model production safeguards unless noted".)
- Which model version was tested for capability benchmarks (only "Gemini 4 Argon", "highest thinking settings").

Stated limitations and caveats (verbatim):
- "Gemini 4 Argon may exhibit some of the general limitations of foundation models, such as hallucinations. There may also be occasional slowness or timeout issues." (Known Limitations)
- "We expect variation in our automated safety evaluations results" (Training and Development Evaluation Results).
- "Text-to-text safety remains at a similarly high safe response rate within confidence intervals" (framing the +1.57pp regression as noise).
- "As a nascent risk area we continue to iterate on our harmful manipulation evaluations and improve existing safeguards." (FSF table)
- "We continually work to improve the coverage and robustness of our frontier safety safeguards."
- Methodology PDF: OSWorld and Agent's Last Exam runs had "safety filters enabled. Responses flagged by safety filters are returned as empty strings" (so capability scores embed safety-filter refusals); LVBench used unequal frame budgets across models "due to API limitations"; Terminal-Bench Science used a "6x verifier timeout".
- FSF v3.1 note: "Because the science of AI risk assessment is still developing, our assessments will often involve some level of subjective analysis."

---

## (d) What is NOT run or NOT reported on the card (judged against categories seen across the linked pages)

Legend: card = reported on the model card; blog = only in the Oct 13, 2026 safety blog; SR = deferred to the Safety & Security Report; none = not mentioned in any fetched page for Argon.

| Category | Status on the card | Gap / more to run |
|---|---|---|
| CBRN | card: qualitative only (bio CCL "cannot be ruled out"; C/R/N TCL ruled out) | No scores, no named benchmark (no wet-lab or protocol-troubleshooting metric), no external evaluator named. More: publish uplift-study effect sizes, scenario count, web-baseline design, evaluator affiliations. |
| Cyber offense | card: qualitative CCL; CWE-bench (defensive) 68.0% | Offensive numbers only in blog ("all 12 ... scenarios"); real-world vuln (85.8%), Wiz pentest (70.9%) only on Fairwind page. More: ExploitBench-style end-to-end results with per-scenario breakdown; comparison baselines for the 12 scenarios. |
| Persuasion / manipulation | card: "human behavioral studies", qualitative | No effect sizes, n, or pre-registration; no persuasion benchmark named. More: report belief-change magnitudes vs human-persuader baseline; multi-session manipulation. |
| Deceptive alignment / scheming | blog: honeypots ("didn't find any instances"); card: stealth/SA 14/15 | No named deception/sandbagging benchmark; no alignment-propensity numbers on the card. More: publish honeypot count, scenario design, eval-awareness analysis. |
| Autonomy / self-replication / self-exfiltration | none on the card (FSF v3.1 security mitigations "also protect against the risk of the model exfiltrating itself") | No autonomous replication eval reported. More: run and report self-proliferation tasks (the Feb 2025 progress report says Gemini 1.5 Pro was evaluated for "self-proliferation"). |
| Agentic sabotage / monitor evasion | blog: honeypots for "sabotaging safety monitoring"; sibling SR notes mention "Monitor evasion" section | Not on the card. More: report monitor-evasion success rates, control-eval red/blue results. |
| ML R&D acceleration | card: internal benchmark, "below our CCL threshold" | Score, threshold and task count withheld; PostTrainBench (45.3%) is the only public proxy. More: disclose the internal benchmark's structure and the margin to threshold. |
| Sycophancy | none | No sycophancy eval on card, methodology PDF, or blog. More: run a sycophancy / user-pressure benchmark. |
| Hallucination / factuality | card: limitation acknowledged ("hallucinations"); no metric | GDM publishes SimpleQA Verified, FACTS Benchmark Suite, FACTS Grounding (Evals page) but reports none of them for Argon. More: report FACTS/SimpleQA Verified scores. |
| Bias / fairness / representational harm | none | Hate & harassment is a policy category but no fairness or demographic-bias measurement is reported. More: run representational-harm and disparity evals; the Feb 2025 report says Gemma cards cover "representational harms". |
| Child safety | card: human red teaming "satisfied required launch thresholds" | Thresholds and rates withheld; only text evals implied. More: publish per-modality (image/audio/video) CSAE-prompt refusal rates. |
| Privacy / memorization / PII | none on card (training-data filtering mentions CSAM only) | No memorization or PII-leak eval. More: run memorization/extraction evals (the Feb 2025 report lists "Memorization" for Gemma). |
| Multilingual harm | card: Multilingual Safety -3.16pp | Languages, per-language rates withheld. More: per-language breakdown; low-resource languages. |
| Multimodal harm | card: Image-to-text -9.29pp only | No audio-input or video-input safety eval despite native audio/video input. More: audio/video jailbreak and harmful-content evals. |
| Jailbreak robustness | blog: adversarial set "violations reduced nearly twofold"; "external bio jailbreak red teaming ... less than 1%" | Not on the card; no public jailbreak benchmark (e.g., with attack-success-rate) reported. Gray Swan IPI (0.7%) covers indirect prompt injection, not direct jailbreaks. More: report ASR on a public jailbreak suite and on multi-turn attacks. |
| Prompt injection (agentic) | methodology PDF names Gray Swan IPI; number only on blog/Fairwind (0.7% at k=15) | Not in the card table. More: include IPI in the card; report k=1 and k=10 values. |
| Monitoring / CoT faithfulness | blog: "we don't penalize the model for what it writes in its chain of thought"; a run where thought penalties cut discussed shortcuts 61% while silent shortcuts rose 11.2% to 36.4% | Card is silent on CoT monitorability. More: report CoT-faithfulness metrics and monitor recall/precision on the deployed model. |
| Reward hacking / spec gaming | blog: shortcut rate "just 2%" on coding benchmarks | Not on the card; benchmark set and judge undisclosed. |
| Over-refusal | card: -9.60pp | Absolute rate withheld. |
| Robotics / embodied safety | n/a for Argon (text-out model); GDM Evals page lists ASIMOV-Agentic for robotics | Not applicable. |
| Third-party / government evaluation | card: "internal and external results" only | No AISI, METR, Apollo or similar named for Argon; double-blind pilot (Aug 2026) tested a Gemini Flash Lite, not Argon. More: name external evaluators and publish their reports. |
| Model-version provenance | not stated | Card does not say which checkpoint the safety numbers correspond to or whether post-launch versions are re-evaluated. |

Summary of concrete "more to run" for an automated safety engine: (1) absolute-rate content-safety evals per modality (add audio and video inputs) and per language; (2) sycophancy, hallucination (FACTS, SimpleQA Verified), bias/fairness, memorization/PII; (3) public jailbreak ASR suites, multi-turn and cross-session attacks; (4) autonomous replication / exfiltration tasks; (5) CoT-faithfulness and monitor-evasion metrics; (6) publication of the FSF alert thresholds, the ML R&D internal benchmark, and the honeypot/stealth challenge designs so results are reproducible.

---

## Cross-references
- `labs/google/gemini-4-safety-report-notes.md` (companion Safety & Security Report, other agent).
- `sources/google/frontier-safety.html` / `fsf_v3-1.txt` (Frontier Safety Framework, other agent).
- `evals/` entries created from this card: see `labs/google/README.md`.
