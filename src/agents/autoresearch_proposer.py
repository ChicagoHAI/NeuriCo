"""
AutoResearch Proposal Generator Agent.

This module launches a provider CLI agent to prepare one structured proposal
for the next AutoResearch attempt. The agent is a planner only: normal
AutoResearch writes proposal.md into attempt history, while HITL submits the
proposal directly to runtime and must not modify public research-workspace
files.
"""

from pathlib import Path
from typing import Any, Dict, Optional
import json
import shlex
import subprocess
import sys
import time

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.compute_backend import get_runtime_compute_backend
from core.security import sanitize_text
from core.agent_runner import run_prebuilt_cli_agent
from core.agent_cli import (
    CLI_COMMANDS,
    append_prompt_block,
    build_agent_command,
    build_agent_environment,
    provider_skill_root,
)


def _generate_compute_backend_section(idea_spec: Dict[str, Any], provider: str = "claude") -> str:
    """Return proposer-only backend constraints for explicit remote backends."""
    backend = get_runtime_compute_backend(idea_spec)
    skill_root = provider_skill_root(provider)
    dsi_skill_path = f"{skill_root}/dsi-slurm/SKILL.md"
    if backend == "dsi-slurm":
        return f"""
═══════════════════════════════════════════════════════════════════════════════
                              COMPUTE BACKEND: dsi-slurm
═══════════════════════════════════════════════════════════════════════════════

Runtime execution is pinned to DSI Slurm by `--compute-backend dsi-slurm`.
Any proposal that requires cluster training, evaluation, or batch execution
must tell comment mode to use `{skill_root}/dsi-slurm/` by reading
`{dsi_skill_path}` and following that skill's guidance.

The proposal must preserve this compute invariant: the local workspace is for
orchestration and reporting only. Comment mode must not run training,
evaluation, model selection, benchmarking, scored-output generation, smoke
tests, or result-changing validation locally. Local commands may inspect files,
edit code, prepare scripts, package inputs, and verify already-copied results
only. DSI Slurm is the only allowed compute surface for experiment workload.

The proposal should preserve the backend lifecycle contract: setup/discovery
checks first, use only the runtime-provided remote workspace, cheap smoke job
when possible, explicit resource requests, and copy-back of all required
results from the remote workspace to the same relative local paths. Comment
mode must also copy each terminal job's `dsi-slurm-artifacts/<JOB_ID>/` bundle
back to the local workspace. NeuriCo runtime creates/removes the remote
workspace and archives local `dsi-slurm-artifacts/`; comment mode must not
remove the remote workspace itself.

Do not propose Modal, local GPU fallback, or any other off-machine backend. If
missing DSI Slurm configuration or access would block the proposed change, make
that blocker explicit in the proposal rather than suggesting a backend switch.

"""
    if backend == "modal":
        return """
═══════════════════════════════════════════════════════════════════════════════
                              COMPUTE BUDGET
═══════════════════════════════════════════════════════════════════════════════

If your proposal would require GPU model training, fine-tuning, or LLM serving
that exceeds the local container, the workspace may have a compute-backend
skill available. Do not propose a backend by name. Instead, scope your proposal
so that:

1. If a compute backend is available, you state the proposal's compute needs
   (model size, GPU memory, expected wall time) and note that an off-machine
   backend may be required — the experiment_runner agent will discover and
   pick the appropriate skill.
2. If no compute backend is available, propose only changes that fit on the
   local container (smaller models, fewer steps, eval-only paths).

Treat compute-backend availability as a constraint to scope around, not as a
licence to propose unbounded training jobs.

═══════════════════════════════════════════════════════════════════════════════

"""
    return ""


