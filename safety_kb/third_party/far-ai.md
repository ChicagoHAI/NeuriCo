# FAR.AI

- Website: https://far.ai (research: https://far.ai/research ; transparency: https://far.ai/transparency ; leaderboard: https://leaderboard.far.ai/)
- Type: 501(c)(3) research and education nonprofit, incorporated October 2022 (EIN 92-0692207); runs FAR.Labs (Berkeley co-working space), grantmaking, and the Alignment Workshop series.
- Fetched: 2026-10-19. Raw copies: `/data/haokun_test/neurico/safety_kb/sources/far-ai/`

## What they evaluate
Robustness of frontier-model safeguards and alignment; model evaluations of societal-risk behaviours. Featured work on the homepage (2026-10-19):
- **STACK** (2025-07-01): adversarial attacks on layered "defense-in-depth" LLM safeguard pipelines; reports a 71% attack success rate on catastrophic-risk scenarios. https://far.ai/research/stack-adversarial-attacks-on-llm-safeguard-pipelines
- **The Obfuscation Atlas** (2026-02-16): models trained against white-box deception probes develop evasion strategies; strong KL regularisation plus a detector penalty suppresses them. https://far.ai/research/the-obfuscation-atlas-mapping-where-honesty-emerges-in-rlvr-with-deception-probes
- Persuasion study (2026-01-08): GPT-4o about as effective at increasing conspiracy beliefs as decreasing them; OpenAI guardrails "did little to prevent this". https://far.ai/research/large-language-models-can-effectively-convince-people-to-believe-conspiracies
- Earlier (not re-fetched; UNVERIFIED here): jailbreak-tuning, adversarial policies vs superhuman Go, "AI Safety Index"-style robustness leaderboards (leaderboard.far.ai).

## Methodology
Primarily empirical attack/defence research published as papers; consulting engagements for developers under the revenue cap below. No standardised pre-deployment evaluation suite is described on fetched pages.

## Open-source tools / datasets
- GitHub organisation AlignmentResearch (linked from FAR.AI papers; contents not fetched this session: UNVERIFIED).
- leaderboard.far.ai (public leaderboard; contents not fetched).

## Pre-deployment / embedded access
| Lab | Model | Date | Source | Notes |
|---|---|---|---|---|
| none documented | - | - | - | TechCrunch 2026-09-16 quotes CEO Adam Gleave saying FAR.AI "turned down contracts from developers that wanted too much control" (raw: `sources/lab-statements-on-third-party-testing/techcrunch-embedded-evaluators-independence-2026-09-16.txt`) |

## Why they are trusted / credibility signals (from https://far.ai/transparency)
- Independence rules, verbatim/paraphrased from the transparency page: consulting for for-profit AI developers is capped at 10% of total annual revenue; developers "generally pay market rates" while governments, standards bodies and aligned nonprofits may get free or discounted work; FAR.AI "will disclose what share of its revenue comes from for-profit developer consulting"; leadership approves each engagement on mission alignment; it "keeps the right to publish non-confidential insights and has declined contracts that restricted this"; publication may be withheld "to prevent clear safety harms, but not to avoid competitive harm to a specific company"; it "will not accept terms that would stop it from commenting freely on publicly available models"; research informed by paid work is labelled as such with funding acknowledgements.
- Governance: CEO, board, whistleblower, anti-corruption and EEO policies; Form 990s for 2022-2024 and the Form 1023 linked (amounts not on page).
- Positions on evaluator access (Gleave, TechCrunch 2026-09-16): evaluators should be able to compare checkpoints, inspect post-training reward environments, and verify performance claims using transcripts and logs; by default evaluators are bound by restrictive NDAs; labs' IP is "so incredibly valuable to them" that they may be cautious about sharing.

## Notable findings (numbers)
- STACK: 71% attack success against layered safeguards on catastrophic-risk scenarios (homepage summary).

## Publication norms
See transparency page: retains publication rights for non-confidential insights; declines contracts restricting comment on public models; labels paid-work-informed research.

## Sources (fetched 2026-10-19)
- https://far.ai/ ; https://far.ai/transparency
- https://techcrunch.com/2026/09/16/anthropic-and-openai-want-to-embed-safety-evaluators-will-they-really-be-independent/

## Gaps / UNVERIFIED
- No documented pre-deployment engagement; FAR.AI is included here mainly for its published independence policy and public positions.
- Funding amounts and donors not on the fetched transparency page.
