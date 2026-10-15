# Zero-shot baselines

A baseline for the NeuriCo pipeline: one Claude Code or Codex session, started
with full permissions and a single instruction, takes an idea all the way to a
paper. There is no resource-finder stage, no paper-writer stage, and no skills
or templates; the agent gets the idea and
[`prompts/zero_shot.md`](prompts/zero_shot.md), nothing else.

## Run one baseline

```bash
./neurico baseline ideas/my_idea.yaml --provider claude --model claude-opus-5-5
./neurico baseline ideas/my_idea.yaml --provider codex  --model gpt-5.6-sol
```

| Flag | Purpose |
| --- | --- |
| `--provider claude\|codex` | Which CLI runs the session (required) |
| `--model <name>` | Model passed to the CLI; default is the CLI's own default |
| `--timeout <seconds>` | Wall-clock limit for the session (default 0 = no limit) |
| `--no-github` | Keep the workspace local |
| `--private` | Create the GitHub repository as private |
| `--no-hash` | Leave the random hash out of the workspace name |
| `--resume-workspace <name>` | Start a new session in an existing baseline workspace to finish a run that ended without a paper |

The idea file is the same YAML that `./neurico submit` takes. It is read
directly; baselines do not go through `ideas/submitted/`.

`./neurico baseline` needs an image that contains `baseline/`. Until the
published image does, build the local overlay once with
`scripts/build_local_image.sh`.

## Run NeuriCo and the baselines together

`scripts/run_methods.py` runs ideas through every row of its `METHODS` list.
Comment rows in or out there. Three jobs run at all times, one per slot
(NeuriCo, zero-shot Claude Code, zero-shot Codex); each slot starts its next
job as soon as the previous one finishes.

```bash
scripts/run_methods.py ideas/a.yaml ideas/b.yaml --gpus 0,1,2,3
scripts/run_methods.py ideas/a.yaml --only zero-shot --dry-run
scripts/run_methods.py --resume-baseline my-idea-9c1e-zeroshot-claude-opus-5-5
```

`--gpus` gives each run one GPU, the least used at launch. A failed NeuriCo run
is resumed and a zero-shot run without a paper gets a new session in its
workspace, up to `--retries` times. Logs and `status.json` go to
`logs/batch/<batch_id>/`; `scripts/batch_status.sh` summarizes health and
`scripts/results_manifest.py` lists every run's outputs. Ctrl-C kills the
running containers.

## What a baseline run produces

Workspaces live in the same parent directory as NeuriCo workspaces
(`config/workspace.yaml`) and follow the same naming, with a `zeroshot` label
so the two can never collide:

| Run | Workspace / repository name |
| --- | --- |
| NeuriCo | `{slug}-{hash}-{provider}-{model}`, e.g. `my-idea-a3f2-claude-opus-5-5` |
| Zero-shot | `{slug}-{hash}-zeroshot-{provider}-{model}`, e.g. `my-idea-9c1e-zeroshot-codex-gpt-5-6-sol` |

Inside the workspace:

| Path | Content |
| --- | --- |
| `paper_draft/main.tex`, `main.pdf` | The paper (same location NeuriCo uses) |
| `src/`, `results/`, `README.md` | Code, raw results, summary |
| `logs/zeroshot_prompt.txt` | The exact instruction the agent received |
| `logs/zeroshot_<provider>.log` | Streamed agent output |
| `logs/zeroshot_<provider>_transcript.jsonl` | Full agent transcript (stream JSON) |
| `.baseline/idea.yaml`, `.baseline/run.json` | Idea, and run record (model, command, timing, exit status, whether a paper exists) |

## What is shared with NeuriCo

- Provider command and environment: `core.agent_cli`
- Log and transcript capture, with API keys redacted as output streams:
  `core.agent_runner.run_prebuilt_cli_agent`
- Repository creation, naming, clone, commit and push: `core.github_manager`.
  The agent is told not to commit or push; the harness publishes when the
  session ends, including after a timeout or failure.
- API key protection: `core.security`. Keys are redacted by pattern and by the
  exact values of credential-like environment variables. Before pushing, a
  baseline also scans every publishable text file in the workspace, not only
  `logs/`, because nothing supervises what a single session writes.
