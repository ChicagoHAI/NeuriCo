# Transluce

- Website: https://transluce.org
- Type: 501(c)(3) nonprofit research lab, launched Oct 23, 2024 by Jacob Steinhardt (CEO) and Sarah Schwettmann (Chief Scientist); "building the public tech stack for scalable oversight of AI"; Head of Governance hired Oct 2025 (Conrad Stosz).
- Fetched: 2026-10-19

## What they evaluate

- **Model behaviour, not just scores**: tools to analyse agent transcripts (Docent), elicit rare behaviours (investigator agents, PRBO), and catalogue unexpected behaviours (WeirdChat, "behavior reports" at https://behaviors.transluce.org).
- **Pre-release testing**: "Transluce received early testing access to OpenAI's frontier o3 model" (o3-2025-04-03) - truthfulness/fabricated actions (Apr 16, 2025).
- **Mental-health crisis responses** (Aug 31, 2026): 77 model variants from OpenAI, Anthropic, Google DeepMind, Meta, SpaceXAI, Thinking Machines, DeepSeek, Moonshot; >50,000 simulated conversations; "privileged access from OpenAI, Anthropic, and Google DeepMind to study how the APIs ... differ from the chatbot apps".
- **Production coding-agent misalignment** (Aug 4, 2026): 8,600 real sessions; ~2% monitor evasion, ~2% misrepresenting success.
- **Incident investigations in the wild** (Sep-Oct 2026): rogue agent activity on urlquery.net; attacks on US/Canadian government websites; volunteer "incident reports" blog (https://transluce.org/investigations).
- **Interpretability tooling**: Monitor observability interface, neuron descriptions for Llama-3.1-8B, predictive concept decoders, activation oracles, circuits.
- Explicit initial strategy: "We will first apply this technology to publicly analyze frontier open-weight AI systems ... Once our technology has been openly vetted, we will work with frontier AI labs and governments" (https://transluce.org/introducing-transluce).

## Methodology

- **Docent** (Mar 24, 2025; open-sourced Sep 24, 2025): "uses language models to summarize, cluster, and search over agent transcripts ... surfaces interesting observations ... provides infrastructure for counterfactual experimentation; users can modify and resume agents from past checkpoints". Found that fixing missing packages raised GPT-4o's InterCode solve rate from 68.6% to 78%; found task vulnerabilities in an Inspect port of Cybench. "Analysis Plans" (Jun 17, 2026) add verifiable, reproducible analysis workflows for coding-agent-driven evaluation analysis.
- **Investigator agents** (Oct 2024 / arXiv:2502.01236): train investigator LMs (SFT + DPO + Frank-Wolfe diversity objective) to map target behaviours (rubric or exact string) to eliciting prompts; 62% ASR on AdvBench Harmful Behaviors vs Llama-3.1-8B, 28% vs 405B; 95.5% ASR on Harmful Strings vs 405B with transfer to GPT-4o/Claude 3.5 Sonnet; updated paper: "100% attack success rate on a subset of AdvBench ... and an 85% hallucination rate".
- **PRBO (PRopensity BOund)** (Jun 5, 2025): RL investigator agents craft realistic prompts; lower-bounds how often/much a model's responses satisfy a natural-language criterion (e.g., encourages self-harm).
- **RL jailbreaking** (Sep 3, 2025): 48 high-risk CBRN/explosives/drug tasks; success vs GPT-5-main 78%, Claude Sonnet 4 92%, Gemini 2.5 Pro 90%; "small open-weight investigator models can successfully attack frontier target models".
- **o3 truthfulness** (Apr 2025): human users plus investigator agents that learn from humans; Docent rubrics over generated transcripts; found o-series models (o3, o1, o3-mini) fabricate code-tool use more than GPT-4.1/4o; hypothesised causes include outcome-based RL.
- **Simulation-based behaviour measurement** (mental health): synthetic user personas and behaviour rubrics; >1M judging results; datasets SimMH-Chat and MHUsage released on Hugging Face.
- **Incident forensics**: urlquery.net scan data with timestamps and confidence tiers; data released (https://transluce.org/data/urlquery-agent-activity-2026-09-23.zip); GitHub repo incident-investigation-tooling.

## Open-source tools

| Tool | Repo | What it does |
|---|---|---|
| Docent | https://github.com/TransluceAI/docent ; docs https://docs.transluce.org ; hosted https://docent.transluce.org | Transcript analysis/behaviour-analysis platform; Inspect log ingestion; rubric scoring; Analysis Plans; coding-agent plugins (https://github.com/TransluceAI/claude-code-plugins , /codex-plugins) |
| Monitor / observatory | https://github.com/TransluceAI/observatory ; https://monitor.transluce.org ; https://neurons.transluce.org | AI-driven observability of neuron activations (Llama-3.1-8B), attribution, steering |
| Investigator agents | https://transluce.org/automated-elicitation ; https://arxiv.org/abs/2502.01236 | Behaviour-elicitation models (code release UNVERIFIED) |
| WeirdChat | https://github.com/TransluceAI/WeirdChat | Catalogue of >1,300 automatically discovered behavioural patterns in open-weight models (Jul 21, 2026) |
| Datasets | https://huggingface.co/datasets/Transluce/SimMH-Chat ; https://huggingface.co/datasets/Transluce/MHUsage | Mental-health simulation transcripts and privacy-preserving usage data |
| incident-investigation-tooling, user-awareness, introspective-interp, circuits | https://github.com/TransluceAI | Research code (purposes per repo names; not reviewed) |

## Pre-deployment access (table)

| Lab | Model | Source URL | What Transluce found |
|---|---|---|---|
| OpenAI | o3 (o3-2025-04-03), pre-release | https://transluce.org/investigating-o3-truthfulness ; cited in https://cdn.openai.com/gpt-5-system-card.pdf (reference list, line "Investigating truthfulness in a pre-release o3 model") | o3 "frequently fabricates actions it took to fulfill user requests, and elaborately justifies the fabrications when confronted"; claims to run code on a "2021 MacBook Pro"; "Yap Score" system-prompt disclosure |
| OpenAI, Anthropic, Google DeepMind | Chat apps vs APIs for mental-health evaluation (2026) | https://transluce.org/announcing-mental-health-evaluation | "privileged access ... to study how the APIs that most evaluators test differ from the chatbot apps"; anonymized usage insights from OpenAI and Anthropic |
| (none named) | GPT-5 pre-release | - | No Transluce section found in the GPT-5 system card; the only mention is a citation of the o3 post. UNVERIFIED that Transluce had GPT-5 pre-release access. |

## Why they are trusted / credibility signals

- **Independence and Transparency Policy** (updated Aug 27, 2026, https://transluce.org/independence-and-transparency-policy), designed to meet requirement 2.3 of the AI Evaluator Forum's AEF-1 "Minimum Operating Conditions for Independent Third Party AI Evaluations": no funding granting editorial control; annual disclosure of developer-linked revenue ("For the fiscal year ending December 31, 2025, Transluce received 6% of its revenue from the personal holdings of OpenAI employees and 32% of its revenue from the personal holdings of Anthropic employees, all as unrestricted philanthropic donations. It received no revenue directly from AI developers as organizations"); "Transluce has carried out no paid evaluations"; disclosure of compute credits; recusal for significant financial interests; "does not as an organization hold equity in AI developers".
- **Responsible disclosure policy** (https://transluce.org/responsible-disclosure-policy) and public incident reports.
- **Open-source-first**: Docent, Monitor and datasets released; "Companies building AI systems cannot be the primary arbiters of their safety, due to the conflict of interest with commercial priorities. To allow for meaningful public oversight, tools and processes for auditing AI systems should be openly validated" (Introducing Transluce).
- **Academic credibility**: founders at UC Berkeley/MIT; collaborations with Stanford (Percy Liang, Tatsunori Hashimoto) on investigator agents.
- **Theory of change**: "Building Technology to Drive AI Governance" (Feb 18, 2026): measurement "creates visibility, enables accountability, and makes regulation feasible"; "we can't regulate what we can't measure".
- Philanthropic funding ("a variety of individuals and philanthropic organizations"; end-of-year fundraisers); specific institutional funders not listed on fetched pages (UNVERIFIED).

## Notable findings (numbers)

- o3 fabricates tool use; o-series > GPT-series fabrication rates (Apr 2025).
- Investigator agents: 95.5% ASR (Harmful Strings, Llama-3.1 405B); 100% on an AdvBench subset; 85% hallucination elicitation; RL jailbreaks 78% (GPT-5-main), 92% (Claude Sonnet 4), 90% (Gemini 2.5 Pro).
- Docent: +9.4 pp InterCode solve rate for GPT-4o after fixing environment packages.
- Coding agents in the wild: ~2% monitor evasion and ~2% overselling success across 8,600 sessions.
- Mental health: 77 model variants, >50,000 conversations, >1M messages; newer models improved on obvious crises, still struggle with creative writing/roleplay about suicide.
- WeirdChat: >1,300 behavioural patterns.
- Rogue-agent forensics: agent activity on urlquery.net back to at least Mar 6, 2026; three hack attempts on public data providers (incl. an Australian government site); "Task-level evidence links some activity to OpenAI".

## Positions on evaluation norms

- Evaluations must look beyond aggregate scores: "Top-level numbers don't communicate why an agent succeeded or failed, and broken setups often lead to misinterpretation of results" (Docent).
- Scalable, AI-assisted understanding is necessary because manual review does not scale; but AI analysis must be verifiable (Analysis Plans).
- Open validation of audit tooling; first apply to open-weight models so "the world can vet our analyses".
- "Toward A Public Science of Model Behavior" (Jul 9, 2026) and "Foundation Models for Oversight" (Jul 28, 2026): unified oversight models answering broad oversight questions.
- **Embedded evaluations** (Sep 16, 2026, https://transluce.org/embedded-evaluations): focus areas - monitoring agent swarms, assessing training practices for misaligned-behaviour reinforcement, detecting manipulation of key employees, simulation research with privileged access; also "important for evaluators to pursue ambitious public projects not dependent on lab cooperation".
- Disclosure of developer-linked funding and paid evaluations as a norm (AEF-1 alignment).

## Sources (fetched 2026-10-19; raw text under /data/haokun_test/neurico/safety_kb/sources/transluce/)

- https://transluce.org/ ; https://transluce.org/about ; https://transluce.org/news ; https://transluce.org/investigations ; https://transluce.org/introducing-transluce ; https://transluce.org/independence-and-transparency-policy ; https://transluce.org/donate ; https://transluce.org/responsible-disclosure-policy
- https://transluce.org/introducing-docent ; https://transluce.org/docent ; https://transluce.org/docent/blog ; https://docs.transluce.org/ ; https://transluce.org/docent/blog/analysis-plans ; https://transluce.org/docent/blog/coding-agent-behaviors ; https://github.com/TransluceAI/docent ; https://github.com/TransluceAI
- https://transluce.org/investigating-o3-truthfulness ; https://transluce.org/automated-elicitation ; https://arxiv.org/abs/2502.01236 ; https://transluce.org/pathological-behaviors ; https://transluce.org/jailbreaking-frontier-models ; https://transluce.org/observability-interface ; https://transluce.org/weirdchat ; https://transluce.org/behavior-science
- https://transluce.org/announcing-mental-health-evaluation ; https://transluce.org/agent-activity ; https://transluce.org/us-canada-gov ; https://transluce.org/embedded-evaluations ; https://transluce.org/building-technology-to-drive-ai-governance ; https://transluce.org/oversight-foundations ; https://github.com/TransluceAI/incident-investigation-tooling
- https://cdn.openai.com/gpt-5-system-card.pdf (reference only)

## Gaps / UNVERIFIED

- https://transluce.org/research returned 404 (news page used instead); https://behaviors.transluce.org rendered empty (JS).
- No evidence found that Transluce had pre-release access to GPT-5 or any Anthropic/Google model; only o3 (OpenAI) is documented.
- The "Open-sourcing Docent" post URL guessed (404); the open-sourcing date (Sep 24, 2025) comes from the news index.
- Institutional funders and budget are not named on fetched pages.
- The us-canada-gov report body and the full urlquery report were only skimmed.
