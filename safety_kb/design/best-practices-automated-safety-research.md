# Best practices for an automated, continuously running AI-safety research engine

Fetched: 2026-10-19. Every recommendation cites the fetched source it rests on; where a
practice is our own synthesis it is labelled (ours). Unverified items are marked UNVERIFIED.
Companion files: `evals/tooling-catalog.md`, `design/quick-start-evals-for-small-models.md`,
`design/safety-engine-architecture.md` (written by another agent).

Sources read for this file (all fetched 2026-10-19):
- S1 Miller, "Adding Error Bars to Evals", arXiv 2411.00640 (abstract + HTML body).
- S2 UK AISI, "Early lessons from evaluating frontier AI systems", 2024-10-24.
- S3 UK AISI, "International evaluation best practice and open questions in AI measurement" (Network best-practice doc summary, 2026-07-23).
- S4 METR, "Guidelines for capability elicitation", 2024-03-15 (current home of the elicitation protocol).
- S5 Needham et al., "Large Language Models Often Know When They Are Being Evaluated", arXiv 2505.23836.
- S6 van der Weij et al., "AI Sandbagging", arXiv 2406.07358.
- S7 UK AISI, "Why we're working on white box control", 2025-07-10 (+ sandbagging update stub).
- S8 Anthropic, "Building and evaluating alignment auditing agents", 2025-07-24.
- S9 Anthropic, "Petri: an open-source auditing tool", 2025-10-06; Petri 3.0 docs (meridianlabs-ai.github.io/inspect_petri).
- S10 Transluce, "Eliciting language model behaviors with investigator agents", 2024-10-23 / arXiv 2502.01236.
- S11 Sakana, AI Scientist-v2 README + arXiv 2504.08066.
- S12 METR RE-Bench, arXiv 2411.15114.
- S13 Chen, Zaharia, Zou, "How is ChatGPT's behavior changing over time?", arXiv 2307.09009.
- S14 Nicholson, "Quantifying non deterministic drift in large language models", arXiv 2601.19934.
- S15 OpenAI × Apollo, "Stress Testing Deliberative Alignment for Anti-Scheming Training", arXiv 2509.15541 + antischeming.ai.
- S16 Longpre et al., "In-House Evaluation Is Not Enough: Towards Robust Third-Party Flaw Disclosure for General-Purpose AI", arXiv 2503.16861.
- S17 HarmBench paper arXiv 2402.04249; StrongREJECT arXiv 2402.10260; MASK Inspect README; SimpleQA arXiv 2411.04368.
- S18 inspect_evals READMEs/changelogs (xstest, strong_reject, sycophancy, simpleqa, mask) and Inspect docs (models, options, providers).
- S19 lm-evaluation-harness docs/decontamination.md.
- S20 arXiv RSS help page (info.arxiv.org/help/rss.html) and API basics page.
- S21 Docent docs (docs.transluce.org installation / Inspect integration).
- OpenAI Safety Evaluations Hub: fetch returned HTTP 403 — not used (UNVERIFIED).

## A. Experiment validity

1. Treat every eval run as an experiment with error bars. "Fundamentally, evaluations are
   experiments" (S1). Compute SE = sqrt(Var(s)/n) (binary: sqrt(s̄(1−s̄)/n)); report mean (SE)
   and n next to every number; 95% CI = s̄ ± 1.96·SE (S1). Our engine's report template must
   refuse to emit a headline number without n and SE (ours).
2. Use clustered standard errors when items share a source (passages, scenarios, seeds):
   clustered SEs can be "over 3X larger" than naive ones (S1). Petri seeds × turns, AgentHarm
   augmented variants of a base behaviour, SORRY-Bench mutations of a base prompt, and MASK
   belief repeats are all clustered (ours).
3. Compare models with paired differences on the same items: SE_paired = sqrt(Var(s_A−B)/n),
   "free" variance reduction when scores are positively correlated (S1). Never compare numbers
   from different `--limit` subsets or different shuffle seeds (inspect_evals truthfulqa now
   fixes a default shuffle seed of 42 precisely because `--limit` selection changed, S18).
4. Run a power analysis before building an eval: n = (z_{α/2}+z_β)²·(ω²+σ_A²/K_A+σ_B²/K_B)/δ²;
   for δ = 0.03, 80% power, α = 0.05 this needs ≈ 969 independent questions, so "new evals
   should have at least about 1,000 questions" (S1). Small suites (XSTest 450, StrongREJECT 313,
   JBB 200) can only detect large effects; say so in the report (ours).
