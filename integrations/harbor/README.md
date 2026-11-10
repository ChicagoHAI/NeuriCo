# NeuriCo Harbor agent

This directory is the locked ACP runtime for using NeuriCo's manager-driven
AutoResearch as a Harbor agent. The adapter converts Harbor's prompt through
NeuriCo's existing local-idea converter and launches fresh HITL AutoResearch in
headless Auto mode inside Harbor's supplied repository, using NeuriCo's Codex
provider. Auto mode uses the manager for every review boundary but never waits
for human input.

## Contract

- The ACP `cwd` becomes the idea's `metadata.local_workspace`. The adapter
  never assumes `/app`, and NeuriCo uses Harbor's repository as its research
  workspace.
- Harbor's complete text prompt is preserved in
  `idea.background.description`. NeuriCo's prompt generator already promotes
  that field as high-priority user instructions.
- NeuriCo runs fresh manager-driven HITL AutoResearch in Auto mode. The manager
  reviews resource-finder, rule-maker, experiment, and scoring boundaries and
  may request repairs or replacement workers without human interaction. The
  resource finder may use Harbor's supplied repository and any external sources
  allowed by the task's Harbor network policy. The scored lifecycle then
  continues with a baseline experiment, scoring, proposals, candidate
  experiments, and manager-governed accept-or-restore checkpointing.
- The adapter is benchmark-focused. Internal scoring is enabled, while paper
  generation and scribe/notebook output are always disabled. Harbor's verifier
  remains the authoritative benchmark result after the agent exits.
- One AutoResearch improvement iteration is used by default, matching
  NeuriCo's CLI default. `NEURICO_HARBOR_AUTORESEARCH_ITERATIONS` may select a
  larger positive count. This changes search depth within one Harbor trial; it
  does not change Harbor's number of independent attempts or limit the
  manager's stage-level repair and replacement decisions.
- `NEURICO_HARBOR_TIME_LIMIT_SECONDS` optionally gives NeuriCo a whole-run
  budget through NeuriCo's native managed-AutoResearch deadline. NeuriCo owns
  stop propagation and budget-specific selected-frontier finalization; the
  adapter only translates the completed budget stop for Harbor. Set this below
  Harbor's agent timeout so native finalization has time
  to finish; for example, use 3480 seconds with a 3600-second Harbor timeout.
  If native shutdown itself stalls, the adapter terminates the isolated NeuriCo
  process tree, including separately grouped provider processes, after a
  30-second grace period. ACP cancellation follows the same ownership boundary:
  it requests NeuriCo's native stop first, then terminates any surviving owned
  groups. A dedicated Linux supervisor retains orphaned provider processes
  until cleanup finishes, including providers started during shutdown. It
  remains independent of the manager so stalled manager cleanup cannot lose
  process ownership. Failed, cancelled, and forcibly terminated runs clean all
  retained descendants. After normal completion or completed native budget
  finalization, detached task services remain available to Harbor's verifier;
  NeuriCo's provider launchers have already rejected and terminated any
  lingering provider process group before those outcomes can be reported.
  Harbor's ACP launcher does not
  currently expose its resolved hard deadline to the agent, so the Harbor
  timeout and the smaller NeuriCo budget are explicit paired job settings.
- The requested Harbor model is advertised as an ACP session configuration
  option and written to an isolated `CODEX_HOME`, pinning every Codex-backed
  NeuriCo stage to the same model.
- Local runs use a Codex login cache supplied through
  `NEURICO_CODEX_AUTH_FILE`. The adapter copies it into the isolated run home;
  it never writes the mounted source file.
- Hosted runs may instead supply `HOSTED_INFERENCE_TOKEN` together with
  `HOSTED_INFERENCE_URL`. Direct OpenAI API mode accepts `OPENAI_API_KEY` and
  optional `OPENAI_BASE_URL`.
- NeuriCo's idea registry and Codex home are kept in a temporary control
  directory outside the task repository. Research state and the retained best
  implementation remain in Harbor's workspace.
