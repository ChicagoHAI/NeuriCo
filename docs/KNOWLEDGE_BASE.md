# The safety knowledge base

One record of everything the engine knows and finds about AI safety, growing continuously: what
labs run and report (`labs/`, `evals/`, `third_party/`, `perspectives/`, `gaps/`), what we ran and
observed (`runs/`, `results/`), what we claim and how far it has been validated (`findings/`), what we
are about to try (`queue/ideas`, `queue/proposals`, `queue/*`), what the catalogs say (`catalog/`),
and what arrived from outside today (`inbox/`). This page is the reference for how that record is
stored, indexed, queried and fed; `safety_kb/README.md` is the reader's entry point and
`docs/SAFETY_ENGINE.md` the operator's.

## 1. Two layers, one truth

**Files are the source of truth.** Every fact is a YAML, Markdown or JSON file under `safety_kb/`,
human-editable, diffable, citable (`CONVENTIONS.md`). The engine writes new files (`ingest.py`
writes `runs/*.json` and `findings/*.yaml`; the crawler writes `inbox/*.md`; the planner writes
`queue/ideas/*.yaml`, `queue/proposals/<run>/`; the scout writes `catalog/models_latest.yaml` and an
inbox note) and appends dated events to existing ones (`findings/*.yaml` `status_history`).

**`kb.sqlite` is a projection.** `src/safety/kbdb.py:rebuild` rebuilds it from scratch from the
files, after every ingest (daemon `refresh_index`), after every crawl, after a status change, and
whenever a query finds a file newer than the index (`ensure_index`). It is git-ignored and can be
deleted at any time. Nothing is stored only in the database: the crawler's hash registry is the
`seen` table *and* `inbox/seen.jsonl` (the file is what survives a rebuild); the agent tool's query
log goes to a JSONL file, not to the database.

Rebuild time on the live knowledge base (823 nodes, 1,220 edges, 641 files, 2026-10-20): about 3 s;
the index is 7 MB. `./neurico safety kb rebuild` prints the counts and the time.

## 2. Schema (`kb.sqlite`, schema version 2)

Legacy tables, unchanged, used by the digest, the anomaly scan and `kb query`: `runs`, `results`,
`findings`, `finding_events`, `planner_rounds`, `evals`, `models` (`kbdb.py` module docstring).

### `nodes`: one row per knowledge object

