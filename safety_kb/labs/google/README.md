# Google / Google DeepMind: index

Fetched: 2026-10-19. Conventions: see `../../CONVENTIONS.md`.

## Files in this directory

- `gemini-4-argon-model-card.md` — Gemini 4 Argon model card (Oct 2026): safety process (who/what/when, governance), full table of every reported eval and number, disclosed vs withheld, and category-by-category gaps. Written from the model card, the evals-methodology PDF, FSF v3.1 and the linked pages.
- `gemini-4-safety-report-notes.md` — running notes on the 217-page Gemini 4 Argon Safety & Security Report (written by the safety-report agent; cross-referenced, not duplicated here).

## Sources saved by the model-card agent (`../../sources/google/`)

Each `.md` carries a header with URL, final URL, fetch date and notes; raw HTML/PDF kept alongside.

- `model-card-gemini-4-argon.md` (+ `argon-links-gemini-4-argon.html`) — the model card web page.
- `model-card-gemini-4-argon-pdf.md` (+ `Gemini-4-Argon-Model-Card.pdf`) — PDF version; table pages are images, values checked visually.
- `gemini-4-argon-model-evaluation-methodology.md` (+ `gemini_4_argon_model_evaluation.pdf`) — benchmark methodology; header lists the hyperlinks embedded in the PDF.
- `frontier-safety-framework-v3-1-apr2026.md` — FSF v3.1 PDF text (the frontier-safety agent also saved `fsf_v3-1.pdf/.txt`).
- `google-ai-principles-page.md` (+ `argon-links-ai-principles.html`).
- `google-ai-safety-page.md` (+ `argon-links-ai-responsibility-safety.html`) — ai.google/safety (ART, 24/7 monitoring, bug bounty, SynthID, FSF, SAIF).
- `google-ai-responsibility-progress-report-feb-2025.md` (+ `.pdf`) — Responsible AI Progress Report, Feb 2025.
- `google-genai-prohibited-use-policy.md` (+ `argon-links-genai-prohibited-use-policy.html`).
- `google-child-safety-commitments-blog-2024.md` (+ `argon-links-child-safety-commitments.html`).
- `deepmind-responsibility-and-safety-page.md` — RSC / AGI Safety Council; links to the Argon safety blog.
- `deepmind-research-evals-page.md` — GDM-published benchmarks (ASIMOV-Agentic, SimpleQA Verified, FACTS, DeepSearchQA, Chess Text, MRCR v2).
- `gemini-api-additional-terms.md` (+ `argon-links-gemini-api-terms.html`) — abuse-monitoring / logging clauses.
- `blog-developing-gemini-4-argon-responsibly-and-safely.md` (+ `argon-links-gemini-4-model-safety-security-blog.html`) — Oct 13, 2026 blog with Argon-specific safety numbers.
- `blog-piloting-double-blind-ai-evaluations.md` (+ `argon-links-double-blind-ai-evaluations-blog.html`) — Aug 27, 2026 third-party double-blind evaluation pilot.
- `deepmind-fairwind-program.md` (+ `argon-links-fairwind-program.html`) — trusted-access cyber program; cyber benchmark charts.

## Eval files created in `../../evals/` from the Gemini 4 Argon card

Capability benchmarks: `vals-index`, `automationbench`, `vals-finance-agent`, `harvey-legal-agent-benchmark`, `deepswe`, `frontierswe`, `vibe-code-bench`, `terminal-bench`, `posttrainbench`, `terminal-bench-science`, `labbench`, `riemannbench`, `graphwalks`, `agents-last-exam`, `osworld`, `chartography`, `lvbench`, `cwe-bench`, `gdm-real-world-vulnerability-discovery`, `wiz-penetration-testing-benchmark`, `gray-swan-ipi`.