def generate_autoresearch_proposal_prompt(
    idea: Dict[str, Any],
    work_dir: Path,
    parent_sha: str,
    attempt_dir: Path,
    templates_dir: Path,
    provider: str = "claude",
    attempt_history: Optional[list[Dict[str, Any]]] = None,
    hitl_idea_reporting: bool = False,
    hitl_submission: bool = False,
    hitl_autoresearch_whiteboard: bool = False,
    hitl_mode: str = "full",
) -> str:
    """
    Generate the AutoResearch proposer prompt from a curated public context.

    The proposer receives public experiment artifacts and a src/ file tree only.
    It does not receive source file contents or hidden scoring internals.
    """
    from jinja2 import Environment, FileSystemLoader

    work_dir = Path(work_dir)
    attempt_dir = Path(attempt_dir)
    templates_dir = Path(templates_dir)

    template_path = templates_dir / "agents" / "autoresearch_proposer.txt"
    if not template_path.exists():
        raise FileNotFoundError(f"AutoResearch proposer template not found: {template_path}")

    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("agents/autoresearch_proposer.txt")

    idea_spec = idea.get("idea", idea)
    context = collect_public_proposal_context(
        work_dir=work_dir,
        # HITL exposes the selected direction's relevant attempt history only
        # through view_current_frontier. Do not duplicate or leak runtime
        # attempt provenance in the prompt's public context.
        attempt_history=None if hitl_submission else attempt_history or [],
        include_attempt_history=not hitl_submission,
        hitl_autoresearch_whiteboard=hitl_autoresearch_whiteboard,
    )

    # Whiteboard tips get their own dedicated UNTRUSTED TIPS section in the
    # template, so drop them from the JSON public_context dump to avoid
    # rendering the same block twice in the proposer prompt.
    whiteboard_active_tips_md = context.pop(
        "whiteboard_active_tips_md",
        "_(whiteboard has no active tips)_\n",
    )

    return template.render(
        title=idea_spec.get("title", "Untitled Research"),
        domain=idea_spec.get("domain", ""),
        work_dir=str(work_dir),
        parent_sha=parent_sha,
        attempt_dir=str(attempt_dir),
        proposal_path=str(attempt_dir / "proposal.md"),
        hitl_idea_reporting=hitl_idea_reporting,
        hitl_submission=hitl_submission,
        pipeline_stage="experiment_runner",
        hitl_stage="proposal",
        allow_raised_ideas=False,
        hitl_mode=hitl_mode,
        public_context=context,
        whiteboard_active_tips_md=whiteboard_active_tips_md,
        compute_backend_section=_generate_compute_backend_section(idea_spec, provider=provider),
    )


def collect_public_proposal_context(
    work_dir: Path,
    attempt_history: Optional[list[Dict[str, Any]]] = None,
    *,
    include_attempt_history: bool = True,
    hitl_autoresearch_whiteboard: bool = False,
) -> Dict[str, Any]:
    """
    Build the public context for proposal generation.

    This intentionally includes only public scoring artifacts, public reports,
    a shallow results summary, current-node attempt history, and an src/ file
    tree. It never reads hidden scoring internals or source file contents.
    """
    work_dir = Path(work_dir)

    context: Dict[str, Any] = {
        "scoring_interface_md": _read_text_if_exists(work_dir / "scoring" / "interface.md"),
        "scoring_results_json": _read_json_or_text(work_dir / "scoring" / "results.json"),
        "report_md": _read_text_if_exists(work_dir / "REPORT.md"),
        "planning_md": _read_text_if_exists(work_dir / "planning.md"),
        "results_summary": _summarize_directory(work_dir / "results"),
        "results_metrics_json": _read_json_or_text(work_dir / "results" / "metrics.json"),
        "src_tree": _list_tree(work_dir / "src"),
        "whiteboard_active_tips_md": _render_whiteboard(
            work_dir,
            hitl_autoresearch=hitl_autoresearch_whiteboard,
        ),
    }
    if include_attempt_history:
        context["attempt_history"] = attempt_history or []
    return context