| column | meaning |
|---|---|
| `id` | `<kind>:<native id>`, e.g. `finding:finding-20261020-001-judge-dependent-harmful-reasonin`, `result:run-suite-20261019-001/sycophancy/qwen2.5-0.5b-instruct`, `eval_note:advbench`, `lab_note:anthropic/system-cards`, `inbox:2026-10-20-arxiv-...` |
| `kind` | see the table below |
| `title`, `summary`, `body` | the searchable text; `summary` <= 600 chars for listings, `body` the full record (YAML dump or the Markdown) capped at 80k chars |
| `family`, `model`, `eval`, `category`, `lab` | filter columns where they apply (one model per row; the others are `model:<id>` tags) |
| `status` | the kind's lifecycle (findings: candidate/reproduced/confirmed/refuted/withdrawn; jobs: pending/running/done/failed; ideas: the state of the job that uses them, else proposed; inbox: open/archived or the front matter's `triage`; models: current/superseded/judge; results: success/failed; notes: note) |
| `created` | when the record came into being (finding `created`, run `started`, job `created`, inbox `fetched`, note `Fetched:` date) |
| `observed` | event time (run `finished`, result `finished`, inbox `published`, scout `refreshed`) |
| `valid_from` | when the current status began (finding: last status change); defaults to `created` |
| `date` | the best known event time: `observed`, else `created`, else the file's mtime; what `--since` and the recency prior use |
| `recorded_at` | transaction time: the mtime of the file the row came from (when the fact entered the record) |
| `source_path` | the file, relative to `safety_kb/`; `show` prints it, agents open it for the full record |
| `url`, `urls` | primary URL and every URL cited in the record |
| `tags` | JSON list: `category:<c>`, `model:<id>`, `eval:<id>`, `campaign:<name>`, `used-by:<org>`, `source:<crawler source>`, `anomalies`, the status, ... (filter with `--tag`) |
| `canonical_keys` | dedup keys derived from the URLs: `arxiv:<id>`, `doi:<doi>`, `url:<normalised>` (sai-review's `canonical_keys` rule) |
| `content_hash` | sha256(title, summary, body); unchanged files give unchanged hashes, so a rebuild is idempotent and a changed note is detectable |
| `meta` | JSON: the structured fields worth keeping (metrics, models list, accepted/rejected ids, front matter, ...) |

`kb_meta` holds `built_at`, `root`, `schema_version`, `tool_hash`, `nodes`, `edges`.

### Kinds and where they come from

| kind | files | id |
|---|---|---|
| `finding` | `findings/*.yaml` (+ `.md` body) | `finding:<id>` |
| `event` | each entry of a finding's `status_history` | `event:<finding id>/<n>` |
| `run` | `runs/*.json` | `run:<run_id>` |
| `result` | each `results[]` / `pairs[]` observation of a run | `result:<run_id>/<eval>/<model>` |
| `job` | `queue/{pending,running,done,failed}/*.yaml` | `job:<job id>` |
| `idea` | `queue/ideas/*.yaml` | `idea:<file stem>` |
| `proposal` | `queue/proposals/<run>/outcome.yaml` + `planning_log.md` | `proposal:<planner run>` |
| `inbox` | `inbox/*.md`, `inbox/archive/*.md` | `inbox:<file stem>` |
| `eval`, `model`, `family`, `campaign` | `catalog/evals.yaml`, `catalog/models.yaml`, `catalog/families.yaml` + `models_latest.yaml`, `campaigns/*.yaml` | `eval:<id>`, `model:<id>`, `family:<id>` (+ `family:<id>/latest`), `campaign:<name>` |
| `eval_note` | `evals/*.md` | `eval_note:<stem>` |
| `lab`, `lab_note` | `labs/<lab>/README.md`, `labs/<lab>/*.md` | `lab:<lab>`, `lab_note:<lab>/<stem>` |
| `third_party`, `perspective`, `gap`, `design`, `report` | `third_party/`, `perspectives/`, `gaps/`, `design/`, `reports/` (not the generated `results-timeline.md`) | `<kind>:<stem>` |

### `edges`: the links that already exist in the files

`edges(src_id, rel, dst_id, evidence, recorded_at)`, primary key `(src, rel, dst)`, index on `dst`.
An edge is written only when both ends exist in `nodes` (no dangling links); `evidence` names the
field it came from.

| rel | from -> to | derived from |
|---|---|---|
| `from_run` | finding -> run | `finding.source_run`, `run.findings` |
| `produced` | run -> result | the run's `results[]` / `pairs[]` |
| `evaluates` | result/job/campaign -> model | `model_id`, `suite.models`, `target_models.subjects` |
| `measures` | result/job -> eval | `eval_id`, `suite.evals` |
| `about_model` | finding -> model | `finding.models` |
| `has_event` | finding -> event | `status_history` |
| `by_run` | event -> run | `status_history[].by = validate:<run>` (the validation run) |
| `for_job` | run -> job | `run.job` |
| `uses_idea` | run/job -> idea | `idea_file` |
| `proposed` | proposal -> job / idea | `outcome.accepted`, `job.extra.planner_run`, idea files named after the planner run |
| `validates` | job -> finding | `job.finding_id` |
| `in_campaign` | run/job/finding/proposal -> campaign | `campaign` |
| `member_of`, `part_of` | model -> family; lab_note -> lab; family/latest -> family | directory and catalog structure |
| `used_by` | eval_note -> lab / third_party | the note's `Used by: <org>` lines (word match on the lab directory, whole-word prefix match on the third-party file) |
| `catalogued_as` | eval_note -> eval | the note's stem equals, or prefixes, a catalog id |
| `cites` | inbox -> run | run ids mentioned in the note |

So the chains the owner asked for are walkable: finding -> run -> results -> models/evals,
proposal -> idea -> job -> run, finding -> validation events -> validating run, eval note -> labs.

### `nodes_fts`

FTS5 (`porter unicode61`) over `title, summary, body, tags`, rebuilt with the nodes. Ranking is
`bm25(title x4, summary x2, body x1, tags x1.5)`.

### `seen`

`seen(hash, source, key, url, first_seen, path)`: the crawler's registry, rebuilt from
`inbox/seen.jsonl` and from the `hash` in each inbox note's front matter.

## 3. Query surface

The same functions serve humans (`./neurico safety kb ...`), the host code (`kbdb.search`,
`kbdb.show`, `kbdb.related`, `kbdb.check_idea`, `kbdb.list_nodes`, `kbdb.stats`) and agents
(`templates/skills/safety-kb/scripts/kb.py`, stdlib only, read-only, installed as
`safety_kb/tools/kb.py` by every rebuild and copied into research workspaces as the `safety-kb`
skill). The SQL lives once, in the tool; `kbdb.py` imports it.

```bash
./neurico safety kb search "sycophancy judge disagreement" --kind finding,result --since 30d [--status s] [--family f] [--model m] [--eval e] [--tag t] [--no-recency] [--limit 10] [--json]
./neurico safety kb show finding:<id> [--full]            # row, dates, tags, urls, edges in/out, body, source file
./neurico safety kb related run:<id> [--rel produced,for_job] [--hops 2]   # neighbourhood + lexical neighbours
./neurico safety kb check-idea "<hypothesis>" [--title "..."] [--sources model:qwen3-8b,finding:<id>] [--json]
./neurico safety kb stats                                  # counts per kind, status and relation; built_at
./neurico safety kb rebuild | timeline | anomalies | query "<sql>"
python3 safety_kb/tools/kb.py search "..."                 # from inside the knowledge base (agents: see the skill)
```

**search**: an exact id first; then FTS with all terms ANDed, then (if fewer than `limit` hits) any
term ORed, the arms kept apart so "all terms match" beats "some terms match"; inside each arm the
bm25 order is re-weighted by a recency prior per kind (half-lives: inbox 30 d, finding/run/result/
event 90 d, idea/job/proposal 180 d, notes none; `--no-recency` for "has this ever been done"
questions) and a lifecycle prior (refuted 0.6, withdrawn 0.5, failed/cancelled 0.7, superseded/
archived 0.6). Every hit returns `components` (`lex_rank`, `bm25`, `rrf`, `recency`, `lifecycle`).
Filters are SQL `WHERE`s on the node columns and tags, applied before ranking.

**check-idea**: the dedup gate, modelled on sai-review's `tools/kb.py check-idea`
(`S:src/sai_digest/tools/kb.py:464-519`): lexical hits over `idea`, `finding`, `run`, `job`,
`proposal` with recency off, plus everything linked by any edge to the `--sources` ids (a model, an
eval, a finding); each hit is banded `duplicate` (same normalised title or content-token Jaccard
>= 0.6), `overlaps` (>= 0.3 or a shared source) or `related`; `band` is the strongest hit or
`clear`. The planner templates tell the agents to run it before proposing; `build_context` prints
the command in every block. The bands are lexical until an embedding arm exists.

**related**: edges in both directions up to two hops, the touched nodes, and the lexical
neighbours of the node's own title+summary.

Set `NEURICO_KB_QUERY_LOG=<file>` to append one JSON line per query (sai-review's
`output/kb_queries.jsonl` idea: "a `new` verdict with no query behind it is a guess").

`kbdb.snapshot_to(kb, dst, exclude_ids)` writes a read-only (0444) copy with the SQLite online
backup API for a sandboxed stage, dropping the given ids and their edges (an ideation stage must
not see its own round); the tool finds it as `input/kb.sqlite`.

## 4. How the planner reads it

`src/safety/planner.py:build_context(kb, campaign)` keeps its signature and the template
placeholders (`campaign`, `catalog_evals`, `catalog_models`, `findings`, `runs`, `inbox`, `jobs`,
`gaps`) but fills them from the index instead of char-clipped file dumps:

- `findings`: counts by status, then the 40 most recently changed findings, one line each with id,
  status, date, title, category, model and the summary; the tool hint on top.
- `runs`: the 25 newest runs, each with up to 4 result ids and their metric summaries (successes
  first); the results timeline file for the rest.
- `inbox`: open inbox items newest first with anomaly notes first, then result drift computed live
  from the `results` table.
- `gaps`: the gap documents and every lab's `gaps.md` summary, then up to 14 notes (`gap`, `lab`,
  `lab_note`, `eval_note`, `third_party`, `perspective`, `design`, `report`) ranked by FTS over the
  campaign objective, categories in scope and target models.
