# Paper comparison: NeuriCo vs zero-shot baselines

Five arena ideas, each run by eight methods, to compare the papers they produce.
This page says where every output is and how to read it. It is written for
whoever (person or agent) builds the paper judge.

## What is being compared

| Method label | What it is |
| --- | --- |
| `neurico-claude-claude-opus-5-5` | NeuriCo pipeline, Claude Code, Opus 5.5 |
| `neurico-codex-gpt-5-6-sol` | NeuriCo pipeline, Codex, GPT-5.6-sol |
| `neurico-claude-claude-fable-5-1` | NeuriCo pipeline, Claude Code, Fable 5.1 (added 2026-10-03) |
| `neurico-codex-gpt-6-astra` | NeuriCo pipeline, Codex, GPT-6-Astra (added 2026-10-03) |
| `zero-shot-claude-claude-opus-5-5` | One Claude Code session, Opus 5.5 |
| `zero-shot-claude-claude-fable-5-1` | One Claude Code session, Fable 5.1 |
| `zero-shot-codex-gpt-5-6-sol` | One Codex session, GPT-5.6-sol |
| `zero-shot-codex-gpt-6-astra` | One Codex session, GPT-6-Astra |

Ideas, in run order (YAMLs in `ideas/arena_candidates/`):
`human_vs_llm_prompter`, `keeping_secrets`, `lies_vs_hallucinations`,
`isolating_knowledge_updates`, `sounds_like_ai`.

Three jobs run at all times, one per slot (NeuriCo, zero-shot Claude Code,
zero-shot Codex), with no time limits. Each slot works through the ideas in
order. A failed NeuriCo run is resumed automatically; an interrupted zero-shot
session is continued, and one that ended normally without a paper gets a
write-up-only session in the same workspace (recorded as `resumed` / `retries`
in the manifest). Started 2026-10-02.

## Get the list of results

Do not hard-code paths; workspace names contain a random hash. Ask for the
manifest:

```bash
uv run python scripts/results_manifest.py                # table, all 30 runs
uv run python scripts/results_manifest.py --papers-only  # only finished papers
uv run python scripts/results_manifest.py --json         # machine-readable
```

It also writes `logs/batch/manifest.json`. Rerun it any time; it merges all
batches and reflects the current state while runs are still going. Each run has:

| Field | Meaning |
| --- | --- |
| `idea`, `method`, `provider`, `model`, `label` | What was run |
| `outcome` | `paper`, `no_paper` (finished without a compiled PDF), `running`, `pending` |
| `workspace` | Local directory of the run |
| `paper_pdf`, `paper_tex` | Paths to the paper, when present |
| `github_url` | Public repository with the same content |
| `retries`, `resumed`, `provider_error` | Whether the run needed a retry, was finished by a second session in the same workspace, or hit a provider failure |

Only compare runs whose `outcome` is `paper`. A `running` workspace may already
contain a half-written `main.tex`.

## Where things are

Everything is under `/data/hypogenicai/workspaces/` and mirrored to the
`Hypogenic-AI` GitHub organization under the same name.

| Run type | Workspace / repository name |
| --- | --- |
| NeuriCo | `{idea-slug}-{hash}-{provider}-{model}` |
| Zero-shot | `{idea-slug}-{hash}-zeroshot-{provider}-{model}` |

Inside a workspace:

| Path | Content | In both kinds of run |
| --- | --- | --- |
| `paper_draft/main.pdf` | The paper | yes |
| `paper_draft/main.tex` | LaTeX entry point (NeuriCo splits the body into `paper_draft/sections/*.tex`) | yes |
| `README.md`, `src/`, `results/` | Summary, code, raw results | yes |
| `logs/*_transcript.jsonl` | Full agent transcripts | yes |
| `REPORT.md`, `literature_review.md`, `resources.md`, `planning.md`, `papers/` | Pipeline stage outputs | NeuriCo only |
| `.neurico/idea.yaml` or `.baseline/idea.yaml` | The idea the run received | one each |
| `.baseline/run.json` | Model, command, timing, exit status | zero-shot only |

Files in workspaces are owned by the container user but world-readable. Run
`git` there with `-c safe.directory='*'`.

Batch-level logs are in `logs/batch/<batch_id>/` (one log per run and a
`status.json`); a rerun or resumed run appears in a later batch directory.
`scripts/batch_status.sh` prints a health summary.

## Notes for building a judge

- **Blind the judge.** Workspace names, repository URLs, `README.md` and the
  logs all reveal the method and model. Give the judge only the paper (PDF or
  text extracted from it) under a neutral ID.
- **Formatting leaks the method too.** NeuriCo papers use the NeurIPS style
  file and are split into section files; zero-shot papers use whatever the
  agent chose. Page counts also differ a lot (5 to 13 pages for the first
  idea). Judging on extracted text, and telling the judge to ignore template
  and length, reduces this.
- **Compare within an idea.** Papers on different ideas answer different
  questions; pair only papers that share `idea`. Eight methods give up to 28
  pairs per idea.
- **Order effects.** Present each pair in both orders.
- **Papers were not checked against their code.** A judge that reads only the
  paper rates the write-up, not whether the reported numbers are real. The
  `results/` directory and transcripts are there if a verification step is
  wanted.
- **Missing papers are an outcome.** A run with `no_paper` failed to deliver;
  decide up front whether it counts as a loss in every pairing or is left out.

## Known deviations in this batch

- `human_vs_llm_prompter`, zero-shot Opus 5.5: the first session ended
  without a paper (it started background jobs and ended its turn to wait for
  them, which ends a non-interactive session). A second Opus 5.5 session was
  started in the same workspace to finish it; earlier logs are kept and the
  second session's are `logs/zeroshot_claude_resume1*`.
- The first two zero-shot runs (`human_vs_llm_prompter`, Opus 5.5 and
  GPT-5.6-sol) used an earlier prompt: it lacked the note that the session is
  non-interactive and still said "keep total API spend modest". All later
  zero-shot runs use the corrected prompt in `baseline/prompts/zero_shot.md`.
- `human_vs_llm_prompter`, NeuriCo GPT-5.6-sol: the first attempt failed after
  12 minutes with "Selected model is at capacity"; it was resumed in the same
  workspace and completed.
- NeuriCo experiment-runner instructions gained a note that the session is
  non-interactive (do not end the turn while background jobs run) on
  2026-10-03, after NeuriCo Opus 5.5 on `sounds_like_ai` failed that way and
  was resumed. Runs started after that have it: NeuriCo GPT-5.6-sol on
  `sounds_like_ai`, and all NeuriCo Fable 5.1 and GPT-6-Astra runs.
- NeuriCo Fable 5.1 and GPT-6-Astra runs use a shared Hugging Face cache on
  `/data` (to keep model downloads off the root disk); earlier NeuriCo runs
  downloaded into their own container.
- A shared OpenRouter key with a $100/day cap was exhausted on 2026-10-02 and
  2026-10-03, so API access differed by when a run happened. Ideas 2
  (`keeping_secrets`) and 5 (`sounds_like_ai`) have runs with and without an
  API judge; ideas 1 and 4 are unaffected and idea 3 is level among its first
  five papers. Per-run detail: `logs/openrouter_fairness_audit_2026-10-03.md`
  (spend by run: `logs/openrouter_audit_2026-10-03.md`).
- `lies_vs_hallucinations`, zero-shot Fable 5.1: the session finished with its
  paper, but the launcher reported a false failure (the launch script was
  edited while this 16-hour job was running), so a one-minute write-up-only
  session was started in the same workspace. It changed nothing in the paper;
  the `resumed` flag on this run is not meaningful.
