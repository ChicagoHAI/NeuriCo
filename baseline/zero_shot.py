"""
Zero-shot baseline: one agent session, one instruction, idea -> paper.

Unlike the NeuriCo pipeline (resource finder -> experiment runner -> paper
writer, each with its own prompt, skills and templates), this launches a single
Claude Code or Codex session with full permissions and one instruction that
contains the idea. It reuses NeuriCo's plumbing so runs stay comparable:

- the same provider commands and environment (core.agent_cli)
- the same streamed, key-sanitized log + transcript capture (core.agent_runner)
- the same workspace parent directory and repository naming, with a
  ``zeroshot-`` label so names never collide with NeuriCo runs:
      NeuriCo:   {slug}-{hash}-{provider}-{model}
      baseline:  {slug}-{hash}-zeroshot-{provider}-{model}
- the same GitHub publication path, including log sanitization
  (core.github_manager)

Usage (inside Docker, via ./neurico baseline):
    python baseline/zero_shot.py <idea.yaml> --provider claude --model claude-opus-5-5
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.agent_cli import build_agent_command, build_agent_environment  # noqa: E402
from core.config_loader import ConfigLoader  # noqa: E402
from core.github_manager import GitHubManager  # noqa: E402
from core.security import sanitize_files, sanitize_logs_directory, sanitize_text  # noqa: E402

METHOD = "zeroshot"
PROVIDERS = ("claude", "codex")
PROMPT_TEMPLATE = Path(__file__).parent / "prompts" / "zero_shot.md"
METADATA_DIR = ".baseline"
PAPER_PDF = Path("paper_draft") / "main.pdf"
DEFAULT_TIMEOUT = 0  # no wall-clock limit

# API keys the agent may use in experiments; only the names are put in the prompt.
EXPERIMENT_KEY_VARS = (
    "OPENROUTER_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "HF_TOKEN",
    "WANDB_API_KEY",
)

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def method_label(provider: str) -> str:
    """Label used where NeuriCo uses the bare provider, e.g. ``zeroshot-claude``."""
    return f"{METHOD}-{provider}"


def load_idea(idea_file: Path) -> Dict[str, Any]:
    with open(idea_file, "r", encoding="utf-8") as f:
        idea = yaml.safe_load(f)
    spec = idea.get("idea") if isinstance(idea, dict) else None
    if not isinstance(spec, dict) or not str(spec.get("title", "")).strip():
        raise ValueError(f"{idea_file} must contain an 'idea' mapping with a title.")
    if not str(spec.get("hypothesis", "")).strip():
        raise ValueError(f"{idea_file} must contain idea.hypothesis.")
    return idea


def format_time_budget(timeout: Optional[int]) -> str:
    """Sentence telling the agent how long it has; no limit means no rush."""
    if not timeout:
        return (
            "There is no time limit: doing the research properly and finishing "
            "the paper matters more than speed."
        )
    hours = timeout / 3600
    if hours >= 1:
        budget = f"{hours:g} hour{'' if hours == 1 else 's'}"
    else:
        budget = f"{round(timeout / 60)} minutes"
    return (
        f"Your time budget is about {budget}; plan the scope so that you finish "
        "with a complete paper inside it rather than an ambitious half-finished one."
    )


def available_api_keys(environment: Optional[Dict[str, str]] = None) -> str:
    environment = os.environ if environment is None else environment
    names = [name for name in EXPERIMENT_KEY_VARS if environment.get(name)]
    if not names:
        return "No LLM API keys are configured; use local open-weight models."
    listed = ", ".join(f"`{name}`" for name in names)
    line = f"API keys available as environment variables: {listed}."
    if "OPENROUTER_KEY" in names:
        line += (
            " Prefer OpenRouter (base URL https://openrouter.ai/api/v1) for LLM"
            " API calls."
        )
    return line


class _BlockDumper(yaml.SafeDumper):
    """Render multi-line strings as literal blocks so the idea reads as written."""


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.Node:
    if "\n" in value:
        # Literal style is only valid without trailing whitespace on a line.
        value = "\n".join(line.rstrip() for line in value.strip().splitlines())
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", value)


_BlockDumper.add_representer(str, _represent_str)


def build_prompt(
    idea: Dict[str, Any],
    timeout: Optional[int],
    environment: Optional[Dict[str, str]] = None,
) -> str:
    """Fill the one-shot instruction with the idea and the session facts."""
    spec = {key: value for key, value in idea["idea"].items() if key != "metadata"}
    idea_yaml = yaml.dump(
        {"idea": spec},
        Dumper=_BlockDumper,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=100,
    ).strip()
    template = PROMPT_TEMPLATE.read_text(encoding="utf-8")
    return (
        template.replace("{time_budget}", format_time_budget(timeout))
        .replace("{api_keys}", available_api_keys(environment))
        .replace("{idea_yaml}", idea_yaml)
    )


RESUME_NOTES = {
    # The earlier session ended normally without a paper: only the write-up is missing.
    "writeup": """