Safety / frontier-safety evals: `gemini-text-to-text-content-safety`, `gemini-multilingual-safety`, `gemini-image-to-text-safety`, `gemini-refusal-tone`, `gemini-unjustified-refusals`, `gemini-human-red-teaming-content-safety`, `gemini-child-safety-launch-thresholds`, `gemini-automated-red-teaming`, `gdm-cbrn-uplift-expert-red-teaming`, `gdm-cyber-end-to-end-attack-scenarios`, `gdm-harmful-manipulation-human-studies`, `gdm-stealth-situational-awareness-challenges`, `gdm-ml-rd-internal-benchmark`, `gdm-misalignment-honeypots`, `gdm-coding-shortcut-rate`, `gdm-bio-jailbreak-red-teaming`.

(If a slug already existed when the generator ran, only a "Used by: Google (Gemini 4 Argon)" line was appended.)

## URLs fetched (all 2026-10-19, HTTP 200)

1. https://deepmind.google/models/model-cards/gemini-4-argon/
2. https://storage.googleapis.com/deepmind-media/Model-Cards/Gemini-4-Argon-Model-Card.pdf
3. https://deepmind.google/models/evals-methodology/gemini-4-argon → 301 → https://storage.googleapis.com/deepmind-media/gemini/gemini_4_argon_model_evaluation.pdf
4. https://storage.googleapis.com/deepmind-media/DeepMind.com/Blog/strengthening-our-frontier-safety-framework/frontier-safety-framework_3-1.pdf
5. https://ai.google/responsibility/principles/ → https://ai.google/principles/
6. https://ai.google/responsibility/safety/ → https://ai.google/safety/
7. https://ai.google/static/documents/ai-responsibility-update-published-february-2025.pdf → storage.googleapis.com/gdm-deepmind-com-prod-public/media/documents/ai-responsibility-update-published-february-2025.pdf
8. https://policies.google.com/terms/generative-ai/use-policy
9. https://blog.google/technology/safety-security/an-update-on-our-child-safety-efforts-and-commitments/ → https://blog.google/innovation-and-ai/technology/safety-security/an-update-on-our-child-safety-efforts-and-commitments/
10. https://deepmind.google/responsibility-and-safety/
11. https://deepmind.google/research/evals/
12. https://ai.google.dev/gemini-api/terms
13. https://blog.google/innovation-and-ai/technology/safety-security/gemini-4-model-safety-security/ (two levels deep, via 10)
14. https://deepmind.google/blog/piloting-the-worlds-first-double-blind-ai-evaluations/ (two levels deep, via 10)
15. https://deepmind.google/fairwind-program/ (two levels deep, via 13)

## URLs found but not fetched (with reason)

