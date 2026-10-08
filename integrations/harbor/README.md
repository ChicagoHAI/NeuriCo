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
  Harbor's agent timeout so native finalization and `.venv` cleanup have time
  to finish; for example, use 3480 seconds with a 3600-second Harbor timeout.
  If native shutdown itself stalls, the adapter terminates the isolated NeuriCo
  process group after a 30-second grace period. Harbor's ACP launcher does not
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
- NeuriCo may create a workspace `.venv` while its agents and internal scorer
  run. After the AutoResearch child process exits, the adapter removes that
  environment if it did not exist before the Harbor session. Dependency
  metadata and research artifacts remain, while a benchmark-provided `.venv`
  is preserved. Harbor's verifier is responsible for its own environment.
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
