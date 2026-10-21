# Anthropic — safety evaluation and monitoring knowledge base

Fetched: 2026-10-19. Scope: how Anthropic evaluates and monitors Claude, what it wants from third-party
evaluators, and what it has open-sourced. Written for the goal of being selected as a third-party evaluator.

## Files
- `independent-evaluators.md` — the Oct 15 2026 evaluator post, selection criteria, access tiers, named orgs, how to be noticed.
- `system-cards.md` — per-card inventories (Opus 5.5, Fable 5.1/Mythos 5.1, Sonnet 5.5, Haiku 5.5; notes on Fable 5/Mythos 5, Mythos Preview, Opus 4.6) and post-deployment monitoring statements.
- `rsp-and-process.md` — RSP v3.4 thresholds, cadence, Risk Reports, external review rules, governance, admitted process failures.
- `open-tools-and-methods.md` — every open-source tool/dataset/method and whether it runs on open models.
- `gaps.md` — what is not run or thinly reported, explicit asks, rewarded finding types, project ideas.
- Eval family files: `../../evals/*.md` (one per family; "Used by: Anthropic" lines).

## Headline facts
- RSP v3.4 (Jul 8 2026) replaces ASL gating with Risk Reports every 3-6 months plus external review; latest Risk Report Aug 14 2026 (coverage Jul 15). Alignment risk raised from "very low" to "low" after 2026 cyber-eval incidents.
- Three evaluator tiers; METR embedded (6 staff, employee-like access, no publication veto); SecureBio tier 1; Accenture/Faculty partnership ($1B each over 5 years); Hugging Face in discussion.
- Every card: RSP evals (CB-1/CB-2, AI R&D, alignment update), cyber, safeguards, agentic safety, alignment assessment (automated behavioral audit ~4,000 sessions, honesty, white-box, covert-capability evals), model welfare, capabilities.

