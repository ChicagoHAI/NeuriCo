# SecureBio

- Website: https://securebio.org (AI work: https://securebio.org/ai/)
- Type: US 501(c)(3) nonprofit focused on catastrophic biological risk; member of the NIST US AI Safety Consortium; partner to the EU AI Office; ISO/IEC 27001:2022 certified (per its AI page).
- Fetched: 2026-10-19. Raw copies: `/data/haokun_test/neurico/safety_kb/sources/securebio/`

## What they evaluate
Biosecurity-relevant capabilities of frontier models, in two risk areas stated on https://securebio.org/ai/: capabilities that "lower the barrier to reconstructing dangerous biological agents", and ways models could "generate novel biological threats through scientific insight". Also safeguard effectiveness (BioTIER) and mitigations (adversarial robustness to dual-use queries, unlearning).

Evaluation suites named in fetched sources:
- **Virology Capabilities Test (VCT)** (Götting et al., arXiv:2504.16137): 322 multimodal questions on fundamental, tacit and visual virology lab knowledge, written and tested by externally recruited virology PhDs/PhD students. Expert virologists with internet access averaged 22.1% in their own sub-areas. Reported model accuracies (expert percentile): o3 43.8% (94th), Gemini 2.5 Pro 37.6% (81st), o4-mini 37.0% (86th), o1 35.4% (89th), Claude 3.7 Sonnet 30.8% (78th), GPT-4.5 Preview 28.3% (61st), GPT-4o 18.8% (47th). Source: https://securebio.org/virologytest. **VCT-v2** (announced 2026-09-11) is described as more shortcut-resistant.
- **Human Pathogen Capabilities Test (HPCT)**, **WCB**, **ReproBAIT** (agents reproducing biological AI models from papers), **Advanced Screening Evasion**, protein-design tasks, and **BioTIER** (safeguard testing: refuse harmful, allow benign). These appear in OpenAI's GPT-6 Astra system card section 10.1.1.4 (raw copy: `sources/lab-statements-on-third-party-testing/openai-deploymentsafety-gpt-6-astra.md`). Methodological detail for HPCT/WCB/ReproBAIT is not public in fetched sources: UNVERIFIED beyond the system-card descriptions.
- **ABC-Bench** (agentic bio-capabilities benchmark, Liu, Nedungadi, Cai et al., ICML 2026; OpenReview yiaf7VlPpH) and co-authorship of **WMDP** (Li, Pan, Gopal et al. 2024).

## Methodology (from https://securebio.org/ai/principles/, fetched 2026-10-19)
SecureBio publishes "principles and practices for model assessment". Key verbatim commitments:
- "We retain autonomy in deciding the methods of the assessment."
- "We never enter into collaborations or engagements in which any funding is contingent on the results of our work."
- "We assess pre-release model snapshots that are as close to their deployment configuration as possible." It also requests versions "without safety filters or safety fine-tuning" to measure underlying capability, discloses which configurations it had, and says publicly when access was insufficient.
- "AI developers have no authority to redact our results to conceal performance or unfavorable findings." Developers see reports beforehand only to flag confidential business information.
- Holdout sets with canary strings; no sharing of solutions/scoring for private tasks; developers barred from training on its evaluations; reports summary statistics rather than task-level results so developers cannot optimise against tasks; checks holdout vs non-holdout performance to detect leakage.
- Publishes its own report alongside the developer's where appropriate, and errata when it changes its view.
- VCT scores reported as "refusal-corrected accuracy" (correct among non-refused) in the Astra card.

