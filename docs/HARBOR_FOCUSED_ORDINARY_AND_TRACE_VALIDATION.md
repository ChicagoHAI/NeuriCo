# Harbor focused ordinary integration validation

Branch: `harbor-focused-ordinary-integration`.
Base: upstream main `42ff31321b86a5f4c6984433b02c9fe009e3e95f`.
Implementation is in progress; no end-to-end completion claim yet.

## Checkpoint 1: workflow routing and native invocation

Ported the existing optional workflow selector and focused managed ordinary
invocation into the merged parent supervisor. AutoResearch remains the default.
Ordinary runs do not parse or apply AutoResearch iteration/deadline controls or
interpret exit 124 as successful best-checkpoint finalization. Both workflows
use the existing cooperative-stop bridge and process supervision.

Validation (2026-11-12, macOS ARM64, Python 3.12.13):

```sh
uv sync --project integrations/harbor --locked --extra dev
integrations/harbor/.venv/bin/python -m pytest \
  integrations/harbor/tests/contract_checks.py \
  integrations/harbor/tests/workflow_checks.py -q
```

Result: **88 passed, 7 skipped**. Skips are the Linux process-supervision tests,
reserved for checkpoint 8. The first restricted run could not execute `ps` in
one cancellation test; rerunning with local process inspection enabled passed.
No model calls were made. `git diff --check` passed.

## Checkpoint 2: managed benchmark deliverables

Propagated `benchmark_mode` into the managed experiment path, its expected
outputs, completion validator, and execution prompt. The exemption applies to
unscored ordinary benchmark execution; scored contracts and AutoResearch
instructions remain unchanged. Task-requested reports remain in the full task
instruction. Existing planning/review phases are unchanged.

Validation (2026-11-12):

```sh
integrations/harbor/.venv/bin/python -m pytest \
  tests/test_managed_ordinary_report.py tests/test_focused_managed_ordinary.py \
  tests/test_managed_task_context.py tests/test_hitl_required_artifacts.py -q
```

Result: **109 passed**. Includes pipeline flag propagation, complete rendered
execution instructions for six domains, task-requested reports, ordinary report
validation, scored artifact contracts, and AutoResearch prompt equality with the
benchmark flag on/off. `git diff --check` passed. No model calls were made.

## Checkpoint 3: provider configuration

Ported the tested `allow_login_shell = false` setting and optional validated
reasoning effort. Set the existing worker model override to Harbor's backend
model, preventing an inherited host override from superseding the task model.
The native manager keeps using the same isolated Codex home. Recorded requested
version/model/effort separately; observed settings will come from retained
provider records in the collection checkpoint, not from configuration guesses.

Validated Codex **0.167.1** using the adapter launcher with a temporary local
cache (`--version` reported `codex-cli 0.167.1`). The pinned CLI successfully
parsed the generated model/high-effort/non-login-shell configuration using
`features list`; no inference or login change was performed.

```sh
integrations/harbor/.venv/bin/python -m pytest \
  integrations/harbor/tests/contract_checks.py \
  integrations/harbor/tests/workflow_checks.py \
  integrations/harbor/tests/provider_checks.py -q
```

Result: **98 passed, 7 Linux-only skipped**. Checks include actual native manager
command/environment construction, native worker model/environment construction,
authentication source immutability, optional/default effort and invalid values.
`git diff --check` passed.

## Checkpoint 4: collect existing records before cleanup

Added opt-in private collection in the existing parent supervisor. Temporary
idea/provider directories now survive stop, drain and collection, including
error paths. Public-store/public-export failure cannot skip private collection.
The existing spool can retain the complete stream when enabled and exports it
directly through the existing sanitizer (incrementally, with multiline state),
without the scratch prefix limit. Available sanitized output survives later
stream read failure. The public exporter and default limits remain unchanged.

The archive retains recursive research/state/log records, native provider
sessions and logs, manager SQLite backups, additional changed outputs including
binaries, and otherwise unretained scratch records. Credentials are excluded or
sanitized. SQLite redaction occurs in a standalone backup; FTS indexes are
rebuilt as needed and copied pages are vacuumed, leaving live history untouched.
Manifest records include hashes, source families, gaps, observed provider
settings, lifecycle data, runtime versions and adapter revision.

Validation (2026-11-12): combined adapter suites **116 passed, 7 Linux-only
skipped**; after adding the interrupted-stream-prefix case, the private suite
passed **19 tests**. A separate strengthened check exported **65 MiB** of stream
through the collector and verified its retained length (**1 passed**). Tests
cover normal/failed child, cancellation, timeout, spawn/output failure, public
storage/export failure, temporary-source removal, native SQLite readability and
redaction, binary preservation, scratch truncation/recovery, inventory hashes,
and retaining prior files when finalization fails. `git diff --check` passed.

This checkpoint verifies final source collection. Invocation coverage and
retention before destructive rollback/overwrite remain checkpoint 5; complete
end-to-end evidence is not yet claimed. No model calls were made.