## Finish the write-up only

A previous session already did the research for this idea in the current
directory but stopped before writing the paper. Your job is only to write it
up. Do not run new experiments, do not rerun or extend earlier ones, and do
not change the code under `src/`.

Read what exists (`README.md`, the code under `src/`, the outputs under
`results/`, and the earlier session's transcript under `logs/`) and write the
paper from those results as they are. You may run light analysis over existing
result files to build tables and figures. If an experiment the earlier session
planned has no finished results, say so in the paper as a limitation rather
than filling the gap.
""",
    # The earlier session was cut short: pick up the research where it stopped.
    "continue": """
## Continuing an interrupted session

A previous session started this project in the current directory but was
interrupted before it finished; any background processes it had started were
killed. Do not start over. Look at what exists (`README.md`, the code under
`src/`, outputs under `results/`, `paper_draft/`, and the earlier session's
transcript under `logs/`), work out what is complete and what was cut off,
finish the remaining work, and complete the deliverables above.
""",
}


def open_existing_workspace(name: str, workspace_parent: Optional[Path] = None) -> Dict[str, Any]:
    """Locate a baseline workspace created by an earlier run."""
    parent = workspace_parent or ConfigLoader().get_workspace_parent_dir()
    work_dir = Path(parent) / Path(name).name
    if not (work_dir / METADATA_DIR / "run.json").is_file():
        raise ValueError(f"Not a baseline workspace: {work_dir}")
    run_info = json.loads((work_dir / METADATA_DIR / "run.json").read_text(encoding="utf-8"))
    return {
        "work_dir": work_dir,
        "repo_name": work_dir.name,
        "github_url": run_info.get("github_url"),
        "run_info": run_info,
    }


def generate_workspace_name(
    idea: Dict[str, Any], provider: str, model: Optional[str], no_hash: bool = False
) -> str:
    """Name a local-only workspace with NeuriCo's repository naming rules."""
    spec = idea["idea"]
    namer = GitHubManager.__new__(GitHubManager)  # naming needs no GitHub session
    fallback_id = f"{METHOD}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    return namer._generate_repo_name(
        spec.get("title", ""),
        spec.get("domain"),
        fallback_id,
        provider=method_label(provider),
        no_hash=no_hash,
        hypothesis=spec.get("hypothesis"),
        model=model,
    )


def write_metadata(work_dir: Path, idea: Dict[str, Any], run_info: Dict[str, Any]) -> None:
    metadata_dir = work_dir / METADATA_DIR
    metadata_dir.mkdir(parents=True, exist_ok=True)
    with open(metadata_dir / "idea.yaml", "w", encoding="utf-8") as f:
        yaml.dump(idea, f, default_flow_style=False, sort_keys=False)
    with open(metadata_dir / "run.json", "w", encoding="utf-8") as f:
        json.dump(run_info, f, indent=2)


