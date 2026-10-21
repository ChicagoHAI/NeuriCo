# Safety knowledge base

An organised, citable record of how AI labs evaluate and monitor safety, what evaluations
exist, where the gaps are, and the machine-readable state of NeuriCo's automated safety
engine. Everything was fetched on 2026-10-19 unless a file says otherwise; `CONVENTIONS.md`
describes the rules (fetch, cite, mark UNVERIFIED, no secrets).

## Start here

| Question | Read |
| --- | --- |
| How do labs evaluate and monitor safety, what exactly do they run, what is missing? | `gaps/synthesis.md` |
| Google DeepMind in depth (Gemini 4 Argon card, 217-page safety report, FSF v3.1) | `labs/google/README.md` |
| Anthropic: system cards, RSP, what they want from independent evaluators | `labs/anthropic/README.md`, `labs/anthropic/independent-evaluators.md` |
| OpenAI: system cards, Preparedness Framework, evaluations hub | `labs/openai/README.md` |
| Qwen / Kimi / GLM / DeepSeek: what they report and the gap matrix | `labs/alibaba-qwen/`, `labs/moonshot-kimi/`, `labs/zhipu-glm/`, `labs/deepseek/`, `gaps/open-model-families-gap-matrix.md` |
| Meta, xAI, Mistral, Amazon, Microsoft and other frameworks | `labs/meta/`, `labs/xai/`, `labs/mistral/`, `labs/other/README.md` |
| The third-party evaluator ecosystem and how to join it | `third_party/README.md`, `third_party/how-to-become-a-trusted-evaluator.md` |
| Using AI to audit AI: the two essays and 23 design lessons | `perspectives/ai-auditing-ai.md` |
| Tooling we can plug in, with install/run details | `evals/tooling-catalog.md`, `design/quick-start-evals-for-small-models.md` |
| Methodology rules for the engine | `design/best-practices-automated-safety-research.md` |
| How the automated engine is built and operated | `design/safety-engine-architecture.md`, `../docs/SAFETY_ENGINE.md` |
| Searching all of it (findings, runs, results, notes, inbox, ideas) and the dedup gate | `../docs/KNOWLEDGE_BASE.md`; `./neurico safety kb search "<query>"`, `python3 tools/kb.py search "<query>"` from this directory |

## Layout

```
catalog/        evals.yaml (runnable evaluation catalog), models.yaml (model registry),
                families.yaml (tracked families), models_latest.yaml (scout snapshot),
                sources.yaml (what the crawler reads: arXiv queries, HF authors, feeds),
                external_indexes.yaml (registries another process maintains: lab-reported
                evaluations, curated rerunnable environments, datasets, report tables/figures)
campaigns/      what the engine is working on (objective, models, budgets, planner policy)
queue/          pending/ running/ done/ failed/ job specs; ideas/ NeuriCo idea YAMLs;
                proposals/ planner output; state.json runtime state (git-ignored)
runs/           one JSON per finished job
findings/       candidate -> reproduced -> confirmed | refuted findings (YAML + MD)
results/        suite outputs (git-ignored; copied into run records)
reports/        digests and scorecards
inbox/          one dated note per crawler / scout / anomaly item awaiting planner triage
                (front matter: source, url, published, fetched, hash); archive/ for triaged
                notes; seen.jsonl is the crawler's hash ledger
labs/<lab>/     per-lab notes with quotes and page references
evals/          one note per evaluation family (380 so far) + tooling-catalog.md
third_party/    evaluator organisations and the trust criteria
perspectives/   essays on auditing
gaps/           gap matrices and the synthesis
design/         architecture, best practices, quick-start
sources/        raw fetched text (PDF/HTML -> txt/md); PDFs over 20 MB are git-ignored
tools/          kb.py: the read-only query tool (installed by every index rebuild) + fetch helpers
kb.sqlite       the index (git-ignored projection of everything above: nodes, edges, FTS;
                `./neurico safety kb rebuild` regenerates it in ~3 s)
```

Everything is a file; `kb.sqlite` is rebuilt from the files after every ingest, crawl and status
change and holds nothing of its own. `../docs/KNOWLEDGE_BASE.md` has the schema and the query surface.

## Operating the engine (host)

```bash
uv run python src/cli/safety.py init
uv run python src/cli/safety.py enqueue-suite --evals xstest-safe strong-reject --models qwen3-1.7b --limit 200
uv run python src/cli/safety.py enqueue-idea safety_kb/queue/ideas/<id>.yaml --kind optimise --provider claude
uv run python src/cli/safety.py start --campaign qwen-small-pipeline-test --gpus 2
uv run python src/cli/safety.py status      # logs/safety/status.md, events.log
uv run python src/cli/safety.py plan --campaign qwen-small-pipeline-test   # run the planner once
uv run python src/cli/safety.py digest      # reports/latest-digest.md
uv run python src/cli/safety.py crawl [--dry-run] [--source arxiv|huggingface|feeds|<feed id>]   # new papers, releases, posts -> inbox/
uv run python src/cli/safety.py kb search "sycophancy qwen3 judge" --kind finding,run --since 30d
uv run python src/cli/safety.py kb show <id> | related <id> | check-idea "<hypothesis>" | stats | envs | rebuild
```

(`./neurico safety <subcommand>` is the same thing.) Agents working in a research workspace have the
same queries as the `safety-kb` skill; agents working here run `python3 tools/kb.py ...`.

## Status of the record (2026-10-19)

- Labs covered: Google, Anthropic, OpenAI, Meta, xAI, Mistral, Amazon, Microsoft, Cohere,
  NVIDIA, G42, Naver, Magic (frameworks), Alibaba Qwen, Moonshot Kimi, Zhipu GLM, DeepSeek.
- Known holes: OpenAI's site returned 403 to the fetcher (archived copies used); several
  Chinese-lab blogs are JS-rendered; some Enkrypt/Cisco/KELA checks for Qwen, Kimi and GLM were
  not completed; items marked UNVERIFIED in each README.
