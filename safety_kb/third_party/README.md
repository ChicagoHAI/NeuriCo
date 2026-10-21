# Third-party evaluator ecosystem: index

Fetched/compiled: 2026-10-19. One file per organisation; each has the same structure (what they evaluate, methodology, open-source tools, pre-deployment access table, credibility signals, notable findings, publication norms, sources, gaps/UNVERIFIED). Raw text under `/data/haokun_test/neurico/safety_kb/sources/<org>/`. Evaluation families are catalogued under `/data/haokun_test/neurico/safety_kb/evals/`.

## Synthesis documents
| File | Content |
|---|---|
| `how-to-become-a-trusted-evaluator.md` | What a new third-party safety lab must demonstrate (access ladder, lab-stated criteria, demonstrated practices, checklist), with citations |
| `lab-statements-on-third-party-testing.md` | Lab-side and policy-side statements: Anthropic (2024-2026, incl. evaluator tiers), OpenAI (2024 red-teaming paper, 2025 external-testing post, 2026 principles), Frontier Model Forum, White House Accord (2026-09-29), California SB 813 / AB 1405, ICML 2026 funding map |
| `openai-hugging-face-incident-2026.md` | The July 2026 agent intrusion and its four investigations (OpenAI, METR+Redwood, Nightingale, Hugging Face) |
| `ai-evaluator-forum.md` | The AI Evaluator Forum (METR, Transluce, SecureBio, RAND, AVERI, CIP, Meridian, Princeton HAL) and its AEF-1 "Minimum Operating Conditions" standard, requirement by requirement |

## Government institutes
| File | Org | One line |
|---|---|---|
| `uk-aisi.md` | UK AI Security Institute | Inspect / Inspect Evals / ControlArena; pre-deployment cyber, bio, safeguards, alignment and monitorability testing of OpenAI, Anthropic, Google DeepMind models; "over 30 state-of-the-art models"; public incident disclosure (Aug 2026) |
| `us-caisi.md` | US CAISI / CAISSI (NIST) | MoUs with OpenAI/Anthropic (Aug 2024); pre-deployment national-security testing; public evaluations of DeepSeek and Kimi K2 Thinking; NIST AI 800-1; Dioptra; framed around US competitiveness |

## Independent nonprofit assessors with documented pre-release access
| File | Org | One line |
|---|---|---|
| `metr.md` | METR | Time horizon, RE-Bench, HCAST; pre-release reports for OpenAI (o1 to GPT-5.6 Sol) and Anthropic (3.7 to Opus 5.5); methodology and risk-report reviews; 2026 Frontier Risk Report on internal models of four labs; embedded Tier-3 team at Anthropic; COI policy; SOC 2 |
| `apollo-research.md` | Apollo Research | In-context scheming, sandbagging, eval awareness; named in every OpenAI reasoning-model card since o1 and in Anthropic cards; three days on GPT-6 Astra; became a PBC (Jan 2026); published COI/security/science-comms norms |
| `redwood-research.md` | Redwood Research | AI control agenda, Subversion Strategy Eval, alignment faking and sabotage evals with Anthropic, ControlArena with AISI; unpaid on-site HF-incident investigation with METR |
| `transluce.md` | Transluce | Docent, investigator agents, behaviour reports; early o3 access; 2026 mental-health evaluation across 77 model variants with privileged access from three labs; AEF-1-aligned independence and disclosure policies |
| `securebio.md` | SecureBio | VCT, HPCT, ReproBAIT, BioTIER; helpful-only checkpoints of GPT-5/5.6/6; review of Anthropic risk-report chem/bio chapter; published assessment principles; ISO 27001 |

