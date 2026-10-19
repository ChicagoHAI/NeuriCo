# OpenAI Safety Evaluations Hub

Fetched: 2026-10-19.

## Status: the standalone hub is gone; it now redirects to the Deployment Safety Hub

- `https://openai.com/safety/evaluations-hub/` returns HTTP 403 to non-browser clients. The Wayback
  snapshot of 2026-10-12 shows the URL **301-redirecting to https://deploymentsafety.openai.com/**
  (the system-card hub).
- The last standalone snapshot (2026-02-24, saved as
  `sources/openai/openai-com/safety-evaluations-hub-feb2026.html` / `.txt`) still carried
  "Last updated: August 15, 2025" and a one-entry changelog: "August 15, 2025: We updated the hub to
  include results for GPT-5 and gpt-oss models, to feature our new Production benchmarks, and to
  provide more detailed information on StrongReject results, disaggregating results by category."
- Consequence: **the hub never contained a model newer than GPT-5 / gpt-oss (Aug 2025).** Every
  2026 number for GPT-5.x and GPT-6 exists only inside system cards (see `system-cards.md`). The
  hub's own promise — "this hub allows us to share metrics on an ongoing basis ... We will update the
  hub periodically as part of our ongoing company-wide effort to communicate more proactively about
  safety" — was not kept after August 2025.
- The hub's backing data file `https://openai.com/backend/safety-data.json` (5,018 bytes) was
  recovered from Wayback (the 2026-02-24 and 2026-10-12 snapshots are byte-identical) and saved to
  `sources/openai/openai-com/safety-data.json`. **That file is the authoritative record of every
  number the hub ever displayed**; this page summarises its structure rather than reprinting the
  per-category score tables.

Scope caveat printed on the hub: "This page currently describes text-based safety performance on
four types of evaluations"; "These do not reflect the full safety efforts and metrics that are used
at OpenAI, and are only intended to provide a snapshot", to be read "alongside ... our System Cards,
Preparedness Framework assessments, and specific research releases".

## Complete inventory of the hub's evaluations (from safety-data.json)

49 series in four families. Model coverage is uneven: 12 models (GPT-4-turbo → GPT-4.1 / o1 / o3 /
o3-mini / o4-mini / GPT-4.5 / GPT-4o variants) for the older sets, 14 for instruction-hierarchy
protection and PersonQA, 18 for SimpleQA, and only 8 for the newest "Detailed" sets (which are the
only ones that include gpt-5-thinking, gpt-5-main, gpt-5-main-mini, gpt-5-thinking-mini,
gpt-5-thinking-nano, gpt-oss-120b, gpt-oss-20b).

### 1. Disallowed content
- Metric definitions (verbatim): autograded, "focus primarily on the metric not_unsafe, which
  verifies that the model did not produce unsafe output according to OpenAI policy and Model Spec";
  the complementary metric is `not_overrefuse` (benign request not refused).
- Three generations: **Standard Refusal Evaluation** — described by OpenAI as "relatively saturated
  ... no longer provides a useful signal"; **Challenging Refusal Evaluation**; and **Production
  Benchmarks**, "an updated version of our Challenging refusal evaluation ... highly multiturn".
- Series present: overall `not_unsafe` and `not_overrefuse` for Standard; overall `not_unsafe` for
  Challenging; plus per-policy breakdowns across the usual OpenAI policy taxonomy (illicit
  violent/non-violent, extremist propaganda, hate and hate-threatening, harassment-threatening,
  self-harm intent/instructions, sexual and sexual/minors, restricted and semi-restricted personal
  data, regulated advice) for Standard, Challenging and the "Detailed production evaluation" set.
- Level: Standard `not_unsafe` sits at 0.97–0.99 for all 12 listed models while `not_overrefuse` sits
  far lower (0.65–0.80) — the saturation OpenAI cites, and the main reason the Production Benchmarks
  replaced it. The GPT-5-era "Detailed production" series show much more spread (roughly 0.65–0.98
  depending on policy area), i.e. the harder set does discriminate. Exact values per model and policy:
  `safety-data.json`.

### 2. Jailbreaks
- **StrongReject** (academic benchmark, Souly et al.): metric `goodness@0.1`, defined on the hub as
  the score computed "which [measures] a model's resistance against common attacks from the
  literature"; 12 models, plus a 2025-08 addition of four category-disaggregated "Detailed
  StrongReject" series (illicit non-violent, illicit violent, abuse/disinformation/hate, sexual)
  covering the GPT-5 and gpt-oss models, where scores cluster 0.93–0.999.
- **Human-sourced jailbreaks**: metric `not_unsafe`; "Prompts collected from human red teaming";
  12 models.

### 3. Hallucinations
- **SimpleQA** — "A diverse dataset of four thousand fact-seeking questions with short answers and
  measures model accuracy for attempted answers"; two series, `accuracy` and `hallucination rate`;
  18 models, no browsing ("The evaluation results below represent the model's base performance
  without the ability to browse the web").
  Latest hub values: gpt-5-thinking accuracy 0.55 / hallucination 0.40; gpt-5-main 0.46 / 0.47;
  gpt-5-thinking-mini 0.22 / 0.26; gpt-5-thinking-nano 0.11 / 0.31; gpt-oss-120b 0.17 / 0.78;
  gpt-oss-20b 0.17 / 0.91.
- **PersonQA** — "a dataset of questions and publicly available facts about people"; `accuracy` and
  `hallucination rate`; 14 models; latest are the gpt-oss pair (120b 0.298 / 0.491; 20b 0.155 / 0.532)
  — no GPT-5 entry.

### 4. Instruction hierarchy
- Hub definition: the model should "follow the instructions in the system message over developer
  messages, and instructions in developer messages over user messages"; "To pass this eval, the model
  must choose to follow the instructions in the highest priority message."
- Series: **message-conflict** (System↔User, Developer↔User, System↔Developer), 12 models each;
  **tutor jailbreak** (system-message and developer-message variants — "The model is instructed to be
  a math tutor and not give away the solution, and the user attempts to trick the model into giving
  away the solution"), 12 models; **phrase protection** and **password protection**, each in
  user-message and developer-message variants ("the model must not output a specific phrase or a
  bespoke password which are specified in a system message"), 14 models including gpt-oss-120b
  (0.909–1.00 across the four) and gpt-oss-20b (0.661–0.947).

## What is *not* on the hub

Everything that drives 2026 deployment decisions: Production Benchmarks for GPT-5.4 and later, U18
evaluations, agentic safe completions, prompt-injection/GPT-Red results, HealthBench and
MentalHealthBench, the alignment suite (auto-review, warnings, honeypot, coding deception, broken
search tool, realistic work environments, agent-to-agent communication, deployment simulation),
CoT monitorability and controllability, monitor-evasion and sandbagging, every Preparedness
capability eval, misuse-monitor recall, and all third-party results. There is also no machine-readable
export for those: the system cards are PDFs/HTML, and the "Download all data" affordance belongs to
the retired hub.

Related live surfaces that partly replace it: the Deployment Safety Hub (per-model cards, with an
RSS feed at https://deploymentsafety.openai.com/rss.xml and a sitemap listing every card section),
and https://openai.com/safety/ (links to cards and policies, no metrics).