- The Harbor parent supervisor performs trace collection, but
  `/logs/artifacts/` is an agent-controlled Harbor publication channel rather
  than an operating-system trust boundary. Before launch, the parent opens
  non-following directory capabilities for the publication and mode-`0700`
  transaction roots and records the task-workspace identity. No run-specific
  entry exists while the supervised process is active. After it exits, the
  parent verifies those identities, builds one run directory in a sibling
  transaction root, revalidates the complete allowlisted text payload, and
  publishes it with descriptor-relative rename. Export failure discards the
  staging tree before a metadata-only fallback is attempted.
- Successful NeuriCo runs may intentionally leave task services alive for the
  benchmark verifier. Such same-UID processes can still mutate the
  agent-controlled artifact channel. `manifest.json` records every public
  member's size and SHA-256 digest so consumers can detect accidental missing,
  added, or modified files. This is a consistency check, not a trusted
  attestation: a deployment that needs adversarial tamper resistance must copy
  the bundle into Harbor-controlled storage outside the task environment.
- Before launch, the parent keeps a bounded in-memory inventory of eligible
  file identities (path, device, inode, link count, size, modification/change
  timestamps, and mode), without reading or storing file payloads. The
  inventory is never passed to the child or written to the trace bundle.
  Post-run collection copies public text files that are new or changed relative
  to that inventory. Unchanged benchmark inputs are not duplicated, while a
  changed public implementation file is retained so the final research state
  is not silently omitted. If inventory collection is incomplete, unknown
  paths fail closed.
- Trace eligibility is an authority decision, not a payload-similarity guess.
  Canonical sealed evaluator paths, hidden evaluation datasets, every
  non-public file under `scoring/`, all `.neurico/` control state,
  rule-maker/scorer/evaluator/manager logs, and unclassified logs are never read
  as artifact payloads. The exporter does not load sealed data to build text
  fingerprints. Public `scoring/interface.md` and `scoring/results.json` remain
  eligible because NeuriCo already defines them as worker/review evidence rather
  than evaluator authority.
- The trace collector adopts NeuriCo's behavioral, application-level sealing
  model. Research workers are required not to access sealed evaluator material;
  logs emitted by explicitly public worker roles are therefore treated as
  public without comparing them against evaluator contents. Evaluator, scorer,
  rule-maker, verifier, and manager producers remain private regardless of
  filename suffix or payload. This is not an operating-system sandbox: a worker
  that deliberately bypasses NeuriCo's sealing contract is outside the trace
  collector's threat model and must be addressed in the core execution and
  evaluator-isolation architecture, not by post-hoc trace scanning.
- Workers are likewise required not to inspect or disclose unrelated mounted
  credentials. Configured NeuriCo/provider credentials and recognizable common
  secret forms are still actively redacted, but the collector does not claim
  to recognize every arbitrary opaque string from an unregistered mounted
  file. Deliberate access to such a file is an execution/access-control failure
  outside this trace collector's threat model.
- Eligible new or changed workspace files and explicitly role-labeled public
  research logs are copied once beneath `workspace/files/`. Every path
  component is opened relative to a verified workspace directory descriptor;
  file device, inode, link count, size, timestamps, and mode must remain stable
  through the read. Only sanitized UTF-8 text is exportable. Changed or new
  binaries (including ASCII-looking files with binary extensions) make public
  capture explicitly partial; their paths and payloads remain withheld.
  Symlinks, hard links,
  credential-like paths, provider homes, dependency environments, caches, live
  control files, and `.git` objects are omitted. Sensitive exclusions are
  not enumerated at all: the per-run bundle records neither their paths nor
  their existence, class, count, sizes, hashes, or link targets.
  Collection is bounded to 64 MiB per file, 512 MiB total, 50,000 examined
  entries, 30 seconds, and a 256 MiB free-disk reserve. Repeated filesystem
  failures are aggregated by error type instead of producing unbounded records.
