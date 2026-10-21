# Irregular (formerly Pattern Labs)

- Website: https://www.irregular.com (research index: https://www.irregular.com/research)
- Type: for-profit "frontier security lab" (self-description); CEO Dan Lahav (named in a Feb 2026 Science policy forum item on the research page). The former name "Pattern Labs" does not appear on fetched pages: UNVERIFIED from primary sources (it is stated in the task brief and in press, not on irregular.com).
- Fetched: 2026-10-19. Raw copies: `/data/haokun_test/neurico/safety_kb/sources/irregular/`

## What they evaluate
Offensive cyber capabilities and offensive-misuse potential of frontier models, pre-release, for most frontier labs. Also AI-security research (agent containment, prompt injection, emergent offensive behaviour of agents).

## Methodology (from the research index and individual posts)
- **SOLVE v0.5** (2025-02-10): "Scoring Obstacle Levels in Vulnerabilities & Exploits", a difficulty framework for end-to-end vulnerability discovery and exploit challenges. Four 0-10 components (code analysis difficulty, vulnerability discovery difficulty, exploit development difficulty, expert knowledge) combined with a smooth-maximum; bands Easy 0-3.9, Medium 4-6.9, Hard 7-8.9, Expert 9-10. Public, CC BY-SA 4.0, with spec, calculator and a human baseline from DownUnderCTF 2023. Explicitly "not an objective score" but a judgement framework. **SOLVE+ v0.5** (2026-09-03) extends to multi-step scenarios scored per step and in aggregate.
- **Atomic Challenges / Atomic Tasks**: bounded single-skill tasks (vulnerability research and exploitation, network attack simulation, evasion). 22 challenges used for GPT-6 Astra.
- **CyScenarioBench** (2025-12-05): scenario-based benchmark for full attack workflows; 10 long-horizon scenarios used for Astra; Google DeepMind used it in its Frontier Safety Framework review of Gemini 4 Argon (per Irregular's 2026-10-13 post).
- **FrontierCyber** (2026-06-22): vulnerability discovery and exploitation against real, unmodified systems ("mobile devices, hosted software, databases, networks, and routers"); no planted vulnerabilities; success verified by hidden flag/canary; difficulty predicted before runs and binned Easy/Medium/Hard/Elite; partial progress credited; a scoring agent calibrated to expert grading; results tied to dated snapshots. 226 challenges in the Astra run (7 Elite).
- **Expected cost per success** as a complementary metric to success rate (2025-12-18); inference-scaling work with UK AISI (2026-03-05).
- **Containment challenges** (2026-10-05): tests that evaluation environments hold before capability testing; an Aug 2026 post ("Addressing Recent Incidents") reports an evaluation-environment incident and resulting containment/monitoring changes.
- Evaluations "in sandboxed environments without public internet access" (Astra system card 10.1.2.6).

## Open-source tools / datasets
- SOLVE specification and calculator: public (CC BY-SA 4.0), linked from https://www.irregular.com/research/introducing-solve.
- FrontierCyber, CyScenarioBench, Atomic suites: no open-source release described on fetched pages (held private, consistent with contamination concerns).
- No GitHub organisation found on fetched pages.

## Pre-deployment / early access (table from research index, all https://www.irregular.com/research/...)
| Lab | Model | Date | Source | What they found |
|---|---|---|---|---|
| Anthropic | Claude 3.7 Sonnet | 2025-02-25 | claude-3-7-sonnet-evaluation | full kill-chain evaluation using SOLVE |
| OpenAI | o3, o4-mini | 2025-04-17 | openais-o3-and-o4-mini-security-evaluation | "do not pose a significant cyber-offensive risk"; cited in the o3/o4-mini system card; "In collaboration with" OpenAI |
| Anthropic | Claude Sonnet 4 / Opus 4 | 2025-07-15 | 48 challenges across web, crypto, binary, RE, network | - |
| OpenAI | GPT-5 | 2025-08-07 | "Irregular x OpenAI"; "Irregular GPT-5 Assessment" is one of three third-party reports OpenAI lists as published after its confidentiality/accuracy review (openai.com/index/strengthening-safety-with-external-testing/) | cited in GPT-5 system card |
| Anthropic | Claude Sonnet 4.5 | 2025-09-30 | evaluation "done with Anthropic" | - |
| OpenAI | GPT-5.2 Thinking, GPT-5.2-Codex, GPT-5.3-Codex, GPT-5.4-Thinking, GPT-5.5 | Dec 2025 - Apr 2026 | per-model posts | strong on bounded tasks; limited on end-to-end scenarios |
| Meta Superintelligence Labs | Muse Spark 1.0 / 1.1 | 2026-04-15, 2026-07-09 | per-model posts | limited on end-to-end CyScenarioBench |
| OpenAI | GPT-5.6 Sol | 2026-06-26 | "First FrontierCyber use in a partner frontier assessment" | responsibly disclosed vulnerabilities; limited vs hardened targets |
| Zhipu | GLM-5.2 | 2026-07-16 | open-weight | no multi-stage solves |
| Anthropic | Claude Opus 5, Opus 5.5, Mythos 5/5.1, Sonnet 5 | 2026-07-24, 2026-09-22 | per-model posts | Opus 5.5 ~28% gain over Opus 5 on 10-challenge CyScenarioBench subset |
| Moonshot | Kimi K3 | 2026-08-19 | open-weight | first open-weight model to solve CyScenarioBench challenges |
| OpenAI | GPT-6 Astra | 2026-09-03 | assessing-gpt-6-astra; system card sec. 10.1.2.6 | FrontierCyber 86/226 vs 34/226 (GPT-5.6 Sol); Easy 14%->63%, Medium 15%->30%, Hard 17%->39%; 0/7 Elite; CyScenarioBench 9/10 solved at least once, avg success 59% (+32 pp); Atomic 20/22; cost per success ~1/3 of Sol; three zero-days (open-source database memory corruption to native code exec; browser JS-engine memory corruption with sandbox disabled; mobile SMS permission flaw) under responsible disclosure; "no successful attacks on fully hardened targets" |
| Google DeepMind | Gemini 4 Argon | 2026-10-13 | assessing-gemini-4-argon | GDM used CyScenarioBench in its FSF review; large gain on full attack chains |
| Reflection | Beam (open-weight) | 2026-10-16 | assessing-reflection-beam | no end-to-end scenario solved |

## Why they are trusted / credibility signals
- Breadth: the only evaluator in this knowledge base with published pre-release cyber assessments for OpenAI, Anthropic, Google DeepMind and Meta in 2025-2026, plus open-weight models (Zhipu, Moonshot, Reflection).
- Public methodology (SOLVE, cost-per-success, FrontierCyber design) and a public "Best Practices for Evaluations and Evaluation Suites" series (2024-10-02).
- Security-domain credibility: its evaluation system found three zero-days in Soft Serve and QuickJS (2025-12-02) and multiple zero-days during the Astra assessment, all handled via responsible disclosure; co-authored an "AI Security Priorities" agenda with RAND (2026-08-24); joint work with UK AISI on inference scaling (2026-03-05) and with Wiz Research (2026-01-29).
- Named by OpenAI as one of three assessors whose reports were published after review (METR, Apollo, Irregular).

## Notable findings (numbers)
See the table. Headline: GPT-6 Astra more than doubled FrontierCyber solves (86 vs 34 of 226) and OpenAI classified Astra as reaching its "Critical" cyber threshold (system card sec. 10.1.2); Irregular's own framing is that offensive use "could pose meaningful risk to real-world systems" while no Elite or fully hardened target fell.

## Publication norms
- Reports are published on irregular.com with lab acknowledgement; OpenAI's contract terms (review and approval before publication) apply to OpenAI engagements (see `lab-statements-on-third-party-testing.md`). Irregular's own pages do not describe NDA/redaction terms: UNVERIFIED.
- Vulnerability details withheld pending patches ("Technical details are omitted because some vulnerabilities may still be present in deployed systems").

## Sources (fetched 2026-10-19)
- https://www.irregular.com/ ; /about ; /research ; /research/assessing-gpt-6-astra ; /research/frontiercyber ; /research/introducing-solve ; /research/openais-o3-and-o4-mini-security-evaluation
- https://deploymentsafety.openai.com/gpt-6-astra (sec. 10.1.2.6)
- https://openai.com/index/strengthening-safety-with-external-testing/ (via web.archive.org)

## Gaps / UNVERIFIED
- Funding round size and investors (press reports of an $80M round) not on fetched pages.
- Access type for each engagement (pre-release checkpoint vs helpful-only) is stated only in lab system cards, not in Irregular's posts.
- Page metadata on irregular.com shows "Oct 16, 2026" for many older posts; body dates were used here.
