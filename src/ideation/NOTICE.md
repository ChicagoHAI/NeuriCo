# Origin of `src/ideation/` and `templates/ideation/`

The ideation stages (`problem -> ideation -> idea_judge`), their JSON schemas, the stage
prompts, the writing rules and the cross-checks were copied and adapted from **sai-review**
(SAI-Labs-HQ/sai-review, private, no public licence; local checkout
`/net/spaces/chenhao/chai-lab/haokunliu/veritas-workspace/sai-review`, HEAD `7f19a45`),
package `src/sai_digest/` (the daily safety digest) and `src/sai_ideator/tools/`.

Copied with the owner's approval on 2026-10-21 ("Yes, copy and adapt"), for use inside
NeuriCo. The port follows `docs/IDEATION_INTEGRATION.md` section 4.1: only the three
ideation stages and their supporting code were taken; the digest's scrape, sync, living-run,
editor, preview, assemble, publish, Docker runner, registry/KB implementation, web-search tool
and `sai_ideator` pipeline (with its proprietary heuristics) were deliberately not ported.

## Files derived from sai-review

| NeuriCo file | sai-review source (`src/sai_digest/` unless noted) | What changed |
| --- | --- | --- |
| `src/ideation/schemas/problem.schema.json` | `schemas/problem.schema.json` | verbatim |
| `src/ideation/schemas/ideas.schema.json` | `schemas/ideas.schema.json` | `neurico` block gains `job_kind`, `finding_id`, `evaluation`, `models`, `evals`; `expected_outputs[].description`; optional idea `category`; domain described as `ai_safety` |
| `src/ideation/schemas/ideas_ranked.schema.json` | `schemas/ideas_ranked.schema.json` | verbatim |
| `src/ideation/stages.py` | `stages.py` | trimmed to `context` (code) + the three agent stages; NeuriCo input names |
| `src/ideation/runtime.py` | `runtime.py` (`_prepare_workspace`, `_validate_outputs`, `_commit_outputs`, `_attempt_agent_stage`, `_check_problem/_check_ideas/_check_ranked`, `method_overlaps`, `notes_flag_suspicious`, `prompt_version`, `stage_prompt`) | the Codex runner, manifest, resume, flock, KB sync, scrape, preview, assemble and budget loop are replaced by `core.agent_factory` (retries, validation feedback, usage, ledger) |
| `src/ideation/writing_rules.py` | `brief.py` (`words`, `word_count`, `sentences`, `count_syllables`, `flesch_kincaid_grade`, `shingles`, `repeated_shingles`, `check_prose_hygiene`, `check_detail_caps`, `DETAIL_CAPS`, the id/file/pipeline regexes) | regexes re-targeted at NeuriCo ids and vocabulary; the brief gates were not ported |
| `src/ideation/dedup.py` | `registry.py` (`norm_title`, `candidates`) | runs over the unified knowledge base (`safety_kb/kb.sqlite` nodes) instead of the digest registry |
| `src/ideation/to_job.py` | `neurico.py` (`to_neurico`) | adds the NeuriCo job-spec projection (`queue/proposals/<run>/*.yaml`) |
| `src/ideation/events.py` | `events.py` | action vocabulary trimmed to the ideation run |
| `templates/ideation/AGENTS.md` | `skills/_workspace/AGENTS.md` | rewritten for the NeuriCo knowledge base and vocabulary |
| `templates/ideation/stage_prompt.md` | `skills/_workspace/stage_prompt.md` | adapted |
| `templates/ideation/skills/problem.md` | `skills/digest-problem.md` | rewritten (findings/runs/evals/models/gaps, one GPU + catalog models, newest-generation rule) |
| `templates/ideation/skills/ideation.md` | `skills/digest-ideation.md` | rewritten (same; the interim ideator's standards and generators) |
| `templates/ideation/skills/idea-judge.md` | `skills/digest-idea-judge.md` | rewritten (same) |
| `templates/skills/safety-kb/scripts/scholar_search.py` | `src/sai_ideator/tools/scholar_search.py` | verbatim apart from the lock-file name |
| `tests/test_ideation.py` | `tests/test_ideation.py`, `tests/test_digest.py` | the runner-seam pattern (fake agent writes canned stage outputs) and the scholar-search backoff tests |

The knowledge-base query tool (`templates/skills/safety-kb/scripts/kb.py`) was already modelled
on sai-review's `tools/kb.py` before this port; see `docs/KNOWLEDGE_BASE.md` section 6.