- `catalog_evals` / `catalog_models`: one line per catalog entry (category, runner, judge; family,
  size, GPU, access, supersession) instead of the YAML text.
- `jobs`: the queue listing as before.

Every record carries an id the agent expands with `python3 tools/kb.py show <id>` (the planner
runs with `safety_kb/` as its working directory and `NEURICO_SAFETY_KB` set). If the index cannot
be built the legacy dumps are used, so planning never depends on the database.

## 5. How new knowledge arrives

| source | writer | what |
|---|---|---|
| finished jobs | `ingest.py` (daemon) | `runs/<run>.json`, `findings/<id>.yaml` (candidate only), validation events |
| result drift | `kbdb.scan_anomalies` (daemon, after each ingest) | `inbox/<stamp>-anomalies.md` |
| model releases | model scout agent (`model_scout.py`) | `catalog/models_latest.yaml`, `catalog/proposals/`, `inbox/<date>-model-scout.md` |
| papers, HF repos, blogs | **crawler** (`crawler.py`, no LLM) | `inbox/<date>-<source>-<slug>.md` |
| planner rounds | `planner.py` | `queue/proposals/<run>/`, `queue/ideas/*.yaml`, jobs |
| humans | any editor | notes under `labs/`, `evals/`, `third_party/`, ...; `./neurico safety finding <id> --status ...` |