5. Resample instead of cooling: K samples per question cut variance (K=2 → 1/3 less, K=4 → 1/2
   less); "Don't lower the sampling temperature to reduce variance" (S1). Use Inspect
   `--epochs K` (S18) and lm-eval repeats; for no-CoT MCQ use next-token probabilities (S1).
6. Establish the noise floor before claiming drift: "nondeterminism persists even at
   temperature 0.0" (S14). For every (model, eval) pair keep a repeated-run baseline (same
   prompts, same settings, ≥3 runs) and flag a change only when it exceeds that baseline by the
   paired-SE test (ours, building on S1, S14).
7. Keep held-out sets and a dev/test split for elicitation. AISI: elicitation can overestimate
   capabilities if the same tasks are used for elicitation and testing; use a dev/test split
   (S2). METR: iterate on a dev set, fix the "top five causes of failure", then "If the score on
   the dev set suite is significantly higher..., this may be an indication that the elicitation
   has been overfit" (S4). Anthropic flagged reusing one environment for dev and test as "a form
   of dev/test contamination" (S8). Rule for the autoresearch loop: any eval the manager uses to
   score an improvement proposal is frozen; proposals are developed on a separate dev slice.
8. Fix spurious failures, document real ones. METR: "Fix all spurious bottlenecks that appear
   at test time" (tool errors, formatting, truncation) and record them; "If the score is
   significantly lower after removing or redoing runs, this is evidence of gaming the
   evaluations" (S4). Our workers must log every rerun with its reason.
9. Calibrate every LLM judge against humans and report agreement. AISI autograders are
   "calibrated using scores given by human experts" and "strong claims should not be drawn
   directly from automated testing in isolation" (S2). Known agreement figures to cite: HarmBench
   classifier 93.19% vs GPT-4 88.37% on human-labelled validation (S17); StrongREJECT evaluator
   "state-of-the-art agreement with human judgments" and "existing evaluation methods
   significantly overstate jailbreak effectiveness" (S17); MASK judges 86.4% agreement on a
   150-example validation set (S17); SimpleQA label error "around 3%" (S17). Maintain a 100-200
   item human-labelled calibration set per judge type (refusal, harm, honesty) and re-check
   whenever the judge model version changes (ours).
10. Measure inter-judge agreement, not one judge. Inspect supports several graders with
    majority vote; "Prefer an odd number of graders" (S18). Pair an API judge with a local
    judge (WildGuard, HarmBench cls, StrongREJECT fine-tuned Gemma) and report Cohen's κ;
    disagreements go to the human-review queue (ours). Transluce warns that "Using an LM to
    verify ... raises concerns about reward hacking" and their GPT-4 judge "produced some false
    positives" (S10) — judges must never be the same model family as the optimised policy in an
    autoresearch loop (ours).
11. Count unscored samples. inspect_evals now excludes unparseable grader output from
    `refusal_rate` and reports `unscored_samples`; earlier versions inflated refusal rates (S18).
    Report `unscored_samples`/n for every judge-scored eval and fail the run if it exceeds a
    threshold (e.g. 2%) (ours).
12. Check for contamination and version drift of datasets. lm-eval's decontamination uses 13-gram
    overlap against training n-grams and is "disabled by default" per task (S19) — usable only
    when we control training data (our own organisms/fine-tunes). For API models, use
    post-cutoff or private held-out items and track dataset revisions (WMDP: harness README says
    4,157 items, paper says 3,668 after removals; StrongREJECT Inspect README says 324 while the
    package has 313/60) (S18, our fetches). Record the exact dataset revision hash per run.
13. Test for evaluation awareness and sandbagging explicitly. Gemini 2.5 Pro reaches AUC 0.83 at
    telling eval from deployment transcripts (humans 0.92), more easily "in agentic settings than
    in chat settings"; the authors advise tracking this capability (S5). Models "can be prompted
    ... to selectively underperform on dangerous capability evaluations" and password-locked via
    fine-tuning (S6). Petri's Sonnet 4.5 result was confounded by its "tendency to speculate about
    being tested" (S9); anti-scheming training results "cannot exclude" situational-awareness
    effects (S15). Practice: score `eval_awareness` on every transcript (Petri/Bloom have a
    dimension; add a cheap judge question elsewhere), report rates, and keep a realism filter;
    for open-weight models add a white-box check — AISI found deception probes "worked extremely
    well in detecting sandbagging" on Llama-3.1-8B though performance "deteriorate[s]" with size
    (S7).
