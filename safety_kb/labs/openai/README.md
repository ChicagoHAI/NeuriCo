# OpenAI — lab index

Fetched: 2026-10-19. Scope: how OpenAI evaluates and monitors AI safety, as of 2026-10-19.

## Files

| File | Contents |
|---|---|
| `system-cards.md` | Per-card inventory of every evaluation that is actually run: eval name, what it measures, metric, result, who ran it, section/page ref; plus a section on ongoing/post-deployment monitoring. Covers GPT-6 Astra (+ GPT-6 Sol/Luna, dots), GPT-6.1 Sol, GPT-6 October, GPT-5.6, GPT-5.6 August, GPT-5.5, GPT-Rosalind-5.5, GPT-5.4 Thinking, GPT-5.3-Codex, GPT-Live-1.1, ChatGPT Images 2.5, GPT-5. |
| `preparedness-and-process.md` | Preparedness Framework v2 (tracked/research categories, High & Critical thresholds, safeguard claim families, Capabilities/Safeguards Reports, SAG → Leadership → SSC governance, cadence, fast track), the Frontier Governance Framework (TFAIA/EU AI Act mapping, 4 risk categories × 3 tiers, incident response, model reporting), safety-cases-for-training guidelines, observed 2026 triggers, and all external involvement incl. access terms and the 2026 third-party testing incidents. |
| `evaluations-hub.md` | The Safety Evaluations Hub: now redirects to the Deployment Safety Hub; complete inventory of its 49 series in 4 families with metric definitions and the latest numbers it ever showed (GPT-5/gpt-oss era), plus the recovered backing JSON. |
| `open-tools-and-methods.md` | OpenAI-released evals/datasets/tools usable on other models; third-party benchmarks the cards run; documented-but-unreleased methods; notes on what is runnable on 0.5B–7B open models. |
| `gaps.md` | Unquantified figures, unpublished thresholds, internal-only evals, thinly reported areas, third-party coverage gaps, and 12 complementary evaluations a third party could run. |

Evaluation-family notes live in `../../evals/` (see "Eval files touched" below).
Raw downloads live in `../../sources/openai/` (PDFs with `.txt` pdftotext copies; Wayback HTML with
`w3m` text copies in `sources/openai/openai-com/`; GitHub READMEs in `sources/openai/github/`).

## URLs fetched successfully

Deployment Safety Hub (system cards; PDF where available):
- https://deploymentsafety.openai.com/ (index), /rss.xml, /sitemap.xml
- /gpt-6-astra + /gpt-6-astra/gpt-6-astra.pdf
- /gpt-6-1-sol + PDF; /gpt-6-october + PDF
- /gpt-5-6 + PDF; /gpt-5-6-preview + PDF; /gpt-5-6-august-update + PDF
- /gpt-5-5 + PDF; /gpt-rosalind-5-5 + PDF; /gpt-5-4-thinking + PDF; /gpt-5-3-codex + PDF
- /gpt-live-1-1 + PDF; /gpt-live + PDF; /chatgpt-images-2-5 + PDF
- /gpt-5, /gpt-5-1, /gpt-5-2, /o3 (HTML only — these have no PDF at the same path)

Frameworks and PDFs:
- https://cdn.openai.com/pdf/18a02b5d-6b67-4cec-ab64-68cdfbddebcd/preparedness-framework-v2.pdf
- https://cdn.openai.com/pdf/e37d949b-8c9f-4d76-b99e-4272f4631a7e/openai-frontier-governance-framework.pdf
- https://cdn.openai.com/pdf/67869394-cb91-4c12-888c-5cbd85c7814c/OpenAI-Hugging-Face%20Incident-Technical-Report.pdf

