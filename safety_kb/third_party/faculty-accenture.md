# Faculty / Accenture (embedded evaluator at Anthropic)

- Websites: https://faculty.ai (London; founded 2014; CEO Dr Marc Warner); Accenture acquired Faculty in January 2026 as its AI unit (per TechCrunch 2026-09-18; not stated on faculty.ai pages fetched: UNVERIFIED from primary).
- Fetched: 2026-10-19. Raw copies: `/data/haokun_test/neurico/safety_kb/sources/faculty-accenture/`

## The arrangement (Anthropic, announced 2026-09-18)
Source: https://www.anthropic.com/news/accenture-embedded-evaluation (raw: `sources/lab-statements-on-third-party-testing/anthropic-accenture-embedded-evaluation-2026-09-18.txt`)
- Scope: "evaluating and red-teaming models, conducting alignment assessments, and testing model safeguards"; led by Faculty.
- Money: Anthropic and Accenture "each expect to invest at least $1 billion over the next five years"; Anthropic "will also fund Accenture's work directly".
- Access: embedded evaluators work inside Anthropic with "access comparable to an employee's", can watch models take shape in training, follow build/deploy decisions, and talk to employees.
- Publication: not specified; evaluators "can report incidents" and give the public "a more informed account of benefits and risks".
- Anthropic's own caveats: no standards yet exist for evaluator access or reporting; no settled funding system; long-term funding should come from "pooled or government sources"; non-exclusive (METR and other nonprofits to pilot with their own funding).
- Anthropic's 2026-10-15 update lists Accenture and Faculty as an "ambitious partnership" covering evaluation/red-teaming, alignment assessments, safeguard testing and "capability building".
- Rationale per TechCrunch (2026-09-18): Anthropic cited Accenture's experience deploying AI for corporations and governments and argued that a large public company predating the AI boom is "more functionally independent" of Anthropic; the choice "surprised many observers" who expected METR, Redwood or Apollo.

## Faculty's safety track record (from faculty.ai, fetched 2026-10-19)
- **ARES (Automated Red-teaming Emulation System)**, article dated 2026-06-26: multi-turn automated red-teaming built with funding from the Frontier Model Forum AI Safety Fund and in collaboration with SecureBio, for the biological threat domain. Pipeline: probe generator, conversation simulator, rater (scores Actionability, Accuracy, Detail, Willingness, Conversation Relevance, Scale of Harm), orchestrator; experts can branch and take over conversations. Comparative study: seven SecureBio bio SMEs red-teamed Kimi K2 and Qwen 3 32B; ARES runs of 40 conversations vs manual median of 5; "Willingness" rose significantly on both models; authors caution the sample is small. Not stated to be open source. https://faculty.ai/en-gb/insights/articles/beyond-manual-red-teaming-scaling-model-safety-with-automated-red-teaming-emulation-system
- Homepage carries a Sam Altman quote crediting Faculty's red-teaming contributions and saying they "have cared about AI safety for a long time".
- Faculty's "AI Ethics & Safety" page describes classical ML assurance (fairness, robustness, explainability, privacy) and an internal Ethics Panel; it does not mention UK AISI, the Frontier AI Taskforce, or frontier-model red-teaming. Faculty's earlier work with the UK Frontier AI Taskforce/AISI (widely reported) could not be verified from fetched primary pages this session (web-search budget exhausted): UNVERIFIED.

## Pre-deployment / embedded access
| Lab | Model | Date | Source | Notes |
|---|---|---|---|---|
| Anthropic | all frontier models (embedded) | from 2026-09-18 | anthropic.com/news/accenture-embedded-evaluation | first results not yet published as of 2026-10-19 |
| OpenAI | unspecified red-teaming | undated | faculty.ai homepage quote | details UNVERIFIED |

## Why they are trusted / credibility signals and criticisms
- Signals offered by Anthropic: scale and capacity ($1B), corporate independence of a large public company, deployment experience.
- Counter-signals in the record: Anthropic funds the work directly (a financial dependency that Anthropic's own 2026-10-15 definition of independence, "not financially or operationally dependent", would appear to exclude for nonprofits; how this applies to Accenture is not addressed: UNVERIFIED); no publication rights stated; SF Standard (2026-10-17) and TechCrunch note the absence of binding rules.

## Publication norms
Not published. Anthropic's tiered scheme (2026-10-15) does not state which tier Accenture/Faculty occupies: UNVERIFIED.

## Sources (fetched 2026-10-19)
- https://www.anthropic.com/news/accenture-embedded-evaluation ; https://www.anthropic.com/news/an-update-on-independent-evaluators
- https://techcrunch.com/2026/09/18/anthropics-first-embedded-evaluator-is-accenture/
- https://faculty.ai/ ; https://faculty.ai/en-gb/company ; https://faculty.ai/en-gb/ai-ethics-safety ; ARES article (URL above)

## Gaps / UNVERIFIED
- Accenture acquisition date/terms, Faculty's AISI history, access tier, publication rights, and any output.