- https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf — assigned to the safety-report agent (`gemini-4-safety-report-notes.md`). The card: "The full Safety & Security Report for Gemini 4 Argon which systematically covers our set of defenses is here."
- https://deepmind.google/frontier-safety/ — assigned to the frontier-safety agent. The card: "we perform testing following the guidelines in Google DeepMind's Frontier Safety Framework (FSF)".
- https://storage.googleapis.com/deepmind-media/gemini/gemini_v2_5_report.pdf (#page=40/41/43) — architecture citations (MoE papers) only; not safety.
- https://policies.google.com/terms/generative-ai/use-policy?e=IdentityBoq... — same policy as #8 with tracking parameters.
- https://cloud.google.com/tpu, https://sustainability.google/operating-sustainably/, https://github.com/google/jax, https://blog.google/technology/ai/introducing-pathways-next-generation-ai-architecture/ — hardware/software, not safety.
- Distribution links: gemini.google.com, ai.google.dev/gemini-api/docs/models, aistudio.google.com, cloud.google.com/gemini-enterprise, antigravity.google/docs, search.google/ways-to-search/ai-mode/, cloud.google.com/terms/, ai.google.dev/gemini-api/docs/, ai.google.dev/gemini-api/docs/quickstart — product/legal pages, not safety.
- https://deepmind.google/models/model-cards/ — index of other model cards (PDF link); the frontier-safety agent saved `model-cards-index.html`.
- Benchmark leaderboards linked from the methodology PDF (deepswe.datacurve.ai, agents-last-exam.org/leaderboard, cwe-bench.com, surgehq.ai/benchmarks/chartography, surgehq.ai/benchmarks/riemann-bench, frontierswe.com, grayswan.ai, tbench.ai, terminal-bench-science.ai, vals.ai/benchmarks/vibe-code, zapier.com/benchmarks, openai.com/index/gpt-6-astra/, Anthropic Opus 5.5 system card) — competitor/benchmark hosts; recorded as source links in `evals/*.md`, not fetched (out of scope: not Google safety pages).
- From the Argon safety blog: https://deepmind.google/blog/securing-the-future-of-ai-agents/ (agent control roadmap), https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-gemini-4-argon/ (launch post), https://www.wiz.io/scan-for-good — three levels deep or product announcements; not fetched.
- From the responsibility page: https://deepmind.google/blog/our-approach-to-bioresilience/ — the frontier-safety agent saved it (`blog-bioresilience.*`).
- From the double-blind blog: technical report PDF and MLCommons post — not Argon-specific; not fetched.
- From the AI Principles page: https://ai.google/static/documents/ai-responsibility-update-2026.pdf (2026 progress report) — found only one level below a linked page and not referenced by the card; not fetched (candidate for a follow-up).
- Social/footer links (x.com, instagram, youtube, linkedin, github.com/google-deepmind, policies.google.com/privacy) — not relevant.

## Notes
- Conversion scripts live outside sources/: `/data/haokun_test/neurico/scripts_kb/html2md.py` (run with `python3 -I`), `pdftotext -layout`, `pdftohtml` for PDF link extraction, `pdftoppm` to view image-only table pages.
- Three small pages (ai.google/principles, double-blind blog, Fairwind) came back compressed on the first curl and were re-fetched with `--compressed`.

## Frontier safety program coverage (agent: frontier-safety scope; fetched 2026-10-19)

### Files written
- labs/google/frontier-safety-framework.md — FSF v3.1 structure (T/CCLs, alert thresholds, cadence, mitigation levels, governance, external parties, version history) + table of dangerous-capability evaluation suites.
- labs/google/safety-program-overview.md — lifecycle view of evaluation and monitoring (pre-training, post-training, pre-deployment, deployment-time classifiers/abuse monitoring/jailbreak pipeline, post-deployment), who runs what, third-party evaluator statements.
- labs/google/open-questions-and-gaps.md — scope gaps, undisclosed parameters, internal-only vs public evals, complementary third-party evaluations (open-weight-runnable flagged).
- evals/: gdm-stealth-situational-awareness.md, gdm-cyber-key-skills-benchmark.md, gdm-in-house-ctf.md, gdm-self-proliferation.md, gdm-dangerous-capabilities-2024-persuasion.md, harmful-manipulation-efficacy-study.md, gdm-cbrn-expert-red-teaming-harm-journeys.md, lab-bench.md, vct-virology-capabilities-test.md, re-bench.md, gdm-grb-research-engineering-benchmark.md, gdm-safeguard-coverage-and-jailbreak-robustness.md, cot-monitorability-legibility.md, eval-awareness-and-sandbagging-checks.md, bio-wet-lab-uplift-rct.md.
- sources/google/: fsf_v1-0, fsf_v2-0, fsf_v3-0, fsf_v3-1 (.pdf + .txt); gemini_3_pro_fsf_report, gemini_3-7_flash_fsf_report (.pdf + .txt); evaluating-frontier-models-dangerous-capabilities-arxiv-2403.13793, approach-to-technical-agi-safety-arxiv-2504.01849, cyber-eval-framework-arxiv-2503.11917, stealth-situational-awareness-arxiv-2505.01420 (.pdf + .txt); model-card-gemini-3-pro (.pdf + .txt); .html + .md for: frontier-safety, responsibility-and-safety, research-evals, model-cards-index, model-card-gemini-3-7-flash, gemini-model-page, blog-strengthening-fsf, blog-updating-fsf, blog-introducing-fsf, blog-responsible-path-agi, blog-cyber-threats, blog-harmful-manipulation, blog-double-blind-evals, blog-bioresilience, blog-gemma-scope, google-ai-principles, google-saif-blog, google-cloud-adversarial-misuse-gen-ai, gemini-api-abuse-monitoring, gemini-api-usage-policies; inspect-evals-gdm-readmes.md.