14. Validate detectors on model organisms with known ground truth. Anthropic's auditing agents
    were scored on implanted behaviours (investigator 13% → 42% with a 10-report super-agent;
    evaluation agent "88% of runs"; red-teaming agent "7/10" quirks) and the authors note such
    organisms "may be unrepresentative of behaviors in real models" (S8). Keep a small zoo of
    organisms (emergent-misalignment LoRAs, backdoored fine-tunes) as positive controls, but
    never tune the detector on the organism it will be scored on (ours; see
    `evals/model-organisms.md`).
15. Aggregate many short agent runs rather than one long one. Anthropic: "We can run many
    parallel auditing agents from identical initial states", and aggregation fixed "fixating on
    early hypotheses" (S8). Our manager should launch N independent worker investigations per
    hypothesis and aggregate, not one long-running session (ours).

## B. Reproducibility packaging

16. Pin everything: harness version (inspect_ai, inspect_evals — several scoring bugs were fixed
    in 2026 releases, S18), judge model id and version, dataset revision, generation config
    (temperature, max_tokens, system prompt), tool/sandbox images. AISI's Network guidance:
    comparability needs "attention given to both the generation of outputs (such as inference
    settings)" and analysis (S3).
17. Ship logs, not just numbers. Every Inspect run writes `.eval` logs (`--log-dir`, default
    `./logs`); lm-eval `--log_samples --output_path` (S18, lm-eval README). Reports link to the
    log directory and a Docent collection built with
    `Docent().recursively_ingest_inspect_logs(collection_id, path)` (S21). inspect_evals itself asks
    for `.eval` logs when reporting bugs (S18).
18. Pre-register eval design. AISI "fully researches, develops, and designs its evaluations in
    advance of using them" (S2); emergent-misalignment ships `preregistered_evals.yaml`
    (repo README). For each new eval the manager writes a spec (hypothesis, metric, n, power,
    judge, pass/fail criterion) before any model is queried (ours).
19. Make runs idempotent and resumable; record reruns (see 8) and the random seeds for sample
    shuffling (`--sample-shuffle`, dataset `shuffle` seeds) (S18).

## C. Cross-model comparison fairness

20. Same prompts, same settings, same judge, same day. Chen et al. observed GPT-4 fall from 84% to
    51% on a prime/composite task between March and June 2023 and concluded there is a "need for
    continuous monitoring of LLMs" (S13). Comparisons across providers must use the same
    inference settings where possible and declare where they could not (S3).
21. Elicit before you compare. AISI: eliciting full capability is "an open scientific question"
    and evaluators should "iterate on capability elicitation" (S2, S3); METR requires at least
    "basic finetuning for instruction following, tool use, and general agency" for open models
    and a reference-model baseline (S4). For API vs open-weight comparisons, state the elicitation
    tier used for each (ours).
22. Pair every refusal metric with an over-refusal metric (XSTest safe / OR-Bench-Hard next to
    StrongREJECT / HarmBench) and every capability number with a human or reference-model
    baseline (S2; RE-Bench used 71 expert attempts and best-of-k at fixed budgets, S12) (ours).
23. Use fixed budgets. RE-Bench compares at 2h/8h/32h budgets with best-of-k (S12); METR counts
    token budgets (S4). Report tokens, wall-clock and attempts per task for every agentic eval.
24. Report by model version string and date; treat a provider alias (e.g. "latest") as a
    different model each day (S13, ours).

## D. Cost control

25. Start every new eval with `--limit 10` (lm-eval README recommends `--limit 10` to "confirm
    answer extraction and scoring"; inspect_evals examples use `--limit 10 --sample-shuffle`;
    Petri docs: "a single tag or a few IDs, plus `--limit 5`") (S18, S9).
26. Prefer local judges for volume and API judges for calibration: WildGuard 7B, HarmBench 13B
    cls, StrongREJECT fine-tuned Gemma-2B, SORRY-Bench Mistral-7B judge all run on one A6000
    (evals/tooling-catalog.md). Budget API judges per run; MASK costs ≈ 8.9 calls/record (S18).
27. Know the price of agentic pipelines: AI Scientist-v2 "typically costs around $15–$20 per
    run" for experiments plus ≈ $5 writeup (S11); Petri full default set is "a few hours and a
    non-trivial API spend" (S9). The manager keeps a per-task token ledger and a daily cap (ours).
