# xAI — safety frameworks and Grok model cards

Fetched: 2026-10-19. All raw text under `safety_kb/sources/xai/`. xAI now operates as "SpaceXAI" (dba of XAI LLC) per the 2026 cards.

## Documents (one file each)
| File | Document | Date |
|---|---|---|
| rmf-draft-2025-02.md | Risk Management Framework (Draft) — placeholder thresholds for VCT/WMDP/LAB-Bench/BioLP/Cybench/MASK | 2025-02-20 |
| risk-management-framework.md | RMF v1.0 — two numeric criteria (bio/chem filter answer rate <1/20; MASK dishonesty <1/2) | 2025-08-20 |
| frontier-ai-framework-2025-12.md | Frontier AI Framework (TFAIA-compliance edition + AB-2013 data disclosure) | 2025-12-30 |
| frontier-ai-framework-2026-06.md | Frontier AI Framework, effective 30 Jun 2026 — EU-CoP vocabulary, 4 risk domains, **all numeric criteria and benchmark names removed** | 2026-06-30 |
| grok-4-model-card.md | Grok 4 (API/Web): refusal 0.00, AgentHarm 0.14, AgentDojo 0.02, MASK 0.43, VCT 0.60-0.71, WMDP-Bio 0.87, CyBench 0.43 | 2025-08-20 |
| grok-code-fast-1-model-card.md | Grok Code Fast 1: MASK 71.9% (breaches RMF <50%), AgentDojo ASR 26.9% | 2025-08-26 |
| grok-4-fast-model-card.md | Grok 4 Fast (reasoning / non-reasoning): MASK 0.47/0.63, soft bias 0.79/0.89 | 2025-09-19 |
| grok-4-1-model-card.md | Grok 4.1 T/NT: multilingual refusal correction, input-filter FNR (0.20 under injection), LAB-Bench subsets + human baselines | 2025-11-17 |
| grok-4-20-system-card.md | Grok 4.20 SA/MA: first third-party testing + Petri-based alignment audit; AgentHarm 0.30, AgentDojo 0.33, HLE calibration | 2026-04-07 |
| grok-4-5-model-card.md | Grok 4.5: capability-first card; CyberGym 80.4, HackerBench compliance 7.8%, VCT 65.5, jailbreak 0.73%, FORTRESS-RN 97.9%, MASK-Rectified 0.67% | 2026-07-14 (rev 07-20) |
| grok-4-6-model-card.md | Grok 4.6: StrongREJECT 3.9%, long-horizon JB 1.0%, bio/chem refusal recall 100%, MASK-Rectified 1.90%, unnamed third-party cyber corroboration | 2026-08-12 (rev 08-17) |
| grok-4-7-model-card.md | Grok 4.7: BioSecBench (LatchBio), CathedralBench (independent cyber), HealthBench Pro; VCT 63.0, dishonesty 0.00% | 2026-09-21 |
| external-criticism.md | AI Lab Watch (4% score; "profoundly unserious"), SaferAI (16% overall, 5% risk treatment) | 2025-09 / 2026-04 |

## Framework structure (current, June 2026 FAIF)
Risk domains: CBRN, Offensive Cybersecurity, Loss of Control, Harmful Manipulation. Behavior buckets: abuse potential / concerning propensities / dual-use capabilities. Process: annual "full systemic risk assessment", trigger-point evaluations, acceptance determination "incorporating a margin of security" with unpublished "risk tiers"; security goal reviewed annually (NIST 800-171 r3, SOC 2 Type II; names insider threats and state actors); incident reporting to authorities when legally required. No board/committee, no named evaluators, no thresholds.

## Evaluations used across cards (see `safety_kb/evals/`)
Public: WMDP (bio/chem/cyber), VCT, BioLP-Bench, LAB-Bench (ProtocolQA/FigQA/CloningScenarios, practical MCQ, ProtocolQA open-ended), BixBench, CyBench (UK AISI Inspect harness), CyberGym, CVE-Bench, AgentHarm, AgentDojo, MASK / MASK-Rectified, Anthropic answer-sycophancy, MakeMeSay, HLE (RMS calibration), StrongREJECT, Crescendo multi-turn, FORTRESS (Scale AI, R/N subset), HealthBench Professional, Petri 2.0 (alignment-audit scaffold). Internal: multilingual refusal set, jailbreak suites, soft/epistemic bias, contrastive sycophancy, restricted bio/chem input-filter set (SecureBio), Autointent-Bio/Chem, Biosecurity VCT, BioUseBench, HackerBench, SecureCodeReview, self-harm suite, child-safety multi-turn suite. Third-party: BioSecBench & LatchBio Capabilities (LatchBio), CathedralBench (Cathedral), FORTRESS-RN runs (Scale AI).

## Trajectory and gaps (summary)
- Thresholds: draft (Feb 2025) placeholders -> two numeric criteria (Aug 2025-Dec 2025) -> none (Jun 2026). Cards from 4.6 on assert "below the FAIF safety thresholds" that are not published.
- The two criteria were breached in shipped configurations (Code Fast 1 MASK 71.9%; Grok 4 Fast NT 63%; Grok 4.1 filter FNR 20% under injection) with no stated consequence.
- Third-party testing: none named until 2026; Grok 4.20 first mentions unnamed refusal/scheming evaluators; 4.6/4.7 cite unnamed cyber corroboration, Scale AI (FORTRESS), LatchBio, Cathedral. No AISI/CAISI involvement is stated anywhere.
- Never run or disclosed: human uplift studies, autonomy / self-replication / AI-R&D evaluations, radiological/nuclear capability evals (only R/N refusal from 4.5 on), pre-mitigation refusal rates in 2026 cards, agentic-harm and prompt-injection numbers after 4.20, alignment audits after 4.20, any security audit result, any incident disclosure.
- Metric redefinitions (MASK -> MASK-Rectified; refusal eval English-only -> multilingual; HackerBench v0.2 -> v0.3; "corrected" results) prevent longitudinal comparison.