## Open-source tools / datasets
- VCT: not fully public; "available on request to organizations with a track record in biosecurity and/or AI safety" and subject to export restrictions (https://securebio.org/virologytest). A GitHub presence for VCT was recorded by another analyst (`sources/academic/github-securebio-vct.txt`).
- WMDP (co-authored): public, https://wmdp.ai.
- ABC-Bench: OpenReview paper; availability UNVERIFIED.

## Pre-deployment / embedded access
| Lab | Model | Date | Source | What they found |
|---|---|---|---|---|
| OpenAI | GPT-5 | Aug 2025 | https://openai.com/index/strengthening-safety-with-external-testing/ (names "SecureBio's Virology Capabilities Test (VCT)" among GPT-5 external evaluations) | numbers in GPT-5 system card (not fetched here) |
| OpenAI | GPT-5.6 Sol | Jul 2026 | https://securebio.org/ai/ ("Pre-release assessment") | not detailed on page |
| OpenAI | GPT-6 Astra | Sep 2026 | https://deploymentsafety.openai.com/gpt-6-astra sec. 10.1.1.4 | "evaluated pre-release capability and bio-railfree (helpful-only) checkpoints of Astra, along with two safeguarded configurations"; VCT 57.8%, VCT-v2 57.7% (highest SecureBio had seen); HPCT 65.9% vs 66.5% (GPT-5.6 Sol); WCB 61.6% vs 67.6%; ReproBAIT helpful-only 83% of published performance vs 69%; first models to generate "designable proteins" within task constraints; Advanced Screening Evasion 0.728 vs 0.726, first full-credit response |
| Anthropic | Claude Opus 4.6 / August 2026 Risk Report | Jul-Oct 2026 | https://securebio.org/ai/ ("Review of Anthropic's chemical and biological risk report, July 2026"); https://www.anthropic.com/news/an-update-on-independent-evaluators (2026-10-15: review of the chem/bio chapter of the August 2026 Risk Report after a pilot review) | report not yet published as of fetch |
| Others | logos for xAI, Meta, Scale, CAISI, FMF, EU AI Office under "Who We've Worked With" | - | https://securebio.org/ai/ | nature of work not described: UNVERIFIED |

## Why they are trusted / credibility signals
- Domain expertise: virology/biosecurity scientists (VCT authors include Dan Hendrycks and SecureBio scientists; questions written by virology PhDs) and expert baselines built into benchmarks.
- Published assessment principles covering independence, non-contingent funding, redaction limits, holdout hygiene, and an explicit public conflicts-of-interest policy (https://securebio.org/fcoi-policy; raw copy saved).
- Security posture: ISO/IEC 27001:2022 certification stated on its AI page; VCT export-controlled and gated.
- Track record: WMDP (2024), VCT (2025), repeated pre-release engagements with OpenAI (GPT-5, 5.6, 6) and Anthropic risk-report reviews; cited by OpenAI as a named external benchmark provider.
- Faculty's ARES multi-turn red-teaming system was built "in collaboration with SecureBio" with seven SecureBio bio SMEs (https://faculty.ai/..., 2026-06-26).

## Notable findings (numbers)
- VCT: frontier models exceed the 22.1% expert baseline; o3 at the 94th expert percentile (2025).
- GPT-6 Astra: VCT 57.8%; helpful-only checkpoint first to achieve full credit on screening evasion; expert review still found "efficiency and reliability concerns" (system card 10.1.1.4).

## Publication norms
Per its principles: developers may flag confidential business information for redaction but cannot redact unfavourable findings; SecureBio states whether redactions affect conclusions; publishes alongside developer reports. For OpenAI engagements, OpenAI's stated contract terms require review and approval prior to publication (see `lab-statements-on-third-party-testing.md` sec. 2.2); how these two positions reconcile in practice is not documented: UNVERIFIED.

## Sources (fetched 2026-10-19)
- https://securebio.org/ ; https://securebio.org/ai/ ; https://securebio.org/ai/principles/ ; https://securebio.org/virologytest ; https://securebio.org/fcoi-policy
- https://arxiv.org/abs/2504.16137 (VCT)
- https://deploymentsafety.openai.com/gpt-6-astra (sec. 10.1.1.4)
- https://openai.com/index/strengthening-safety-with-external-testing/ (via web.archive.org)
- https://www.anthropic.com/news/an-update-on-independent-evaluators

## Gaps / UNVERIFIED
- Funders not named on fetched pages. Payment for OpenAI/Anthropic work not stated (OpenAI says it offers compensation to all assessors; SecureBio says it discloses funding in each report).
- HPCT/WCB/ReproBAIT/BioTIER methodology not public in fetched sources.
- GPT-5 system-card numbers for SecureBio evals not fetched here.