def setup_gitignore(work_dir: Path) -> None:
    """Merge NeuriCo's research .gitignore (weights, datasets, caches, ...)."""
    from core.runner import ResearchRunner

    ResearchRunner._setup_workspace_gitignore(
        SimpleNamespace(project_root=PROJECT_ROOT), work_dir
    )


def prepare_workspace(
    idea: Dict[str, Any],
    provider: str,
    model: Optional[str],
    *,
    github_manager: Optional[GitHubManager],
    private: bool = False,
    no_hash: bool = False,
    workspace_parent: Optional[Path] = None,
) -> Dict[str, Any]:
    """Create the baseline workspace, GitHub-backed when a manager is given."""
    spec = idea["idea"]
    title = spec["title"]
    label = method_label(provider)

    if github_manager is not None:
        repo_info = github_manager.create_research_repo(
            idea_id=f"{METHOD}-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            title=title,
            description=title,
            private=private,
            domain=spec.get("domain", "research"),
            provider=label,
            no_hash=no_hash,
            hypothesis=spec.get("hypothesis", ""),
            model=model,
        )
        model_note = f" ({model})" if model else ""
        description = (
            f"{title} | Zero-shot {provider}{model_note} baseline on "
            f"{datetime.now().strftime('%Y-%m-%d')}"
        )
        repo_info["repo_object"].edit(description=" ".join(description.split())[:350])
        work_dir = Path(repo_info["local_path"])
        github_manager.clone_repo(repo_info["clone_url"], work_dir)
        return {
            "work_dir": work_dir,
            "repo_name": repo_info["repo_name"],
            "github_url": repo_info["repo_url"],
        }

    parent = workspace_parent or ConfigLoader().get_workspace_parent_dir()
    name = generate_workspace_name(idea, provider, model, no_hash=no_hash)
    work_dir = Path(parent) / name
    work_dir.mkdir(parents=True, exist_ok=False)
    return {"work_dir": work_dir, "repo_name": name, "github_url": None}


def redact_workspace_secrets(work_dir: Path) -> list[str]:
    """Redact API keys from every publishable text file, not only logs/.

    Returns the workspace-relative paths that were rewritten.
    """
    from git import Repo

    repo = Repo(work_dir)
    # Tracked-and-modified plus untracked files, honoring .gitignore.
    listed = repo.git.ls_files("--modified", "--others", "--exclude-standard", "-z")
    return sanitize_files(work_dir, sorted(set(filter(None, listed.split("\0")))))


def publish(
    github_manager: Optional[GitHubManager], work_dir: Path, message: str
) -> Dict[str, Any]:
    """Sanitize the workspace and, when GitHub-backed, commit and push it."""
    logs_dir = work_dir / "logs"
    if github_manager is None:
        sanitized = sanitize_logs_directory(logs_dir)
        return {"requested": False, "sanitized_logs": sanitized}

    publication: Dict[str, Any] = {"requested": True, "status": "pending"}
    try:
        redacted = redact_workspace_secrets(work_dir)
        if redacted:
            print(f"   ✓ Redacted API keys in {len(redacted)} file(s): {', '.join(redacted)}")
        publication["redacted_files"] = redacted
        # commit_and_push sanitizes logs/ again and skips files over 100MB.
        pushed = github_manager.commit_and_push(work_dir, message)
        publication["status"] = "succeeded" if pushed else "unchanged"
    except Exception as e:
        publication.update(status="failed", message=sanitize_text(str(e)))
        print(f"\n⚠️  Failed to push to GitHub: {publication['message']}")
        print("   Results are available locally")
    return publication