### The crawler (`./neurico safety crawl`)

Replaces sai-review's `scrape` stage (rs-pipeline + LLM judge, X/RSS credentials) with three
credential-free sources configured in `safety_kb/catalog/sources.yaml` (data, not code):

- **arXiv API**: `(categories) AND (any keyword) [AND (any require term)]` per query entry, sorted
  by submission date, kept only when a keyword (and a require term) is in the title or abstract;
  key `arxiv:<id>` (version-stripped).
- **Hugging Face**: the newest model repos of each `hf_authors` entry in `catalog/families.yaml`
  (quantised re-uploads skipped by tag) and dataset searches; keys `hf:model/<repo>`,
  `hf:dataset/<repo>`.
- **Feeds**: RSS 2.0 / Atom from labs, evaluators, community sites and newsletters, optional
  per-feed keyword filter; key `url:<normalised url>` (or the arXiv/DOI key when the link is a paper).

Each new item is one note with front matter (`source`, `kind`, `title`, `url`, `key`, `published`,
`fetched`, `hash`, `tags`, extras) and the abstract/summary as body. The hash is sha256 of the
canonical key, so the same paper from two feeds is one note. Politeness: one request per
`rate_limit_seconds` per host (arXiv asks for 3 s), a descriptive `User-Agent`, 30 s timeouts; every
source is wrapped so a feed that is down is one line in the run summary (`logs/safety/crawler.log`)
and never a failed sweep. The daemon runs a sweep every `crawl_interval_hours` (24) when
`sources.yaml` exists; `--dry-run` lists without writing, `--source arxiv|huggingface|feeds|<feed id>`
narrows a run. Feed URLs were checked on 2026-10-20; the ones that returned 404 or HTML are kept with
`enabled: false` and a note so the owner can fix them.