28. Use `--max-connections`/`--max-samples` and vLLM batching ("vLLM automatically handles
    batching", Inspect providers page) rather than more GPUs (S18).

## E. Reporting standards

29. Every report states: model id + version + date; eval name + harness version + dataset
    revision; n, mean, SE/CI, clusters; judge id + calibration figure; `unscored_samples`;
    elicitation tier; eval-awareness rate; known limitations. AISI Network guidance: limitations
    "should be clear in any reporting" (S3); Petri: "Read the transcripts closely" and metrics are
    "a starting point" (S9).
30. Separate "pipeline smoke test" from "result". Small-model runs (0.5B-3B) mostly validate the
    pipeline; label them as such so they never enter cross-model claims (ours).
31. Include transcripts/excerpts for every flagged behaviour and a link to the Docent collection
    (S9, S21).
32. Automated reviewer: AI Scientist-v2 uses an LLM reviewer (`--model_review`) and a VLM figure
    loop; only 1 of 3 of its papers exceeded a workshop acceptance threshold (S11). Use an
    automated reviewer as a gate for format/statistics/claims-vs-evidence, with a human gate for
    anything that becomes a cross-model safety claim (ours).

## F. Safety of the engine itself

33. Sandbox all model-written code: "This codebase will execute Large Language Model
    (LLM)-written code ... run this within a controlled sandbox environment (e.g. a Docker
    container)"; risks include "dangerous packages, uncontrolled web access, and unintended
    process spawning" (S11). Inspect sandboxes and ControlArena assume Docker (control-arena
    README).
34. Keep harmful-content artefacts out of git and out of prompts to unrelated workers; treat
    downloaded eval data as untrusted (CONVENTIONS.md; agentharm licence restricts use to AI
    safety/security, S18).
35. Never put API keys in the knowledge base (CONVENTIONS.md).

## G. Responsible disclosure

36. Follow coordinated flaw disclosure: standardised "AI flaw reports and rules of engagement
    for researchers", provider "flaw disclosure programs ... with legal safe harbors", and
    infrastructure to route reports to affected parties, since flaws "can transfer across
    different providers' GPAI systems" (S16). Practice (ours): a finding on an API model goes to
    that provider's disclosure channel before publication; jailbreak strings and CBRN-adjacent
    completions are stored only in the restricted `sources/` area and summarised, not quoted, in
    reports; open-weight findings are reported with hashes of prompts rather than prompts when
    harmful.
37. Canada's "selective disclosure" for CBRN/cyber datasets (S3) is the template for our own
    tiers: public (method + aggregate), restricted (prompts), private (completions).

## H. Keeping the eval knowledge base current

38. Poll arXiv daily via RSS: `https://rss.arxiv.org/rss/cs.AI`, combinable as
    `https://rss.arxiv.org/rss/cs.ai+q-bio.NC` ("Limit 2000 results"); Atom at `/atom/`; "Feeds
    are updated daily at midnight Eastern Standard Time" (S20). Categories for us: cs.AI, cs.CL,
    cs.CR, cs.LG, cs.CY. For search use `http://export.arxiv.org/api/query?search_query=...`
    with `start`/`max_results` (S20). Keyword filters: jailbreak, refusal, sandbagging, scheming,
    deception, sycophancy, alignment faking, evaluation awareness, model organism, control
    protocol, SAE, probe, steering, emergent misalignment, benchmark contamination (ours).
39. Watch eval repos for releases and changelogs: inspect_evals (184 evals; per-eval CHANGELOG
    sections record scoring fixes), inspect_ai, lm-evaluation-harness, inspect_petri /
    petri_bloom, control-arena, HarmBench/strong_reject/jailbreakbench, garak, promptfoo,
    PyRIT, SAELens pretrained list (new Qwen SAEs), TransformerLens bridge architectures (S18,
    tooling-catalog). GitHub API `pushed_at` and release endpoints are enough; re-run the
    `--limit 10` smoke suite after any harness upgrade (ours).
40. Watch lab channels: Anthropic Alignment Science blog (alignment.anthropic.com) and
    anthropic.com/research, OpenAI safety pages (Safety Evaluations Hub blocked to our fetcher —
    UNVERIFIED), Google DeepMind FSF reports, AISI blog/research (aisi.gov.uk), METR
    (metr.org, evaluations.metr.org), Apollo (apolloresearch.ai), Redwood, Transluce
    (transluce.org), Meridian Labs (Petri/Bloom docs). Model cards/system cards for each new
    release (ours).
41. Watch Hugging Face for model and dataset releases via the API (`/api/models/<id>`,
    `/api/datasets/<id>` return `license`, `gated`, `lastModified`); Qwen/Kimi/GLM/DeepSeek org
    listings; gated datasets (wildjailbreak, sorry-bench) need one-time acceptance (our fetches).
42. Re-run the small-model smoke suite (design/quick-start-evals-for-small-models.md) nightly as
    a canary for pipeline drift, and the full battery on each new model version; store results
    with the version string so that regression diffs are paired (S1, S13).