- Public DSI Slurm job bundles under `logs/dsi-slurm-artifacts/` follow the
  same text-only and redaction policy; `job.json`, `.out`, and `.err` evidence
  is eligible while binary or credential-bearing payloads remain excluded.
- Documented Modal execution logs matching
  `logs/modal_<kind>_<YYYYMMDD>_<HHMMSS>.log` are classified as public worker
  evidence and pass through the same text sanitizer.
- JSON and JSONL are redacted structurally. Free-form text and YAML-like
  assignments redact common prefixed credential names such as
  `OPENAI_API_KEY`, `AWS_SECRET_ACCESS_KEY`, `client_secret`, `apiKey`,
  `accessToken`, and `private_key`, together with configured environment
  credential values,
  credential-bearing URIs, JSON Web Tokens, bearer tokens, nested sensitive
  blocks, raw private-key blocks, and recognizable provider tokens. Direnv
  sources and caches (`.envrc` and `.direnv/`) are never artifact sources.
  References to credential, sealed-evaluation, privileged-runtime, and other
  sensitive excluded paths inside otherwise-public traces are redacted by the
  same eligibility policy. If detectable credential material remains after
  sanitization, the whole file is withheld and collection is marked partial.
  Configured credentials of at least
  four characters are redacted exactly even without a recognizable provider
  prefix. A shorter configured credential makes trace preparation fail closed
  to a metadata-only result instead of risking broad or incomplete replacement.
- The combined child stdout/stderr stream mixes public workers with privileged
  runtime and evaluator events, so it is never forwarded or copied into the
  public bundle. While the child is active, the parent retains the bounded raw
  stream only in an unlinked mode-`0600` spool. After the child stops, the
  parent materializes it in private, per-run, mode-`0700` scratch under
  `/tmp/neurico-trace-scratch/<run-id>/`; scratch files use mode `0600`. New or
  changed unclassified logs, generated binaries, and other
  files that cannot enter the sanitized public bundle are retained there under
  the same 64 MiB per-file and 512 MiB per-run limits. Known sealed,
  evaluator-owned, credential-path, and private runtime locations are never
  duplicated into scratch. Scratch is not mentioned in ACP messages or public
  trace metadata and normally disappears when Harbor destroys the task
  container. Manager history remains in NeuriCo's private `.neurico` state and
  is not duplicated. Collection is final-state based: a workspace file that a
  worker creates and deletes before the supervised process exits cannot be
  recovered unless its content also appeared in stdout or a durable NeuriCo
  log.
- `workspace/snapshot.json` indexes preserved public text and aggregate public
  exclusions; `collection.json` records collection policy and failures;
  `run.json` records configuration and lifecycle outcome without child-output
  payloads or payload-derived counts;
  `manifest.json` hashes the completed bundle and labels collection as
  `scope_complete`, `partial`, or `minimal`. Size, time, free-space, inventory, and
  filesystem omissions make the status partial rather than silently claiming
  completeness. `scope_complete` means only that classified public UTF-8 text
  was completely collected; private manager history, mixed-authority stdout,
  and sealed/runtime
  material are named policy omissions rather than implied to be captured. A
  new or changed unclassified log also makes collection partial without
  revealing its path. Runtime inventory is limited to Python, platform,
  NeuriCo, and adapter versions. Workspace Git provenance is limited to HEAD so hidden
  material cannot affect dirty-state metadata. The adapter-source summary
  additionally records dirty state and changed-entry count, without filenames,
  subjects, or diffs. Private chain-of-thought that a provider does not emit is
  not available to the adapter.
- Trace preparation is observational. If credential redaction or the pre-run
  inventory cannot be initialized safely, NeuriCo still runs normally and the
  parent publishes only a metadata bundle identifying the trace-preflight
  error. Per-file snapshot failures mark capture incomplete and are summarized
  by type in `collection.json`; collection continues for other eligible files
  unless a time or free-space limit is reached. If storage cannot be trusted or
  even the metadata fallback cannot be published, the adapter emits a generic
  trace-unavailable warning without changing the child exit result.
