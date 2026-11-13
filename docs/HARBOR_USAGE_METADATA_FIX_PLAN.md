# Preserve Harbor usage metadata

Status: implemented and locally validated on 2026-11-12.
See `HARBOR_FOCUSED_ORDINARY_AND_TRACE_VALIDATION.md` for results.
Branch: `harbor-focused-ordinary-integration`.

## Objective and scope

Preserve the eight analysis-related fields incorrectly redacted in the live
Harbor pilot, using NeuriCo's existing sanitizer. This changes evidence collection,
not research prompts, workflow, provider calls, scoring, or runner behavior.

Tool-description redaction and rejected trace files remain separate issues.
Completing this fix does not establish overall evaluation readiness or recover
values already removed from previous archives.

## Confirmed cause

In `integrations/harbor/neurico_harbor_agent/artifacts.py`,
`_is_sensitive_field_name` classifies names containing `token` or `tokens` as
sensitive unless their remaining words belong to an existing metadata allowlist.
`_sanitize_serializable` applies that classification before descending into
objects or retaining numeric values. Consequently, both individual counters and
whole usage objects are replaced by `[REDACTED_SECRET_FIELD]`.

The pilot exposed these affected fields:

| Fields | Information lost |
| --- | --- |
| `cached_input_tokens`, `cache_write_input_tokens`, `reasoning_output_tokens` | Usage counters |
| `last_token_usage`, `thread_token_usage`, `turn_token_usage` | Entire usage objects |
| `time_to_first_token_ms` | Response latency |
| `fallback_token_limit_override` | Token-limit configuration |

Adding general words such as `write` to the existing descriptor allowlist is too
broad: a local reproduction showed that it would also exempt `write_token`.

## Implementation

### 1. Add regressions for the observed provider records

Extend `integrations/harbor/tests/contract_checks.py` with small synthetic records
matching the pilot's `turn.completed`, `token_count`, `token_usage_record`,
`task_complete`, and metadata shapes. Include all eight fields, nested counters,
zero values, and null optional values. Exercise the existing `_safe_text_payload`
entrypoint for JSON and JSONL, rather than testing only the name classifier.

Assert that the benign records survive unchanged after parsing. Include
credential-bearing cases proving that `access_token`, `refresh_token`,
`write_token`, and `api_key` still redact. Include a configured secret inside an
exempt usage object to prove that preserving its parent does not bypass scanning
or recursive sanitization. Run the targeted regressions to establish the current
failure before changing implementation.

### 2. Correct the existing field classifier

Add a small constant containing exactly the eight field names above. In
`_is_sensitive_field_name`, recognize these exact names as metadata before the
generic token-name rule. Do not exempt arbitrary prefixes, suffixes, or combinations
of words, and do not expand the general descriptor allowlist.

Keep the recursive sanitizer and credential-value detection unchanged. An exempt
field proceeds through the existing value handling: dictionaries and lists are
visited recursively, strings still undergo sanitization, and numeric/null values
remain intact. Do not skip sanitization for an entire `usage` object.

This is a shared-classifier correction: it intentionally preserves these harmless
fields in both public and private exports that use the classifier. Public artifact
selection, private/public separation, and credential protections remain unchanged.
No separate private-only redaction policy or gapbench-side reconstruction is needed.

### 3. Verify archive collection and existing behavior

Extend the existing private archive test in
`integrations/harbor/tests/internal_trace_checks.py` to copy a representative
provider JSONL record containing the nested usage objects and counters. Verify
that the retained file is parseable, its analysis values match the source, its
inventory hash/size match the written bytes, and collection reports no gaps.
Include a credential value to verify redaction on this same collection path.

From the NeuriCo integration worktree, run:

```sh
PYTHONPATH="$PWD:$PWD/src:$PWD/integrations/harbor" \
  integrations/harbor/.venv/bin/python -m pytest \
  integrations/harbor/tests/contract_checks.py \
  integrations/harbor/tests/internal_trace_checks.py \
  integrations/harbor/tests/retention_hook_checks.py -q
git diff --check
```

If the contract suite includes Linux-only skips, record them explicitly; this
field-classification fix does not require repeating process-supervision tests or
launching a model. Do not treat the redacted pilot files as recoverable originals.

### 4. Document and commit locally

Add the concrete change, commands, and actual test outcomes to
`docs/HARBOR_FOCUSED_ORDINARY_AND_TRACE_VALIDATION.md`. Explicitly retain the
unresolved status of tool-description redaction and missing trace files.

Commit the implementation, regressions, and validation note as one focused local
commit after checks pass. Do not push or open a PR. No model run is needed for
this fix.

## Acceptance criteria

- All eight observed fields survive JSON/JSONL sanitization with their original
  non-secret values and nested structure.
- Existing input/output/total counters remain unchanged.
- Credential fields and configured credential values remain protected, including
  when nested within a preserved usage object.
- The archive collection path preserves those values with valid inventory hashes
  and no collection gaps for the tested records.
- Existing relevant regressions pass; documentation accurately states coverage.
- No changes to NeuriCo's workflow, benchmark results, or historical raw evidence.

These criteria cover the observed usage-metadata bug. They do not claim that a
finite field list anticipates every future provider schema or every analysis need.