def run_baseline(
    idea: Dict[str, Any],
    provider: str,
    model: Optional[str] = None,
    *,
    timeout: Optional[int] = None,
    full_permissions: bool = True,
    use_github: bool = True,
    github_org: str = "",
    private: bool = False,
    no_hash: bool = False,
    resume_workspace: Optional[str] = None,
    resume_mode: str = "continue",
) -> Dict[str, Any]:
    from core.agent_runner import run_prebuilt_cli_agent

    if resume_mode not in RESUME_NOTES:
        raise ValueError(f"resume_mode must be one of {sorted(RESUME_NOTES)}, got {resume_mode!r}")

    title = idea["idea"]["title"]
    label = method_label(provider)
    print(f"🚀 Starting zero-shot baseline: {title}")
    print(f"   Provider: {provider}")
    print(f"   Model: {model or '(provider default)'}")

    github_manager = None
    if use_github and os.getenv("GITHUB_TOKEN"):
        github_manager = GitHubManager(org_name=github_org or None)
    elif use_github:
        print("⚠️  GitHub integration disabled: GITHUB_TOKEN not set")
    print(f"   GitHub: {'Enabled' if github_manager else 'Disabled'}")

    resume_number = 0
    if resume_workspace:
        # A fresh session writes the paper from the results an earlier session left.
        workspace = open_existing_workspace(resume_workspace)
        if not (workspace["work_dir"] / ".git").is_dir():
            github_manager = None
        print(f"   Resuming workspace: {workspace['repo_name']}")
    else:
        workspace = prepare_workspace(
            idea, provider, model, github_manager=github_manager, private=private, no_hash=no_hash
        )
    work_dir: Path = workspace["work_dir"]
    logs_dir = work_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    setup_gitignore(work_dir)

    prompt = build_prompt(idea, timeout)
    cmd = build_agent_command(provider, full_permissions=full_permissions, model=model)
    if resume_workspace:
        run_info = workspace["run_info"]
        resume_number = len(run_info.get("resumes", [])) + 1
        prompt = prompt.rstrip() + "\n" + RESUME_NOTES[resume_mode]
        stem = f"{METHOD}_{provider}_resume{resume_number}"
        (logs_dir / f"{METHOD}_resume{resume_number}_prompt.txt").write_text(prompt, encoding="utf-8")
        run_info.setdefault("resumes", []).append(
            {"model": model, "command": cmd, "mode": resume_mode, "started_at": utc_now()}
        )
        run_info["status"] = "running"
    else:
        stem = f"{METHOD}_{provider}"
        (logs_dir / f"{METHOD}_prompt.txt").write_text(prompt, encoding="utf-8")
        run_info = {
            "method": label,
            "provider": provider,
            "model": model,
            "command": cmd,
            "timeout_seconds": timeout,
            "workspace": workspace["repo_name"],
            "github_url": workspace["github_url"],
            "started_at": utc_now(),
            "status": "running",
        }
    log_file = logs_dir / f"{stem}.log"
    transcript_file = logs_dir / f"{stem}_transcript.jsonl"
    write_metadata(work_dir, idea, run_info)
    if github_manager is not None and not resume_workspace:
        github_manager.commit_and_push(work_dir, f"Initialize zero-shot baseline: {title}")

    print(f"📁 Working directory: {work_dir}")
    print(f"   Command: {cmd}")
    print(f"   Log file: {log_file}")
    print(f"   Transcript: {transcript_file}")
    print()
    print("=" * 80)
    print("ZERO-SHOT AGENT OUTPUT (streaming)")
    print("=" * 80)
    print()

    result: Dict[str, Any] = {"success": False, "return_code": None}
    try:
        result = run_prebuilt_cli_agent(
            command_argv=shlex.split(cmd),
            prompt=prompt,
            work_dir=work_dir,
            log_file=log_file,
            transcript_file=transcript_file,
            env=build_agent_environment(provider),
            timeout=timeout,
            provider=provider,
        )
    except Exception as e:
        result["error"] = sanitize_text(str(e))
        print(f"\n❌ Error during execution: {result['error']}")
    finally:
        paper_exists = (work_dir / PAPER_PDF).is_file()
        success = bool(result.get("success"))
        outcome = dict(
            completed_at=utc_now(),
            return_code=result.get("return_code"),
            elapsed_seconds=result.get("elapsed_time"),
            timed_out=bool(result.get("timed_out")),
        )
        if resume_number:
            run_info["resumes"][-1].update(outcome)
        else:
            run_info.update(outcome)
        run_info.update(
            status="completed" if success else "failed",
            paper_pdf=str(PAPER_PDF) if paper_exists else None,
        )
        if result.get("error"):
            run_info["error"] = result["error"]
        write_metadata(work_dir, idea, run_info)

        model_line = f"Model: {model}\n" if model else ""
        publication = publish(
            github_manager,
            work_dir,
            f"{'✅' if success else '⚠️'} Zero-shot baseline "
            f"{'resumed and ' if resume_number else ''}completed\n\n"
            f"Research: {title}\n"
            f"Provider: {provider}\n"
            f"{model_line}"
            f"Status: {'Success' if success else 'Completed with issues'}\n"
            f"Paper: {'yes' if paper_exists else 'missing'}\n\n"
            "Zero-shot baseline from NeuriCo\n"
            "https://github.com/ChicagoHAI/neurico\n",
        )

    print()
    print("=" * 80)
    if result.get("timed_out"):
        print(f"⏱️  Timed out after {timeout} seconds")
    print("✅ Baseline completed!" if success else "⚠️  Baseline did not complete successfully.")
    print(f"   Paper: {work_dir / PAPER_PDF if paper_exists else 'not found'}")
    print(f"Location: {work_dir}")
    if workspace["github_url"]:
        print(f"GitHub: {workspace['github_url']}")
    print("=" * 80)
    return {
        "work_dir": work_dir,
        "github_url": workspace["github_url"],
        "success": success,
        "paper_exists": paper_exists,
        "publication": publication,
    }


