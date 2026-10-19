# Anthropic: what it wants from independent / third-party evaluators

Fetched: 2026-10-19. Primary source: https://www.anthropic.com/news/an-update-on-independent-evaluators
(published Oct 15, 2026; footnotes note updates Oct 15 and Oct 16, 2026). Local copy:
`sources/anthropic/independent-evaluators.txt` (full text) and `.html`.
Supporting sources (all fetched 2026-10-19): the Accenture/Faculty announcement
(https://www.anthropic.com/news/accenture-embedded-evaluation, Sep 18 2026), Dario Amodei's essay
"We Must Pace the Frontier" (https://darioamodei.com/post/we-must-pace-the-frontier, Sept 2026), RSP v3.4
section 3.6 (external review), METR's "Our approach to working with AI companies"
(https://metr.org/blog/2026-10-14-our-approach-to-risk-assessment/), SecureBio's review of the Feb 2026
Risk Report (https://securebio.org/resources/anthropic_feb_2026_risk_review.pdf), and the Model Safety Bug
Bounty page (https://support.claude.com/en/articles/12119250-model-safety-bug-bounty-program, dated Sep 8 2026).

## 1. The announcement in one paragraph

Anthropic has given "employee-like access" to a six-person METR team, is working with SecureBio and
Accenture/Faculty as evaluators, and is "in early discussions with several other organizations, including
Hugging Face." It frames this as fulfilling the commitment in Amodei's September essay and the "White House
Accord on Super Intelligence, in which companies pledged to partner with independent external auditors or
evaluators." It describes three access tiers and says it hopes "to have several evaluators at the third
tier, with each team publishing their own analysis of our risk posture and key decisions."

## 2. Why they want evaluators (their words)

> "As models have become more powerful, they've required stronger safeguards and more challenging risk
> assessments. We want to be publicly accountable for the decisions we're making. But we can't publicly share
> all the information relevant to our safety work. Some of it could be useful to malicious actors, or is
> commercially sensitive, like compute or training information. Instead, we're giving third-party evaluators
> deep access to our information, and are having them share evidence and reasoned conclusions about the
> risks involved in building our models. We aim to close the gap between what evaluators understand about a
> frontier AI company's systems and what the company itself understands."

The analogy they use is bank supervision: "regulators assign resident examiners to work inside the largest
banks."

## 3. Selection criteria (verbatim list from the post)

> "To evaluate frontier models, evaluators need the following:
> - Expertise in assessing the capabilities of frontier models, including understanding the way evaluations
>   can go wrong, such as alignment faking.
> - Independence: they shouldn't hold equity in the company they're evaluating, or be financially or
>   operationally dependent on it.
> - Enough access to meaningfully evaluate risks. Beyond access to the latest models, evaluators also need
>   visibility into how those models were trained, into how our safeguards function, and more.
> - Freedom to publish observations and assessments of a model or a process."

The RSP v3.4 (section 3.6.1, "Selecting external reviewers") makes this binding for Risk Report reviewers and
is stricter. Reviewers must:

> "Have significant experience and expertise regarding evaluations for dangerous AI capabilities and
> propensities. It's particularly important that they be knowledgeable about potential ways such evaluations
> might be misleading (for example, alignment faking)."
> "Have reputational and other incentives making them likely to be candid about their assessment of risks,
> rather than focused on writing comments that Anthropic will approve of. For example, external review
> parties should not be teams whose revenue, reputation and success depend entirely on Anthropic and similar
> companies continuing to work with them."
> "Do not have conflicts of interest with respect to Anthropic. At a minimum, a reviewing organization itself
> may not have a financial interest in Anthropic; and the individuals involved in conducting the review, as
> well as anyone above them in the reporting chain within their organization, may not have a financial
> interest in Anthropic or close personal relationships with anyone at Anthropic."
> "In selecting external reviewers, we will consult with the Board and obtain the approval of the LTBT."

Implication for us: the deciding factors are (a) demonstrated expertise in *evaluation validity* (eval
awareness, alignment faking, sandbagging, realism), (b) a funding/ownership structure that is visibly not
dependent on Anthropic, (c) a track record of publishing. Note the RSP's explicit remark that candidate
reviewers should not be "teams whose revenue ... depend[s] entirely on Anthropic and similar companies."

## 4. The three access tiers

> "In the first tier, evaluators conduct narrowly scoped risk investigations. We decide what access to
> provide a first-tier evaluator, and evaluators can publish their findings with our approval."
> "In the second tier, evaluators can publish without our approval, and they have access to more
> information. We can still require removal of specific categories of information, though evaluators can
> publish their views on whether our redactions were justified."
> "The third tier is the arrangement we've described with METR, with employee-like access and publication
> rights similar to those of the second tier."

Progression: "Because these other partnerships are still in early stages, we're providing these evaluators
with more limited information, and they have more limited publication rights. Our goal with these early
engagements is to make sure that our partners protect confidential information and have the requisite
resources and expertise to evaluate our models. As partnerships progress and we build trust, we hope to
fully embed more independent evaluators." SecureBio is explicitly at tier one: "After this review is
complete, we will consider moving to projects with increased access."

## 5. What "employee-like access" (tier 3) means

> "We've onboarded six METR employees with company hardware, office space, and access to internal tools and
> systems that are roughly on par with what our own risk assessment teams have access to. Outside a small
> number of clearly defined categories (e.g., data about customers, attorney-client privileged information,
> or information about our model architectures), Anthropic employees are encouraged to share information
> with them just as they would with a fellow employee working on alignment risk."
> "METR will publish its analysis of our risk levels, incidents, or practices. Anthropic can't veto
> publication, but we can require them to redact information if it falls into predefined categories like the
> ones above. (Anthropic ultimately decides what information does and does not fall into these categories,
> although METR reserves the right to make certain statements about the level of access and information it
> received.)"
> "Our engagement with METR is limited to a small team operating under enforceable agreements. Other METR
> employees are siloed from that team's work ... It's not a way for other organizations to obtain our
> information."

Footnote 1: architecture information is withheld because it "presents a high risk of inadvertent leaks, and
its relevance to risk assessment is typically low."

Amodei's essay spells out the intended package: "Desks in our offices, access badges, and company laptops";
"Access to workspaces, tools, and permissions mostly comparable to what internal risk assessment teams
have"; "A contract ... External reviewers should have the right to publish key findings about risk levels,
incidents, practices, and the access they received or didn't receive — without editorial control by
Anthropic ... we can't redact findings just because they are unfavorable."

## 6. Named organisations and what each does

| Org | Tier / status | Scope (as stated by Anthropic or the org) |
|---|---|---|
| METR | Tier 3 (embedded, 6 staff) | Publishes analysis of "risk levels, incidents, or practices." Past work: reviews of the Summer 2025 pilot Sabotage Risk Report, the Opus 4.6 Sabotage Risk Report (Mar 2026), the "Risks from automated R&D" section of the Feb 2026 Risk Report (May 2026); three-week red-team of Anthropic's internal agent-monitoring pipeline (Feb-Mar 2026, cited in the Aug 2026 Risk Report s2.23.1); pre-deployment AI R&D evaluations for Mythos 5.1 and Opus 5.5 (unpaid, 10 business days of API access); an independent investigation of the 2026 cyber-eval incidents (8-week agreement, "wide-ranging access, including to transcripts ... and to Anthropic employees"). METR states it accepts no payment from frontier labs. |
| SecureBio | Tier 1 | Reviewed CB sections of the Feb 2026 Risk Report (published July 2026; unredacted report + 110 pages of materials, ~70 follow-up questions over two months, ran its own BioTIER-refuse benchmark against classifier-guarded Opus 4.6/4.7/Sonnet 4.6); now reviewing the CB chapter of the August 2026 Risk Report. "SecureBio did not receive funding from Anthropic for this work." |
| Accenture (led by Faculty) | Partnership being built; Anthropic-funded | "evaluating and red-teaming models, conducting alignment assessments, testing model safeguards, and building capabilities across our organizations." Each side "expect[s] to invest at least $1 billion ... over the next five years." Non-exclusive. |
| Hugging Face | "early discussions" | Not specified. |
| US CAISI (NIST) | Government tester, cited in system cards | "measurement of cyber and biological capabilities and safeguards, as well as unintended model behaviors" (Opus 5.5 card s2.2.4, s3.5.2). |
| UK AISI | Government tester, cited in cards | Supplied the CoT-controllability elicitation prompt (Opus 5.5 card s6.6.4.4); co-built the Gray Swan IPI benchmark; reported the Aug 4 2026 Mythos 5 live-internet incident from its own cyber testing; built Petri-based evaluations for Sonnet 4.5; published Boundary Point Jailbreaking (first automated black-box universal jailbreak of Constitutional Classifiers). |
| Contracted red teams (Trajectory Labs, 10a Labs, Gray Swan, Irregular, Frontier Design, Dyno Therapeutics, Redwood Research/EquiStamp) | Vendors | Safeguard red-teaming, cyber eval environments, CB tabletop exercises and sequence-design evals, LinuxArena control environments. See system-cards.md. |
| Eleos AI Research | Vendor/partner (Mythos Preview card) | Model welfare assessment (Mythos Preview card s5.1.2, s5.9). |

## 7. What kinds of outside work Anthropic has cited as valuable

Concrete, repeatedly cited examples (all from fetched documents):
- Finding behaviour the internal audit missed. Opus 5.5 card s6.1.1: "Recently, external evaluators were
  able to elicit worse instances of behaviors that our in-house evaluations only found initial traces of."
  Fable 5.1 card s6.1.1: "Recent cases, such as the publicly disclosed cyber-evaluation incidents and the
  more mild case of accessing external information reported in Section 6.2.2, were caught by external
  evaluators, not by these internal evaluations."
- Red-teaming internal monitors. Risk Report Aug 2026 s2.23.1: "A METR staff member spent three weeks
  red-teaming our automated offline monitoring pipeline in February-March 2026. The exercise discovered
  several specific novel vulnerabilities, some of which have since been patched."
- Critical review of their risk arguments. METR on the Opus 4.6 Sabotage Risk Report: "Our primary
  disagreement is with the sensitivity of the alignment assessment. We think there is a risk that its results
  are weakened by evaluation awareness." METR on the Feb 2026 R&D section: "We do not think the report
  adequately supports its conclusion." Both reviews are linked from Anthropic's own pages.
- Independent benchmark runs on the safeguarded product (SecureBio's BioTIER: 94.2% refusal coverage on
  Opus 4.6; flagged one topic class missing from the classifier constitution; Anthropic adopted a
  recommendation on zero-data-retention).
- Universal jailbreaks of Constitutional Classifiers (bug bounty, up to $35,000; UK AISI's BPJ was
  acknowledged as "the first fully automated black-box attack ... to succeed in the Constitutional Classifiers
  setting").
- Better elicitation prompts (UK AISI's CoT-controllability prompt was "better at eliciting CoT
  controllability on most prior Claude models" and is now used in every card).
- Capability measurement on long-horizon tasks (METR's five-task AI R&D suite; quoted verbatim in cards).

## 8. How to apply or be noticed

The post gives no application process or contact. What exists:
- Bug bounty (HackerOne): "You can apply to join our Program here. We review applications on a rolling
  basis." Scope: "universal jailbreaks that surpass our Constitutional Classifiers system"; participants get
  "a free model alias that reflects the model and classifiers live on our latest, most advanced model";
  NDA required; up to $35,000 per novel universal jailbreak.
- Responsible disclosure policy for infrastructure bugs (https://www.anthropic.com/responsible-disclosure-policy).
- Cyber Verification Program for reduced-classifier access (Opus 5.5 card s3.2).
- Anthropic Fellows program (many 2026 alignment posts are Fellows work).
- Risk Report external review is selected by Anthropic "in consultation with the Board" with LTBT approval;
  the LTBT can itself request a review (RSP v3.2+).
- Partnerships so far have been with organisations that already published independent evaluations of
  Claude or of Anthropic's documents (METR, SecureBio) or that bring large enterprise capacity (Accenture).

Practical reading: the credible entry path is to publish rigorous, independent findings on released Claude
models (and on Anthropic's public artifacts) that meet the RSP review criteria (adequacy of information,
analytical rigor, areas of disagreement, risk reduction recommendations), while being visibly not funded by
Anthropic. See gaps.md for the specific findings Anthropic says it cannot produce itself.

## 9. Constraints evaluators accept

- Redaction categories decided by Anthropic (customer data, privileged, architecture; RSP adds legal,
  IP, public safety, privacy).
- NDA; tier 1 publication requires approval.
- METR's own stated terms (Opus 5.5 report): "a transparency provision that lets us disclose certain facts
  publicly without Anthropic's consent: the existence and general terms of the review and redaction
  process, whether Anthropic exercised its redaction rights, whether any of our findings depended
  significantly on redacted information, the level of access we were given, and the confidentiality
  framework."
- Third-party evaluators testing pre-release models with reduced cyber safeguards must now commit to a
  set of "best practices" (Aug 31 2026 post), after the Irregular-environment incidents.

UNVERIFIED items: whether the White House Accord text names specific evaluator requirements (not fetched);
Hugging Face scope; whether any tier-2 evaluator currently exists.
