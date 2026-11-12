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
