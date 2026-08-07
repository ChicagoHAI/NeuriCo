# GitHub Integration

GitHub integration is optional. NeuriCo can run entirely locally with
`--no-github`, or it can create a research repository during submission and
push run artifacts to it.

## Configure GitHub

Create a classic personal access token with `repo` scope, then add it to `.env`:

```dotenv
GITHUB_TOKEN=your_token
GITHUB_ORG=
```

Leave `GITHUB_ORG` empty to use the token owner's personal account. Set it to an
organization name only when the token can create repositories in that
organization.

- **Docker:** run `./neurico config` or edit `.env` directly.
- **Local `uv`:** edit `.env` directly.

Do not commit `.env` or print the token in logs.

## Submit with GitHub enabled

GitHub is enabled when `GITHUB_TOKEN` is present and `--no-github` is omitted.

| Docker | Local `uv` |
| --- | --- |
| `./neurico submit ideas/my_idea.yaml` | `uv run python src/cli/submit.py ideas/my_idea.yaml` |

Submission validates the idea, creates the repository, clones it beneath the
configured workspace parent, writes research metadata, and prints the
`<idea_id>`.

Create the repository in a configured organization:

| Docker | Local `uv` |
| --- | --- |
| `./neurico submit ideas/my_idea.yaml --github-org MyOrg` | `uv run python src/cli/submit.py ideas/my_idea.yaml --github-org MyOrg` |

Create a private repository:

| Docker | Local `uv` |
| --- | --- |
| `./neurico submit ideas/my_idea.yaml --private` | `uv run python src/cli/submit.py ideas/my_idea.yaml --private` |

## Run the submitted idea

Do not add `--no-github` when you want run artifacts pushed to the connected
repository.

### Standard

| Docker | Local `uv` |
| --- | --- |
| `./neurico run <idea_id> --provider claude --full-permissions` | `uv run python src/core/runner.py <idea_id> --provider claude --full-permissions` |

### AutoResearch

| Docker | Local `uv` |
| --- | --- |
| `./neurico run <idea_id> --provider claude --full-permissions --autoresearch --autoresearch-iterations 3` | `uv run python src/core/runner.py <idea_id> --provider claude --full-permissions --autoresearch --autoresearch-iterations 3` |

### HITL AutoResearch

| Interface | Docker | Local `uv` |
| --- | --- | --- |
| Web | `./neurico hitl-web <idea_id>` | `uv run python src/cli/hitl_web.py <idea_id>` |
| Terminal | `./neurico hitl-cli <idea_id>` | `uv run python src/cli/hitl_cli.py <idea_id>` |

Use `/run` in the HITL interface and enable GitHub when prompted.

## Run without GitHub

Add `--no-github` to both submission and ordinary run commands:

| Docker | Local `uv` |
| --- | --- |
| `./neurico submit ideas/my_idea.yaml --no-github` | `uv run python src/cli/submit.py ideas/my_idea.yaml --no-github` |
| `./neurico run <idea_id> --no-github --provider claude --full-permissions` | `uv run python src/core/runner.py <idea_id> --no-github --provider claude --full-permissions` |

Results remain in the configured local workspace.

## Existing resources

After submission, you may add datasets, papers, or helper code to the generated
workspace before running. Commit and push those files in the workspace
repository so the remote and local workspace agree before NeuriCo begins.

For host-local data that should not be committed, declare it through
`local_resources` and use the workflow in
[`LOCAL_IDEA_SUBMISSION.md`](LOCAL_IDEA_SUBMISSION.md).

## Troubleshooting

### Token is missing or invalid

Confirm `GITHUB_TOKEN` is present in `.env`, uses a classic token with `repo`
scope, and has not expired or been revoked.

### Organization repository creation fails

Confirm the token owner is a member of the organization and that the
organization permits personal access tokens and repository creation. Try a
personal repository by leaving `GITHUB_ORG` empty.

### Repository already exists

NeuriCo normally includes a short hash in generated repository names. Use
`--no-hash` only when you intentionally want a stable name and have confirmed
that it is available.

### Push fails after a run

The local workspace still contains the research artifacts. Inspect its Git
status and remote, resolve authentication or branch protection issues, and push
manually if necessary.