openai.com pages (all via Wayback Machine `id_` snapshots — openai.com returns HTTP 403 to
non-browser clients, including WebFetch and curl):
- /index/path-to-astra/ (ts 20261011094053)
- /index/safety-overview-gpt-6-astra/ (20261013034730)
- /index/openai-frontier-governance-framework/ (20261006094746)
- /index/third-party-cyber-evaluations-involving-openai-models/ (20261004061002)
- /index/strengthening-safety-with-external-testing/ (20261011095923)
- /index/detecting-and-reducing-scheming-in-ai-models/ (20261011124917)
- /index/deliberative-alignment/ (20260630201024)
- /index/evaluating-chain-of-thought-monitorability/ (20261003100012)
- /index/reasoning-models-chain-of-thought-controllability/ (20261006120121)
- /index/why-language-models-hallucinate/ (20261013203739)
- /index/the-instruction-hierarchy/ (20260910023926)
- /index/advancing-red-teaming-with-people-and-ai/ (20261002200648)
- /index/red-teaming-network/ (20260915214440)
- /index/bug-bounty-program/ (20261011002011)
- /index/towards-safety-cases-for-frontier-ai-training/ (20261010233940)
- /index/updating-our-preparedness-framework/ (20260930205154)
- /safety/ (20261012115457)
- /safety/evaluations-hub/ (20260224232026 — last standalone snapshot; the 20261012 snapshot shows a
  301 to deploymentsafety.openai.com)