- Harbor runs NeuriCo in embedded workspace mode. NeuriCo-owned dependency
  metadata and its virtual environment live under `neurico-research-env/`,
  while the task's root `.venv` is never read, reused, or removed by the
  adapter. Harbor's verifier remains responsible for its own environment.
- Task-provided MCP servers are rejected when the ACP session is created. The
  adapter does not silently start a run without capabilities declared by the
  benchmark.
- Harbor runs its own verifier after NeuriCo exits; the adapter does not inspect
  or translate Harbor's verifier.

The Python source runtime exposes a locked `codex` launcher. It uses an already
available Codex CLI only when its version exactly matches the adapter pin;
otherwise it installs `@openai/codex@0.147.0` into the execution user's cache.
This mirrors Harbor's own Codex-agent installation strategy while keeping the
NeuriCo source manifest compatible with Harbor's `python-uv` runtime. The
launcher also ensures that Git, which AutoResearch needs for local checkpoints,
is present in minimal task images.

## Local Harbor with ChatGPT authentication

First authenticate the host Codex CLI and confirm the active method:

```bash
codex login
codex login status
```

Then expose only the cached login file to the task container. A local job
configuration looks like this:

```yaml
agents:
  - name: acp
    model_name: openai/gpt-5.6-sol
    override_timeout_sec: 3600
    env:
      NEURICO_CODEX_AUTH_FILE: /run/secrets/neurico-codex-auth.json
      NEURICO_HARBOR_AUTORESEARCH_ITERATIONS: "1"
      NEURICO_HARBOR_TIME_LIMIT_SECONDS: "3480"
    kwargs:
      source:
        repo_url: https://github.com/ChicagoHAI/neurico
        ref: <branch-tag-or-commit>
        source_dir: .
        manifest_path: integrations/harbor/harbor-agent.json

environment:
  type: docker
  mounts:
    - type: bind
      source: /absolute/host/path/to/.codex/auth.json
      target: /run/secrets/neurico-codex-auth.json
      read_only: true
```

Use a branch while developing and a full commit SHA once the integration is
stable. This executes on the local Harbor/Docker stack and consumes the Codex
entitlement of the ChatGPT account represented by the mounted login cache. The
cache is a secret and must never be committed or included in job artifacts.

## Hosted Harbor

Hosted automation should use a per-user credential, an enterprise Codex access
token exposed through an appropriate provider, or Harbor's hosted inference
gateway. Gateway mode is configured with:

```yaml
agents:
  - name: acp
    model_name: openai/gpt-5.6-sol
    override_timeout_sec: 3600
    env:
      NEURICO_HARBOR_AUTORESEARCH_ITERATIONS: "1"
      NEURICO_HARBOR_TIME_LIMIT_SECONDS: "3480"
    kwargs:
      source:
        repo_url: https://github.com/ChicagoHAI/neurico
        ref: <full-commit-sha>
        source_dir: .
        manifest_path: integrations/harbor/harbor-agent.json
```

Supply `HOSTED_INFERENCE_TOKEN` and `HOSTED_INFERENCE_URL` as Harbor secrets,
not literal configuration values. The gateway must expose an OpenAI Responses
API-compatible endpoint.

The adapter intentionally does not accept raw NeuriCo command-line arguments.
Benchmark controls are added as individually validated `NEURICO_HARBOR_*`
environment variables so a Harbor config cannot silently enable unrelated
research-publication behavior. Iteration count and the optional whole-run time
limit are the only such controls; model choice belongs to Harbor, and paper
generation remains off.

## Contract tests

```bash
cd integrations/harbor
uv sync --frozen --extra dev
uv run --frozen --extra dev pytest -q tests/contract_checks.py
```

The suite includes a real stdio ACP handshake and model-selection round trip,
and verifies that the child selects headless manager-driven Auto HITL instead
of ordinary mechanical AutoResearch. Model-backed execution is replaced at the
process boundary during contract tests, so the tests do not consume model
usage.
