# Lab-side statements on third-party testing (what labs say they want from evaluators)

Fetched: 2026-10-19. Raw copies in `/data/haokun_test/neurico/safety_kb/sources/lab-statements-on-third-party-testing/`.
This file is the lab/policy side of the picture; per-evaluator files in this directory are the evaluator side.
All quotes are verbatim from the fetched text unless marked paraphrase.

## 1. Anthropic

### 1.1 "Third-party testing as a key ingredient of AI policy" (2024-03-25)
URL: https://www.anthropic.com/news/third-party-testing
- Argues for "a diverse ecosystem of different organizations" (companies, universities, governments) running "broadly-trusted" tests on "a narrow set of the most computationally-intensive, large-scale systems".
- Two-stage regime: "a very fast, automated testing stage" "biased towards avoiding false negatives", then a deeper stage "likely using expert human-led elicitation".
- National-security capabilities: "some testing and evaluation questions relate to national security capabilities which are classified" so "only certain governments are able to effectively evaluate them".
- Disclosure: "We will also need to experiment with disclosure processes, similar to how the security community has developed norms around pre-notification of disclosures of zero days".
- Not covered: evaluator accreditation, information security for testers (absent from the text).

### 1.2 "A new initiative for developing third-party model evaluations" (2024-07-01)
URL: https://www.anthropic.com/news/a-new-initiative-for-developing-third-party-model-evaluations
Ten stated "principles of good evaluations" (paraphrased headings; full list in raw copy):
1. Sufficiently difficult (relevant to ASL-3/ASL-4 or human-expert-level behaviour).
2. Not in the training data.
3. Efficient, scalable, ready-to-use (automated).
4. High volume where possible (1,000-10,000 items preferred over 100).
5. Domain expertise (SMEs develop or review).
6. Diversity of formats (task-based, model-graded, human-trial, not only multiple choice).
7. Expert baselines (compare with human experts).
8. Good documentation and reproducibility ("ideally using the Inspect or METR standard").
9. Start small, iterate, scale (1-5 items first, read transcripts).
10. Realistic, safety-relevant threat modelling (a high score should convince experts a major incident could result).
Priority domains: ASL assessments (cyber, CBRN, model autonomy incl. "AI R&D proficiency" and "self-replication"), national-security early warning, social manipulation, misalignment (deception, sabotage, exfiltration); advanced science; harmfulness/refusal classifiers; multilingual; societal impacts; infrastructure (no-code eval platforms, model-graded evals, uplift trials).

### 1.3 Dario Amodei, "We Must Pace the Frontier" (September 2026)
URL: https://darioamodei.com/post/we-must-pace-the-frontier (raw: amodei-we-must-pace-the-frontier-2026-09.txt)
- Proposes embedded third-party evaluators "(such as METR)" with "Desks in our offices, access badges, and company laptops", access "mostly comparable" to internal risk-assessment teams, with exceptions required by law, contract, or customer/partner confidentiality.
- Evaluators should verify adherence to "training, deployment, operational, and safeguards practices", incident reporting, and the alignment of completed models and of training pipelines.
- Publication "without editorial control by Anthropic"; Anthropic may redact security-sensitive, legally privileged, commercially sensitive or third-party-confidential information but "can't redact findings just because they are unfavorable"; reviewers may say publicly if a redaction removed something material.
- Calls for "all frontier labs" to "partner with government to formalize the idea of permanent embedded evaluators". Does not address evaluator qualifications or funding.