### URLs fetched (HTTP 200 unless noted)
- https://deepmind.google/frontier-safety/
- https://storage.googleapis.com/deepmind-media/DeepMind.com/Blog/strengthening-our-frontier-safety-framework/frontier-safety-framework_3-1.pdf
- https://storage.googleapis.com/deepmind-media/DeepMind.com/Blog/strengthening-our-frontier-safety-framework/frontier-safety-framework_3.pdf
- https://storage.googleapis.com/deepmind-media/DeepMind.com/Blog/updating-the-frontier-safety-framework/Frontier%20Safety%20Framework%202.0.pdf
- https://storage.googleapis.com/deepmind-media/DeepMind.com/Blog/introducing-the-frontier-safety-framework/fsf-technical-report.pdf
- https://storage.googleapis.com/deepmind-media/gemini/gemini_3_pro_fsf_report.pdf
- https://storage.googleapis.com/deepmind-media/gemini/gemini_3-7_flash_fsf_report.pdf
- https://arxiv.org/pdf/2403.13793 ; https://arxiv.org/pdf/2504.01849 ; https://arxiv.org/pdf/2503.11917 ; https://arxiv.org/pdf/2505.01420
- https://arxiv.org/abs/2505.01420, /2503.11917, /2507.05246, /2404.15058, /2501.13011, /2509.07968, /2406.13843 (title + abstract only)
- https://deepmind.google/responsibility-and-safety/
- https://deepmind.google/research/evals/
- https://deepmind.google/models/model-cards/
- https://deepmind.google/models/model-cards/gemini-3-pro/ (served as PDF)
- https://deepmind.google/models/model-cards/gemini-3-7-flash/
- https://deepmind.google/models/gemini/
- https://deepmind.google/blog/strengthening-our-frontier-safety-framework/
- https://deepmind.google/blog/updating-the-frontier-safety-framework/
- https://deepmind.google/blog/introducing-the-frontier-safety-framework/
- https://deepmind.google/blog/taking-a-responsible-path-to-agi/
- https://deepmind.google/blog/evaluating-potential-cybersecurity-threats-of-advanced-ai/
- https://deepmind.google/blog/protecting-people-from-harmful-manipulation/
- https://deepmind.google/blog/piloting-the-worlds-first-double-blind-ai-evaluations/
- https://deepmind.google/blog/our-approach-to-bioresilience/
- https://deepmind.google/discover/blog/gemma-scope-helping-the-safety-community-shed-light-on-the-inner-workings-of-language-models/
- https://ai.google/responsibility/principles/
- https://blog.google/technology/safety-security/introducing-googles-secure-ai-framework/
- https://cloud.google.com/blog/topics/threat-intelligence/adversarial-misuse-generative-ai
- https://ai.google.dev/gemini-api/docs/abuse-monitoring ; https://ai.google.dev/gemini-api/docs/usage-policies.md.txt
- https://raw.githubusercontent.com/UKGovernmentBEIS/inspect_evals/main/src/inspect_evals/gdm_capabilities/README.md (+ gdm_stealth, gdm_self_reasoning READMEs; GitHub API directory listing)