## URLs fetched (all 2026-10-19; local copies under `../../sources/anthropic/`)
Anthropic:
- https://www.anthropic.com/news/an-update-on-independent-evaluators (independent-evaluators.txt/html)
- https://www.anthropic.com/news/accenture-embedded-evaluation
- https://www.anthropic.com/news/announcing-our-updated-responsible-scaling-policy (2024 post)
- https://www.anthropic.com/rsp and https://www.anthropic.com/rsp-updates
- https://www-cdn.anthropic.com/files/4zrzovbb/website/0bacdc8440ea96e62a8766d99ebe1d4eea6d5f3a.pdf (RSP v3.4 -> rsp-v3.4.pdf)
- https://anthropic.com/responsible-scaling-policy/roadmap
- https://www-cdn.anthropic.com/f61d49fa5596956a5dec75fea0e973bf6a6a8378/Redacted%20Risk%20Report%20August%202026%20.pdf (risk-report-aug-2026.pdf)
- https://www-cdn.anthropic.com/08eca2757081e850ed2ad490e5253e940240ca4f.pdf (risk-report-feb-2026.pdf; not read in depth)
- https://www-cdn.anthropic.com/f21d93f21602ead5cdbecb8c8e1c765759d9e232.pdf (sabotage-risk-report-opus-4-6.pdf)
- https://alignment.anthropic.com/2025/sabotage-risk-report/2025_pilot_risk_report.pdf
- https://www-cdn.anthropic.com/files/4zrzovbb/website/0a58d567024a8b448ff15158ebc3625328dfcc1f.pdf (Advanced AI Framework, June 2026)
- https://www.anthropic.com/system-cards (index)
- https://www.anthropic.com/claude-opus-5-5-system-card ; https://www.anthropic.com/claude-sonnet-5-5-system-card ; https://www.anthropic.com/claude-haiku-5-5-system-card ; https://www.anthropic.com/claude-fable-5-1-mythos-5-1-system-card ; https://anthropic.com/claude-opus-5-system-card ; https://anthropic.com/claude-fable-5-mythos-5-system-card (all served as PDFs; saved as *.pdf + .txt)
- https://www-cdn.anthropic.com/c788cbc0a3da9135112f97cdf6dcd06f2c16cee2.pdf (Opus 4.6 card); https://www-cdn.anthropic.com/08ab9158070959f88f296514c21b7facce6f52bc.pdf (Mythos Preview card); https://www-cdn.anthropic.com/963373e433e489a87a10c823c52a0a013e9172dd.pdf (Sonnet 4.5 card); https://www-cdn.anthropic.com/4263b940cabb546aa0e3283f35b686f4f3b2ff47.pdf (Claude 4 card)
- https://www.anthropic.com/research/petri-open-source-auditing ; https://alignment.anthropic.com/2026/petri-v2 ; https://alignment.anthropic.com/2025/petri (not fetched separately)
- https://www.anthropic.com/news/bloom ; https://alignment.anthropic.com/2025/bloom-auto-evals/
- https://alignment.anthropic.com/2025/automated-auditing/ ; https://www.anthropic.com/research/auditing-hidden-objectives
- https://www.anthropic.com/research/agentic-misalignment ; https://alignment.anthropic.com/2026/agentic-misalignment-summer-2026/
- https://www.anthropic.com/research/sabotage-evaluations ; https://www.anthropic.com/research/shade-arena-sabotage-monitoring
- https://www.anthropic.com/research/alignment-faking ; https://www.anthropic.com/research/open-source-circuit-tracing
- https://www.anthropic.com/research/next-generation-constitutional-classifiers
- https://support.claude.com/en/articles/12119250-model-safety-bug-bounty-program
- https://www.anthropic.com/news/investigating-incidents-cybersecurity-evals ; https://www.anthropic.com/research/alignment-assessment-cybersecurity-incidents ; https://www.anthropic.com/news/improving-alignment-security-efforts ; https://www.anthropic.com/research/investigating-unintended-model-actions
- https://alignment.anthropic.com/ (index) and posts: 2026/training-alignment-auditors, 2026/auditbench, 2026/auditing-overt-saboteur, 2026/sleight-bench, 2026/chive, 2026/psm, 2026/msm, 2026/coding-audit-realism, 2026/challenges-hopes, 2026/hot-mess-of-ai, 2026/automated-alignment-agent, 2026/diffuse-ai-control, 2026/lie-detectors, 2025/sabotage-risk-report, 2024/rogue-eval, 2025/openai-findings, 2025/automated-researchers-sandbag, 2025/wont-vs-cant
- https://www.anthropic.com/research (index)
- https://darioamodei.com/post/we-must-pace-the-frontier
- GitHub API/READMEs: safety-research org, anthropic-experimental org, anthropics org; inspect_petri, bloom, SHADE-Arena, auditing-agents, sleight-bench, agent-escape-bench, impossiblebench, political-neutrality-eval, A3, agentic-misalignment, mythos-5-incident-transcript, persona_vectors (sources/anthropic/repos/)
Third parties:
- https://metr.org/risk-assessment/ ; https://metr.org/blog/2026-09-22-claude-opus-5-5/ ; https://metr.org/blog/2026-10-14-our-approach-to-risk-assessment/ ; https://metr.org/blog/2026-05-08-rd-section-anthropic-risk-report-feb-2026-review/ ; https://metr.org/blog/2026-03-12-sabotage-risk-report-opus-4-6-review/ ; https://metr.org/assets/sabotage-risk-report-opus-4-6-review-mar-2026.pdf ; https://metr.org/risk-report-feb-mar-2026.pdf (downloaded, not read)
- https://securebio.org/resources/anthropic_feb_2026_risk_review.pdf

## Not fetched / unverified
- White House Accord on Super Intelligence text; UK AISI's Aug 4 2026 Mythos 5 incident report; UK AISI BPJ paper; the Frontier Compliance Framework document; Risk Report Feb 2026 body; Petri/Bloom technical reports as PDFs; "Measurements for understanding the pace of AI development inside frontier labs" (Sep 17 2026); METR's OpenAI/Hugging Face incident report; anthropics/model-cards README; the Training-alignment-auditors code link. Web search budget was exhausted mid-task; later lookups used direct fetches only.
- Sub-agent delegation was unavailable (session limit), so all cards were read directly; the Fable 5/Mythos 5, Mythos Preview, Opus 4.6 and Opus 5 cards were only partially read.
- Two PDFs over 20 MB (Fable 5/Mythos 5 card, Mythos Preview card) are listed in sources/anthropic/.gitignore per CONVENTIONS; their .txt extractions are kept.