- /backend/safety-data.json (20261012000339 — the hub's backing data, 5,018 bytes; 404 on the live site)

GitHub (API metadata + raw READMEs): openai/{simple-evals, evals, frontier-evals, preparedness,
monitorability-evals, model_spec, model_spec_evals, model_spec_dataset, gpt-oss-safeguard,
teen-safety-policy-pack, mle-bench, SWELancer-Benchmark, hallucinations-paper-experiments,
emergent-misalignment-persona-features, privacy-filter, orion-multistep-analysis, codex-security,
openai-guardrails-python, human-eval}; full org repo listing (2 pages, sorted by pushed_at).
Third-party repos checked: SEC-bench/SEC-bench-Pro, sunblaze-ucb/exploitgym,
exploitbench/exploitbench, aisa-group/PostTrainBench, UKGovernmentBEIS/inspect_evals,
UKGovernmentBEIS/control-arena, METR/eval-analysis-public.

Third-party evaluator sources:
- https://www.apolloresearch.ai/science (index of OpenAI system-card engagements, GPT-4o → GPT-5.6)
- https://metr.org/ ; https://metr.org/blog/2026-06-26-gpt-5-6-sol/ ;
  https://metr.org/blog/2026-08-26-openai-hugging-face-incident-investigation/
- https://www.aisi.gov.uk/blog ;
  /blog/gpt-6-astra-performs-unsanctioned-supply-chain-attacks-in-simulations (2026-09-28) ;
  /blog/our-evaluation-of-openais-gpt-5-5-cyber-capabilities (2026-04-30)
- https://www.nist.gov/caisi ; https://antischeming.ai/
- arXiv: 2603.05706 (CoT-Control), 2609.38415 (UK AISI Astra supply-chain report)

## URLs not fetched / unavailable

- `https://openai.com/*` directly: **HTTP 403** for every path via WebFetch and curl (bot blocking).
  Everything on openai.com was obtained via Wayback; a handful of pages had no snapshot on the first
  attempt and were re-resolved (`availability` API) before fetching.
- `https://openai.com/backend/safety-data.json` live: **404** (`{"message":"NotFound"}`) — only the
  archived copy exists, consistent with the hub's retirement.
- `https://openai.com/index/hugging-face-incident-and-the-road-ahead/` and
  `/index/hugging-face-model-evaluation-security-incident/`: Wayback returned an Internet Archive
  donation-banner page rather than the article, so these two posts are **not** fetched; their content
  is covered here only via the Hugging Face technical-report PDF and METR's report, both fetched.
- `https://openai.com/index/gpt-5-6-cyber/` (referenced by the Astra card for "Advanced Cybersecurity
  Completion Rate"): no Wayback snapshot — **not fetched**.
- HealthBench Professional tech report (Apr 2026), MentalHealthBench paper, and a public CoT-Control
  repo: referenced in cards/posts without resolvable URLs — marked UNVERIFIED in
  `open-tools-and-methods.md`.
- NIST CAISI: no OpenAI-specific assessment publication found on https://www.nist.gov/caisi (its 2026
  published assessments are of other developers' models), so CAISI's OpenAI work is documented only
  from the GPT-5.5 system card.
- deploymentsafety.openai.com PDF paths for /gpt-5, /gpt-5-1, /gpt-5-2, /o3: return HTML, not PDF
  (older cards are HTML-only at those paths); analysed from HTML/TOC only.
- `openai/preparedness` now redirects to `openai/frontier-evals`; `openai/SWELancer-Benchmark` is a
  stub pointing at the same place.

## Named third parties (for `third_party/`)

UK AISI, US CAISI (NIST), METR, Apollo Research, Redwood Research, SecureBio, Irregular, Gray Swan,
Dyno Therapeutics, Velocity Bio, Gryphon Scientific, FutureHouse (ProtocolQA data), CrowdStrike,
Bugcrowd, four unnamed private red-teaming organisations, a Cyber Frontier Risk Council and a
Frontier Risk Council, plus the ROOST Model Community (open safety-model distribution).

## Eval files touched

33 new family notes created in `../../evals/` on 2026-10-19: `openai-production-benchmarks`,
`openai-u18-safety-evals`, `openai-agentic-safe-completions`, `openai-static-multiturn-jailbreaks`,
`gpt-red`, `openai-alignment-restrictions-suite`, `openai-coding-deception-broken-search`,
`openai-realistic-work-env-misalignment`, `openai-agent-to-agent-comms`,
`openai-deployment-simulation`, `openai-metagaming-oversight-gaming`, `openai-monitorability-suite`,
`oai-repo-sabotage`, `sneaky-sandbox-escape`, `openai-sandbagging-monitor-evasion`,
`openai-misuse-monitor-performance`, `sec-bench-pro`, `sre-bench`, `sandbox-bench`,
`openai-cyber-range`, `vulnlmp`, `openai-internal-research-debugging`, `kernelgen-1p`,
`nanogpt-speedrun`, `troubleshootingbench`, `multimodal-troubleshooting-virology`,
`tacit-knowledge-troubleshooting`, `openai-bio-design-proxies`, `mentalhealthbench`,
`first-person-fairness`, `model-spec-evals`, `simple-evals`,
`openai-dots-persistent-agent-evals`.

A `- Used by: OpenAI (...)` line was appended to 41 notes that already existed (never overwritten):
`cve-bench`, `exploitbench`, `exploitgym`, `cyscenariobench`, `frontiercyber`, `cybergym`,
`healthbench`, `healthbench-professional`, `protocolqa`, `lab-bench`, `wmdp`, `mle-bench`,
`posttrainbench`, `re-bench`, `terminal-bench`, `impossiblebench`, `shade-arena`, `gray-swan-ipi`
(already had one), `gray-swan-ipi-benchmark`, `strongreject`, `cot-control-benchmark`,
`cot-controllability`, `cot-monitorability-legibility`, `apollo-evals`,
`anti-scheming-and-openai-evals`, `scheming-honeypots-internal-codebases`,
`destructive-actions-resampling`, `sandbox-escape-propensity`, `metr-ai-rd-tasks`,
`uk-aisi-cyber-ranges`, `securebio-capability-tests`, `securebio-bio-suites`, `biotier`,
`vct-virology`, `vct-virology-capabilities-test`, `abc-bench`, `simpleqa-verified`,
`truthfulqa-simpleqa-hallucination`, `petri`, `inspect`, `bbq`, `openai-moderation-dataset`.

`../../evals/catalog.md` did not exist and was created with the header table required by
`CONVENTIONS.md` plus the 34 OpenAI rows (the 33 new notes and `cve-bench`); it carries a note
asking other agents to append their own sections rather than rewrite it.