def _render_whiteboard(work_dir: Path, *, hitl_autoresearch: bool = False) -> str:
    """Render the AutoResearch cross-run whiteboard's active tips as markdown."""
    try:
        if hitl_autoresearch:
            from core.hitl_whiteboard import HitlAutoResearchWhiteboard as Whiteboard
        else:
            from core.whiteboard import Whiteboard
    except ImportError:  # pragma: no cover
        return ""
    try:
        wb = Whiteboard(work_dir).load()
        return wb.render_markdown()
    except Exception as e:  # pragma: no cover
        return f"_(whiteboard read error: {e})_\n"


def run_autoresearch_proposer(
    idea: Dict[str, Any],
    work_dir: Path,
    parent_sha: str,
    attempt_dir: Path,
    provider: str = "claude",
    templates_dir: Optional[Path] = None,
    timeout: Optional[int] = 900,
    full_permissions: bool = True,
    attempt_history: Optional[list[Dict[str, Any]]] = None,
    prompt_suffix: str = "",
    env_extra: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Launch the AutoResearch proposer agent.

    Returns launch metadata and success status. Normal AutoResearch also
    returns its materialized proposal path; HITL proposal content is submitted
    directly to runtime and has no worker-owned proposal artifact.
    """
    if provider not in CLI_COMMANDS:
        raise ValueError(
            f"Unsupported provider: {provider}. Choose from: {list(CLI_COMMANDS.keys())}"
        )

    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent.parent / "templates"

    work_dir = Path(work_dir)
    attempt_dir = Path(attempt_dir)
    attempt_dir.mkdir(parents=True, exist_ok=True)
    proposal_path = attempt_dir / "proposal.md"
    hitl_submission = bool(env_extra and env_extra.get("NEURICO_HITL_URL"))

    print("🧭 Starting AutoResearch Proposal Generator")
    print(f"   Provider: {provider}")
    print(f"   Work dir: {work_dir}")
    print(f"   Parent node: {parent_sha}")
    print(f"   Attempt dir: {attempt_dir}")
    timeout_label = "disabled" if timeout is None else f"{timeout}s ({timeout // 60} minutes)"
    print(f"   Timeout: {timeout_label}")
    print("=" * 80)

    prompt = generate_autoresearch_proposal_prompt(
        idea=idea,
        work_dir=work_dir,
        parent_sha=parent_sha,
        attempt_dir=attempt_dir,
        templates_dir=Path(templates_dir),
        provider=provider,
        attempt_history=attempt_history,
        hitl_idea_reporting=bool(env_extra and env_extra.get("NEURICO_HITL_URL")),
        hitl_submission=hitl_submission,
        hitl_autoresearch_whiteboard=bool(
            env_extra and env_extra.get("NEURICO_HITL_AUTORESEARCH_WHITEBOARD") == "1"
        ),
        hitl_mode=str((env_extra or {}).get("NEURICO_HITL_MODE", "full")),
    )
    prompt = append_prompt_block(prompt, prompt_suffix)

    prompt_file = attempt_dir / "proposer_prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    print(f"   Prompt saved to: {prompt_file}")
    print(f"   Prompt length: {len(prompt)} characters")

    cmd = build_agent_command(provider, full_permissions=full_permissions)

    transcript_file = attempt_dir / f"proposer_{provider}_transcript.jsonl"

    print(f"▶️  Launching {provider} CLI proposer...")
    print(f"   Command: {cmd}")
    if not hitl_submission:
        print(f"   Proposal: {proposal_path}")
    else:
        print("   Proposal: submitted directly to HITL runtime")
    print(f"   Transcript: {transcript_file}")
    print()

    env = build_agent_environment(provider, env_extra)

    start_time = time.time()
    return_code: Optional[int] = None
    error: Optional[str] = None
    launch: Dict[str, Any] = {
        "success": False,
        "timed_out": False,
        "background_processes_terminated": False,
    }

    try:
        if hitl_submission:
            # HITL proposal submission is a live runtime interaction. Use the
            # shared runner so the configured deadline applies even while the
            # provider streams progress indefinitely.
            launch = run_prebuilt_cli_agent(
                command_argv=shlex.split(cmd),
                prompt=prompt,
                work_dir=work_dir,
                log_file=attempt_dir / f"proposer_{provider}.log",
                transcript_file=transcript_file,
                env=env,
                timeout=timeout,
                provider=provider,
                defer_provider_failure_to_runtime=True,
            )
            return_code = launch["return_code"]
            if launch["timed_out"]:
                error = f"AutoResearch proposer timed out after {timeout}s"
                print(f"\n⏱️  {error}")
        else:
            with open(transcript_file, "w", encoding="utf-8") as transcript_f:
                process = subprocess.Popen(
                    shlex.split(cmd),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=env,
                    text=True,
                    encoding="utf-8",
                    bufsize=1,
                    cwd=str(attempt_dir),
                )

                process.stdin.write(prompt)
                process.stdin.close()

                for line in iter(process.stdout.readline, ""):
                    if line:
                        sanitized_line = sanitize_text(line)
                        print(sanitized_line, end="")
                        transcript_f.write(sanitized_line)

                return_code = process.wait(timeout=timeout)

    except subprocess.TimeoutExpired:
        process.kill()
        error = f"AutoResearch proposer timed out after {timeout}s"
        print(f"\n⏱️  {error}")
    except Exception as e:
        error = f"AutoResearch proposer error: {e}"
        print(f"\n❌ {error}")
        raise

    elapsed = time.time() - start_time
    proposal_exists = proposal_path.exists() and proposal_path.stat().st_size > 0
    success = (
        return_code == 0
        and (hitl_submission or proposal_exists)
        and error is None
        and not bool(launch.get("background_processes_terminated"))
    )

    if not hitl_submission and not proposal_exists and error is None:
        error = f"proposal.md was not created at {proposal_path}"

    if success:
        print(f"✅ AutoResearch proposal generated in {elapsed:.1f}s")
    else:
        print(
            f"⚠️  AutoResearch proposer finished with issues "
            f"(return_code={return_code}, error={error})"
        )

    result = {
        "success": success,
        "return_code": return_code,
        "proposal_path": str(proposal_path),
        "prompt_file": str(prompt_file),
        "transcript_file": str(transcript_file),
        "elapsed_time": elapsed,
        "error": error,
        "timed_out": bool(launch.get("timed_out")),
        "background_processes_terminated": bool(
            launch.get("background_processes_terminated")
        ),
    }
    if hitl_submission:
        result["provider_process_failed"] = bool(
            launch.get("provider_process_failed")
        )
    return result


def _read_text_if_exists(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _read_json_or_text(path: Path) -> Any:
    if not path.exists() or not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _summarize_directory(path: Path) -> list[Dict[str, Any]]:
    if not path.exists() or not path.is_dir():
        return []
    entries = []
    for child in sorted(path.rglob("*")):
        rel = child.relative_to(path).as_posix()
        if _is_hidden_context_path(rel):
            continue
        if child.is_file():
            entries.append(
                {
                    "path": rel,
                    "type": "file",
                    "bytes": child.stat().st_size,
                }
            )
        elif child.is_dir():
            entries.append(
                {
                    "path": rel + "/",
                    "type": "dir",
                }
            )
    return entries


def _list_tree(path: Path) -> list[str]:
    if not path.exists() or not path.is_dir():
        return []
    tree = []
    for child in sorted(path.rglob("*")):
        rel = child.relative_to(path).as_posix()
        if _is_hidden_context_path(rel):
            continue
        suffix = "/" if child.is_dir() else ""
        tree.append(f"src/{rel}{suffix}")
    return tree


def _is_hidden_context_path(rel_path: str) -> bool:
    normalized = rel_path.strip("/")
    hidden_roots = (".scoring_sealed", "data/.test")
    return any(normalized == root or normalized.startswith(f"{root}/") for root in hidden_roots)