### URLs not fetched / failed
- https://deepmind.google/discover/blog/evaluating-frontier-models-for-dangerous-capabilities/ — HTTP 404 (paper fetched from arXiv instead).
- https://deepmind.google/models/model-cards/gemini-4-argon/ and gemini_4_safety_report.pdf — out of scope (covered by other agents; cross-referenced only).
- Double-blind evaluation technical report and AVERI pilot report — not located/fetched (blog only).
- Akbulut et al. 2026 manipulation toolkit, Hong et al. 2026 wet-lab RCT, Panoplia trial, Ho et al. 2025 capability index — not fetched; described only via Google documents (marked UNVERIFIED where relied upon).
- RAND RRA2849-1, Rodriguez et al. framework benchmark contents, Gray Swan reports — not fetched.
- Secondary commentary (frontierrisk.substack.com, ppc.land, LessWrong/EA Forum on external evaluator access) — surfaced via web search only, not fetched; treated as UNVERIFIED.

## Gemini 4 Argon Safety & Security Report (October 2026)
- URL: https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf (217 pages). Fetched 2026-10-19.
- Notes: `labs/google/gemini-4-safety-report.md` (structure, governance, full evaluation table, mitigations, withheld items, gaps) and `labs/google/gemini-4-safety-report-notes.md` (page-by-page running notes).
- Raw: `sources/google/gemini_4_safety_report.pdf`, `sources/google/gemini_4_safety_report.txt`.
- Headline: unmitigated model "cannot rule out" reaching the Cyber Uplift Level 1 CCL (CyScenarioBench saturated, ~16.7x estimated uplift), the CBRN Uplift Level 1 CCL for biology (expert red teaming BIO-1 91.2 / BIO-2 88.5 vs web 69.6 / 62.3), and the Stealth & Situational Awareness TCL (14/15 challenges); harmful manipulation and ML R&D CCLs not reached. Safety cases rely on classifiers/probes (adaptive single-turn OSR 0%, multi-turn 40%) and an agent CoT/action monitoring platform. Pervasive evaluation awareness (up to 94% on stealth tasks) and reduced CoT monitorability (NCRI 150.3 vs 125.8 for 3.8 Flash; combined-monitor evasion 45.5% on easy LinuxArena side tasks when prompted) are the main caveats.
- Eval family files added under `evals/` (44): cbrn-harm-journey-expert-red-teaming, cyscenariobench, cyber-uplift-cost-model, exploitbench, cwe-bench (appended), google-internal-vulnerability-benchmarks, harmful-manipulation-human-efficacy-study, harmful-manipulation-strategic-planning-redteam, manipulation-propensity-synthetic-dialogues, google-re-bench-grb, stealth-and-situational-awareness-evals, apollo-ml-rd-sabotage-capability-evals, apollo-strategic-deception-propensity-evals, agentic-task-gaming-overreach-evals, capability-benchmark-cheating-audit, rl-rollout-alignment-faking-audit, instrumental-convergence-evals, gram-gauging-realistic-agentic-misbehavior, scheming-honeypots-internal-codebases, ncri-no-cot-reasoning-index, linuxarena-control-monitor-evasion, cot-control-benchmark, cot-steganographic-evasion-eval, cot-legibility-coverage-autorater, gray-swan-shade-automated-red-teaming, gray-swan-ipi-benchmark, trajectory-labs-manual-cyber-red-teaming, misuse-safeguard-coverage-and-jailbreak-robustness-evals, healthbench, mental-health-wellbeing-evals, impossible-tasks-evaluation, ambiguous-high-risk-task-collaboration-eval, personality-evaluation-sycophancy, simpleqa-verified, aa-omniscience, facts-grounding, helpbench-privacy-safety-security-advice, over-refusal-tone-neutrality-evals, prohibited-content-safe-response-rate-evals, agentic-misuse-harness-and-computer-use-evals, indirect-prompt-injection-adaptive-redteam-suites, robotics-physical-safety-roboharm-asimov, gci-general-capability-index, evaluation-awareness-and-sandbagging-transcript-checks.