Triage is the planner's: it reads open inbox items through the index and moves handled notes to
`inbox/archive/` (status `archived`) or sets `triage:` in the front matter.

## 6. What was taken from sai-review's KB design, and what was not

Read: `docs/kb-schema.md`, `docs/kb-design-research.md`, `docs/digest.md` ("The knowledge base",
"The scrape step"), `src/sai_digest/{kb,registry,scrapper}.py`, `src/sai_digest/tools/kb.py`.

**Ported** (adapted to NeuriCo's kinds and ids):

- the one node index + FTS5 + typed edge table shape (`kb-schema.md:20-80`), with `<kind>:<native>`
  ids, `content_hash`, event/transaction time split (`date` vs `recorded_at`), tags as data;
- the query surface and its ranking: `search` (AND-then-OR, bm25 column weights, recency/lifecycle
  priors returned as `components`), `show`, `neighbors` (as `related`), `check-idea` with its bands
  and thresholds, `stats`, read-only `mode=ro` opening, capped results, the stdlib-only sandbox tool
  whose SQL the host imports (`tools/kb.py:1-38, 224-277, 464-519`);
- `snapshot_to` with exclusions (`kb.py:1189-1225`), the query log as a JSONL side file;
- `canonical_keys` / `normalize_url` for dedup (`scrapper.py:366-417`), the deterministic
  candidate pass before any agent runs (`registry.py:201-237`) as the hash registry of the crawler.

**Deliberately not ported**:

- *The KB as system of record with `valid_to` / `superseded_by` / hash-chained `events`*
  (`kb-schema.md:8-16, 88-97`). sai-review needed it because its registry JSONs stopped being the
  truth and agents wrote to the database. Here the files are the truth, every finding carries its own
  dated `status_history`, every run its record, and git holds the history; a bitemporal schema in
  the projection would be a second, derived history that could drift from the files. `recorded_at`
  (file mtime) plus `created`/`observed`/`valid_from` give the temporal view the owner asked for
  without a write path into the database. If the engine ever needs supersession, it belongs in the
  files (`superseded_by:` in a finding) and the index projects it.
- *Typed detail tables per kind* (`findings_idx`, `ideas`, `runs`...): the legacy `runs`/`results`/
  `findings` tables already play that role for the two kinds with real numeric queries; the rest
  are filter columns + `meta` JSON on `nodes`.
- *Notes written from the sandbox* (`note` op, `kb_notes.jsonl` import): agents here write findings
  and inbox-triage files, which are ingested as files; a free-text note table would be the one thing
  stored only in the database.
- *The scrapper and its LLM judge* (`digest.md:334-351`): replaced by the credential-free crawler
  with no model calls; relevance and severity judgement stays with the planner, which has the whole
  knowledge base to judge against.
- *Embeddings / vec0 / RRF over two arms* (phase 2 of `kb-design-research.md`): not needed at
  10^3 nodes; the ranking keeps the RRF slot (`rrf` component) so a vector arm can be fused later.

## 7. Files

- `src/safety/kbdb.py`: schema, collectors, `rebuild`, `ensure_index`, `snapshot_to`, `seen_hashes`
  / `record_seen`, host wrappers, legacy timeline/anomaly code.
- `templates/skills/safety-kb/scripts/kb.py` + `SKILL.md`: the query tool and the agents' guide.
- `src/safety/crawler.py`, `safety_kb/catalog/sources.yaml`: the crawler and its sources.
- `src/safety/planner.py:build_context`: the index-fed planner context.
- `src/cli/safety.py`: `kb search|show|related|check-idea|stats|rebuild|...`, `crawl`.
- `tests/test_safety_kb_nodes.py`, `tests/test_safety_crawler.py`.