### 1.4 "Anthropic's first embedded evaluator is Accenture" (2026-09-18)
URL: https://www.anthropic.com/news/accenture-embedded-evaluation
- Scope: "evaluating and red-teaming models, conducting alignment assessments, and testing model safeguards"; led by Faculty (Accenture's AI unit). Anthropic and Accenture "each expect to invest at least $1 billion over the next five years"; Anthropic "will also fund Accenture's work directly".
- Access "comparable to an employee's".
- Admits "no standards yet exist for what information evaluators can access or how they report findings", nor a settled funding model; long-run view that funding should come from "pooled or government sources". Non-exclusive; METR and other nonprofits to pilot "using their own funding".

### 1.5 "An update on independent evaluators" (2026-10-15)
URL: https://www.anthropic.com/news/an-update-on-independent-evaluators
- Four stated requirements for an evaluator: expertise, independence, sufficient access, and freedom to publish. Independence defined as not holding equity in the company and not being financially or operationally dependent on it.
- Three access tiers (paraphrase): Tier 1 narrowly scoped risk investigations, Anthropic decides access and publication needs approval; Tier 2 more information, publication without approval but redaction of predefined categories (evaluator may say whether redactions were justified); Tier 3 employee-like access with Tier-2 publication rights (the METR arrangement).
- METR: six staff with company hardware, office space, internal tools "roughly on par" with Anthropic's own risk-assessment teams; employees encouraged to share information except customer data, attorney-client privileged material, and model-architecture information (the last "a high leak risk", shared only with explicit approval). Engagement limited to a small team under "enforceable agreements"; other METR staff siloed; team works under Anthropic's security standards. Anthropic cannot veto publication.
- SecureBio reviews the chem/bio chapter of the August 2026 Risk Report (after a pilot review of an earlier report). Accenture/Faculty: evaluation, red-teaming, alignment assessment, safeguard testing. Hugging Face and others: early discussions.
- Explicitly says evaluators who also work with other companies are a leak risk, which the arrangement must manage.

## 2. OpenAI

### 2.1 "OpenAI's Approach to External Red Teaming for AI Models and Systems" (white paper, Ahmad, Agarwal, Lampe, Mishkin; Nov 2024)
URL: https://cdn.openai.com/papers/openais-approach-to-external-red-teaming.pdf (raw: openai-external-red-teaming.txt)
- Four goals of external red teaming: "Discovery of novel risks", "Stress testing mitigations", "Augmenting risk assessment with domain expertise", "Independent assessment" ("strengthens trust in the results by reducing real or perceived conflicts of interest").
- Four campaign design steps: cohort composition (driven by threat modelling and "motivating questions ... risks of what, to whom, posed by whom or what?"), model/system versions to expose, interfaces/instructions/documentation, synthesis into evaluations.
- Table 2 lists access types and trade-offs: pre-deployment snapshots without mitigations; with partial mitigations; with model+system mitigations; post-deployment. Red teamers may be "individuals who have expertise in adversarial testing or relevant domain knowledge", "academic groups", "organizations that specialize in red teaming services", or "public arenas for bounty prizes".
- Documentation expected from red teamers: prompt/generation pairs, category, risk level on a scale, heuristics for the rating.
- Limitations section (p.10+ in raw text): red teaming is point-in-time, depends on tester skill, and does not substitute for evaluations.

### 2.2 "Strengthening our safety ecosystem with external testing" (2025-11-19)
URL: https://openai.com/index/strengthening-safety-with-external-testing/ (fetched via web.archive.org; openai.com returned 403)
- Three forms of third-party collaboration: "Independent evaluations", "Methodology reviews", "Subject-matter expert (SME) probing".
- GPT-5: external assessments on "long horizon autonomy, scheming, deception and oversight subversion, wet lab planning feasibility, and offensive cybersecurity"; named benchmarks "METR's time horizon evaluation" and "SecureBio's Virology Capabilities Test (VCT)".
- Access provided: "secure access to early model checkpoints, select evaluation results ..., zero-data retention where needed, and models with fewer mitigations"; some organizations "received direct chain-of-thought access" to detect "sandbagging or scheming behavior".
- Methodology review example: gpt-oss adversarial fine-tuning; "we invited third party assessors to review and make recommendations on our internal methods and results rather than repeat similar work" because worst-case fine-tuning "requires infrastructure and technical expertise that is not commonly available outside of major AI labs".
- Principles: "Transparency with careful confidentiality bounds" (NDAs; "we review and approve publications from third-party assessments to ensure both confidentiality and factual accuracy"; published examples: METR GPT-5 report, Apollo report on o1, Irregular GPT-5 Assessment); "Thoughtful information disclosure and secure, sensitive access"; "Balanced financial incentives" ("we offer compensation to all of our third party assessors ... No payment is ever contingent on the results").
- Appendix reproduces contract language: publication rights "submitted to OpenAI for review and approval in writing prior to any publication"; confidentiality for 2 years except trade secrets; outputs of Non-Public Models are Confidential Information.
- "Effective third party evaluation requires specialized expertise, stable funding, and methodological rigor."

### 2.3 "Priorities and principles for effective third party assessments" (Lama Ahmad, 2026-09-22)
URL: https://openai.com/index/priorities-principles-third-party-assessments/ (fetched via web.archive.org)
- Commitment to "independent assessments with deep levels of access across training, evaluation, and deployment"; says it has provided "visible chain of thought access, and unprecedented levels of confidential data and internal deployment access for incident response and monitor red teaming".
- Defines "Safety claim" and "Safety case" (verbatim in raw copy).
- Four priority areas: (1) independent assessment of safety cases across training, evaluation, internal and external deployment; (2) assessment of critical safeguards ("grey box" jailbreak/uplift testing; agents vs cyber defences; misalignment monitors; chain-of-thought monitoring reliability; monitoring "that cannot easily be disabled"); (3) assessment of Preparedness capability evaluations (chem/bio, cyber, AI self-improvement) and alignment evaluations (threshold setting, refresh when saturated); (4) independent investigation of critical misalignment incidents (cites "the OpenAI Hugging Face incident"; investigators need "cyber forensics expertise, alignment expertise, large-scale chain of thought analysis, and the staff and resources ... in a timely manner").
- Seven principles (verbatim headings): "Clearly scoped and mutually agreed upon claims for assessment" (pre-registered claims; state whose claims); "Proportionate access"; "Transparent methodology and standards" ("Reports should distinguish direct findings from interpretation"); "Expertise and independence" (disclose "financial incentives, relationships with developers, and prior involvement"; "recusal or appropriate exclusion periods"); "Security and confidentiality" ("enforceable confidentiality protections covering their personnel"; otherwise "access on company-managed devices or premises"); "Actionable findings and time to remediate"; "Responsible publication practices" (editorial independence, redaction policies, assessors "can note where substantive redactions have been made").
- "No one third party can or should comprehensively cover urgent frontier safety questions."

## 3. Frontier Model Forum (Anthropic, Google, Microsoft, OpenAI, Amazon, Meta)

### 3.1 Issue brief "Early Best Practices for Frontier AI Safety Evaluations" (2024-07-31)
URL: https://www.frontiermodelforum.org/updates/early-best-practices-for-frontier-ai-safety-evaluations/
Six practices: draw on domain expertise; evaluate systems as well as models; consider marginal vs absolute risk; account for prompt sensitivity ("incorporate multiple kinds of prompts for a given task"); evaluate against intended use and adversarial exploitation; nuanced transparency ("provide transparency into a subset of prompts and/or data while keeping another subset hidden").

### 3.2 Technical report "Third-Party Assessments" (2025-08-04)
URL: https://www.frontiermodelforum.org/technical-reports/third-party-assessments/
- Three functions: Confirmation (replication testing, methodology review, holistic review), Robustness (open-ended assessment, adversarial testing), Supplementation.
- Assessor qualities: replication needs "technical proficiency in AI architectures with domain expertise"; open-ended assessment needs "strong capability elicitation skills, domain-specific knowledge" and threat-modelling experience; adversarial testing needs "experience with red teaming techniques".
- Security readiness: assessors "adhere to strict data handling protocols, maintain confidentiality agreements" and must demonstrate they can handle privileged access before receiving it; access limited to "only the minimum information necessary".
- Independence: replication assessors "must maintain independence from the development process"; "Methodological independence enables assessors to approach evaluations with a fresh perspective".
- Limitations: "The third-party ecosystem for frontier models remains relatively nascent"; "accreditation frameworks" are in early development; "Experts who combine rigorous capability elicitation skills with deep domain knowledge remain scarce".
- METR and Apollo Research are named as illustrative external evaluators.

## 4. Government and policy instruments (2026)

### 4.1 White House Accord on Super Intelligence (2026-09-29)
Source: Forbes Australia reproduction of the accord text (raw: forbes-white-house-accord-on-super-intelligence-2026-09-30.txt). Primary whitehouse.gov text not located: UNVERIFIED beyond the reproduction.
- Signatories listed: Trump, Musk, Zuckerberg, Huang, Amodei, Pichai, Brockman.
- "four layers of controls and audits": internal controls monitoring capabilities and alignment "around areas like cybersecurity, biosecurity, and chemical threats"; an empowered internal team; "Partner with an independent external auditor or evaluator to carry out independent assessments of whether the controls, monitoring, and detection are operating as intended"; "an independent committee of the board of directors" to receive reports from internal and external auditors.
- Voluntary ("should" language); "Over time, it may make sense to codify these steps into laws or regulations." No requirement to publish findings.

### 4.2 California SB 813 and AB 1405 (signed 2026-09-09)
Source: Crowell & Moring client alert (secondary; bill text on leginfo not fetched).
- SB 813 creates voluntary "Independent Verification Organizations" (IVOs) designated by the Government Operations Agency; applicants must show expertise in AI risk assessment "including the metrics and methodologies"; IVOs file annual reports covering standards, governance and "funding sources relevant to independence".
- AB 1405 creates an AI auditor registry: auditors may not take an audit where a "financial, business, employment, or other interest would reasonably be expected to impair objectivity", may not audit their own prior work or assign anyone with material responsibility at the auditee in the prior 12 months; must retain reports 10 years; reports must include scope, results, remediation, limitations and a signed compliance statement. Registration mandatory from 2029-01-01 (dates vary across sources; UNVERIFIED which controls).
- Neither law requires developers to obtain an audit.

### 4.3 Evidence on the ecosystem's size and independence
- Staufer, "Who Funds Frontier AI Evaluations? A Preliminary Mapping of the Third-Party Evaluation Ecosystem", ICML 2026 Technical AI Governance workshop (https://icml.cc/virtual/2026/78581): 75 system cards, 519 evaluations mapped, 68% internal; third-party layer "thin" and partly funded by the developers it evaluates. Full paper (OpenReview eEtbT6gTMt) could not be fetched (403); numbers from the ICML abstract page.
- TechCrunch 2026-09-16 (raw: techcrunch-...txt): Apollo had three days on GPT-6 Astra; METR and Redwood had about a week on-site for the OpenAI Hugging Face incident; FAR.AI's Adam Gleave says FAR.AI "turned down contracts from developers that wanted too much control"; Meta, SpaceXAI and Google DeepMind had not committed to embedded evaluators; Hassabis proposed an industry standards body instead.
- SF Standard 2026-10-17 (raw: sfstandard-...txt): "practically no binding rules"; shared funders and staff movement between labs and evaluators; OpenAI fired three safety researchers over sharing "sensitive information" with an outside group (one said it concerned communication with METR); METR says it takes no funding from AI companies.

## 5. Google DeepMind, Meta, xAI, others
- No fetched primary statement from Google DeepMind on embedded third-party evaluators as of 2026-10-19 (web-search budget exhausted during this session; see `labs/google/` for its Frontier Safety Framework, owned by another analyst). TechCrunch (above) reports GDM had not committed and Hassabis proposed an industry standards body. UNVERIFIED beyond that report.
- Meta, xAI, Amazon, Microsoft: see `labs/meta/`, `labs/xai/`, `labs/other/` for what their frameworks say about external testing.
