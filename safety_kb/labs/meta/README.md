# Meta - safety evaluation and monitoring (knowledge-base notes)

Fetched: 2026-10-19. All claims below cite the per-document files, which quote the fetched sources in /data/haokun_test/neurico/safety_kb/sources/meta/.

## Overview
- Governance: Meta's frontier risk policy has gone through three versions in 20 months: Frontier AI Framework v1.1 (Feb 2025; cyber + chem/bio; thresholds critical/high/moderate defined by "uniquely enable" / "significant uplift"; Critical = "Stop development", High = "Do not release"), Advanced AI Scaling Framework v2.0 (Apr 7 2026; adds Loss of Control, named accountable executives, preparedness reports, 10^26 FLOP frontier definition; thresholds softened to "substantially contribute" and "Develop/Deploy with mitigations"), and Meta Superintelligence Scaling Framework v2.1 (Oct 2026; adds containment-failure outcome and open-weights discussion, board governance in progress).
- The only quantitative thresholds Meta publishes are in v2.0: CTF simple-suite "< 75% pass@10" rule-out; BioTIER ">= 80% refusal or safe responses, and 40% ... against all adversarial attacks"; MASK >= 40% and Agent Misalignment <= 50% propensity criteria; MLE-bench 60% medal threshold (Muse Spark report).
- Open-weight Llama 4 (Apr 2025) shipped with a model card containing qualitative critical-risk statements (CBRNE, child safety, cyber) and no safety numbers; the only figures are blog refusal rates on political topics (7% -> <2%).
- Closed-weight Muse Spark (Apr 2026) is the first Meta model with a full Safety & Preparedness Report: pre-mitigation "high risk" for chem/bio (and for cyber in 1.1), post-mitigation "moderate or lower"; dozens of named benchmarks with numbers; external evaluators named (Apollo, Scale AI, HandshakeAI, GraySwan, Irregular, SecureBio). Apollo found "the highest rates of evaluation awareness among models they have tested to date".
- Tooling (Purple Llama): CyberSecEval 1-4, Llama Guard 4 (12B multimodal, MLCommons taxonomy S1-S14; English F1 61%), Prompt Guard 2 (86M/22M; recall@1%FPR 97.5%; AgentDojo APR 81.2%), LlamaFirewall (AgentDojo ASR 17.6% -> 1.75%), Code Shield (precision 96% / recall 79%).
- No Llama 4.1 / Llama 5 model card exists as of 2026-10-19 (UNVERIFIED beyond search); Meta's current frontier work is Muse Spark.

## Index
| File | Document | Date |
| frontier-ai-framework.md | Frontier AI Framework v1.1 (Wayback copy; live URL 500) | Feb 2025 |
| advanced-ai-scaling-framework.md | Advanced AI Scaling Framework v2.0 + Meta Superintelligence Scaling Framework v2.1 | Apr / Oct 2026 |
| muse-spark-safety-preparedness-report.md | Muse Spark Safety & Preparedness Report | May 26 2026 |
| muse-spark-1-1-evaluation-report.md | Muse Spark 1.1 Evaluation Report | Jul 9 2026 |
| llama4-model-card.md | Llama 4 Scout/Maverick model card + launch blog | Apr 5 2025 |
| llama-guard-4.md | Llama Guard 4 12B card | Apr 2025 |
| prompt-guard-2.md | Llama Prompt Guard 2 (86M/22M) card | Apr 2025 |
| cyberseceval.md | CyberSecEval v1-v4 (papers + README) | 2023-2025 |
| llama-firewall.md | LlamaFirewall paper/README (incl. Code Shield, AlignmentCheck) | May 2025 |
| purple-llama.md | Purple Llama umbrella README | - |
| third-party-testing-statements.md | External red teaming / evaluator access statements | - |

## Raw sources
/data/haokun_test/neurico/safety_kb/sources/meta/ - PDFs + pdftotext .txt for both frameworks (v1.1, v2.0, v2.1), both Muse Spark reports, four arXiv papers; raw GitHub markdown for Llama 4 card, Purple Llama, CyberSecEval, LlamaFirewall READMEs; HF API JSON for gated Llama 4 / Llama Guard 4 / Prompt Guard 2 repos; webfetch-*.md files holding WebFetch tool output for gated HF pages and blog posts.

## Could not fetch / unverified
- https://ai.meta.com/static-resource/meta-frontier-ai-framework/ returns HTTP 500 (used Wayback capture of 2026-03-03).
- https://ai.meta.com/blog/meta-approach-frontier-ai/ returns 404.
- Gated HF READMEs (401): content taken via WebFetch page rendering.
- Meta "model spec" promised in v2.0: not located.
- Llama 4 Behemoth card: not found.