def main() -> None:
    try:
        from dotenv import load_dotenv

        for name in (".env.local", ".env"):
            if (PROJECT_ROOT / name).exists():
                load_dotenv(PROJECT_ROOT / name)
                break
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        description="Zero-shot baseline: one agent session takes an idea to a paper"
    )
    parser.add_argument("idea_file", type=Path, help="Path to idea YAML file")
    parser.add_argument("--provider", required=True, choices=PROVIDERS)
    parser.add_argument(
        "--model",
        default=None,
        help="Model for the provider CLI (e.g. claude-opus-5-5, gpt-5.6-sol)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help="Session timeout in seconds (default: 0 = no limit)",
    )
    parser.add_argument(
        "--full-permissions",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="codex: --yolo, claude: --dangerously-skip-permissions (default: True)",
    )
    parser.add_argument("--no-github", action="store_true", help="Run locally only")
    parser.add_argument("--github-org", default=os.getenv("GITHUB_ORG", ""))
    parser.add_argument("--private", action="store_true", help="Create a private repository")
    parser.add_argument("--no-hash", action="store_true", help="Skip the random hash in the name")
    parser.add_argument(
        "--resume-workspace",
        default=None,
        metavar="NAME",
        help="Finish an earlier baseline run: start a new session in that existing "
        "workspace (name under the workspace directory) instead of creating one",
    )
    parser.add_argument(
        "--resume-mode",
        choices=sorted(RESUME_NOTES),
        default="continue",
        help="With --resume-workspace: 'continue' an interrupted session, or 'writeup' only "
        "(the research is done and just the paper is missing) (default: continue)",
    )
    args = parser.parse_args()

    try:
        idea = load_idea(args.idea_file)
        result = run_baseline(
            idea,
            args.provider,
            args.model,
            timeout=args.timeout if args.timeout > 0 else None,
            full_permissions=args.full_permissions,
            use_github=not args.no_github,
            github_org=args.github_org,
            private=args.private,
            no_hash=args.no_hash,
            resume_workspace=args.resume_workspace,
            resume_mode=args.resume_mode,
        )
    except Exception as e:
        print(f"\n❌ Error: {sanitize_text(str(e))}", file=sys.stderr)
        sys.exit(1)
    if not result["success"]:
        sys.exit(2)
    # A clean agent exit without a paper is still an incomplete run.
    sys.exit(0 if result["paper_exists"] else 3)


if __name__ == "__main__":
    main()