## Commercial red-team and cyber evaluation vendors
| File | Org | One line |
|---|---|---|
| `gray-swan.md` | Gray Swan AI | Arena competitions with UK AISI/CAISI, ART and IPI benchmarks, Shade attacker; named in OpenAI, Anthropic and Google cards; labs are customers |
| `irregular.md` | Irregular (ex-Pattern Labs) | SOLVE, Atomic, CyScenarioBench, FrontierCyber; pre-release cyber assessments for OpenAI, Anthropic, Google DeepMind, Meta and open-weight models; zero-day disclosures |
| `scale-seal.md` | Scale AI SEAL | Fortress, MASK, PropensityBench, MHJ leaderboards; first US AISI-authorised evaluator (Feb 2025); system-card naming UNVERIFIED |
| `haize-labs.md` | Haize Labs | Automated red-teaming and judges; named in o1 card; acquired Sept 2026 |
| `lakera.md` | Lakera | Gandalf, PINT, b3 (with UK AISI); no pre-deployment access documented |
| `promptfoo.md` | Promptfoo | MIT red-team CLI and public model security reports; acquired by OpenAI (Mar 2026) |
| `enkrypt-ai.md` | Enkrypt AI | Red-team reports (DeepSeek-R1, Pixtral); leaderboard; post-release only |
| `holistic-ai.md` | Holistic AI | Jailbreak audits of public models; open library |
| `faculty-accenture.md` | Faculty / Accenture | Embedded evaluator at Anthropic ($1B each over five years, Sept 2026); ARES automated red-teaming |

## Benchmark, index and assurance organisations
| File | Org | One line |
|---|---|---|
| `mlcommons-ailuminate.md` | MLCommons AILuminate | 12-hazard, 24k-prompt safety benchmark with Poor-Excellent grades; modelbench open source |
| `epoch-ai.md` | Epoch AI | Capabilities Index, FrontierMath, benchmarking hub; capability tracker rather than safety auditor; OpenAI funding disclosure episode |
| `ai-verify.md` | AI Verify Foundation / IMDA (Singapore) | Moonshot toolkit, Global AI Assurance Pilot, Starter Kit, multilingual red-teaming challenge |
| `academic-and-nonprofit-auditors.md` | CAIS, Stanford CRFM/HAI, Berkeley, ETH, EPFL, SaferAI, AI Lab Watch, FLI AI Safety Index, MIT, Oxford, FRI | Benchmarks (HarmBench, WMDP, MASK, HLE, HELM Safety, AgentDojo, COMPL-AI, CyberGym, BountyBench) and lab-rating indices |

## Evaluators without lab access whose findings shaped the field
| File | Org | One line |
|---|---|---|
| `palisade-research.md` | Palisade Research | Shutdown resistance (o3 79/100), chess specification gaming, autonomous hack-and-self-replicate; all code public |
| `nightingale-collective.md` | Nightingale Collective | OSINT investigations of undisclosed OpenAI agent incidents (wiki message board; RubyGems) |
| `far-ai.md` | FAR.AI | STACK safeguard-pipeline attacks; published independence policy (10% developer-revenue cap); declined restrictive contracts |

## Regional
| File | Content |
|---|---|
| `china-governance-and-commitments.md`, `shanghai-ai-lab-safework.md` | Chinese governance commitments and Shanghai AI Lab SafeWork evaluations (written by another analyst) |

## Cross-cutting facts (for quick reference)
- Named in system cards as of Oct 2026: METR, Apollo, UK AISI, US CAISI, Gray Swan, Irregular, SecureBio, Transluce (o3), Haize/Faculty/Virtue AI (o1 acknowledgements), Scale AI (xAI Grok 4.5 FORTRESS), LatchBio and Cathedral (Grok 4.7), HandshakeAI (Meta Muse Spark).
- Documented deepest access: METR (Anthropic Tier 3, six staff, employee-like; internal models of four labs for the Frontier Risk Report), METR/Redwood (OpenAI premises, raw chains of thought), SecureBio and Irregular (helpful-only pre-release checkpoints), Apollo (CoT access on GPT-6 Astra for two days).
- Standards for evaluators themselves: AI Evaluator Forum AEF-1 "Minimum Operating Conditions for Independent Third Party AI Evaluations" (adopted by Transluce); California SB 813 IVO criteria (2027-2028); METR, Apollo, SecureBio, FAR.AI, Transluce published COI/independence policies.
