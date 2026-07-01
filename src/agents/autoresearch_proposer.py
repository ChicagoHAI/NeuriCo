"""
AutoResearch Proposal Generator Agent.

This module launches a provider CLI agent to write one structured proposal for
the next AutoResearch attempt. The agent is a planner only: it writes
proposal.md into the attempt history directory and must not modify the research
workspace.
"""

from pathlib import Path
from typing import Any, Dict, Optional
import json
import os
import shlex
import subprocess
import sys
import time

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.compute_backend import get_runtime_compute_backend
from core.security import sanitize_text


CLI_COMMANDS = {
    "claude": "claude -p",
    "codex": "codex exec",
    "gemini": "gemini",
}

TRANSCRIPT_FLAGS = {
    "claude": "--verbose --output-format stream-json",
    "codex": "--json",
    "gemini": "--output-format stream-json",
}


def _skill_root_for_provider(provider: str) -> str:
    return f".{provider}/skills"


def _generate_compute_backend_section(idea_spec: Dict[str, Any], provider: str = "claude") -> str:
    """Return proposer-only backend constraints for explicit remote backends."""
    backend = get_runtime_compute_backend(idea_spec)
    skill_root = _skill_root_for_provider(provider)
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
        attempt_history=attempt_history or [],
    )

    return template.render(
        title=idea_spec.get("title", "Untitled Research"),
        domain=idea_spec.get("domain", ""),
        work_dir=str(work_dir),
        parent_sha=parent_sha,
        attempt_dir=str(attempt_dir),
        proposal_path=str(attempt_dir / "proposal.md"),
        public_context=context,
        compute_backend_section=_generate_compute_backend_section(idea_spec, provider=provider),
    )


def collect_public_proposal_context(
    work_dir: Path,
    attempt_history: Optional[list[Dict[str, Any]]] = None,
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
        "attempt_history": attempt_history or [],
        "whiteboard_active_tips_md": _render_whiteboard(work_dir),
    }
    return context


def _render_whiteboard(work_dir: Path) -> str:
    """Render the AutoResearch cross-run whiteboard's active tips as markdown."""
    try:
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
    timeout: int = 900,
    full_permissions: bool = True,
    attempt_history: Optional[list[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Launch the AutoResearch proposer agent.

    Returns a dict with success, proposal_path, prompt_file, transcript_file,
    elapsed_time, and error when applicable.
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

    print(f"🧭 Starting AutoResearch Proposal Generator")
    print(f"   Provider: {provider}")
    print(f"   Work dir: {work_dir}")
    print(f"   Parent node: {parent_sha}")
    print(f"   Attempt dir: {attempt_dir}")
    print(f"   Timeout: {timeout}s ({timeout // 60} minutes)")
    print("=" * 80)

    prompt = generate_autoresearch_proposal_prompt(
        idea=idea,
        work_dir=work_dir,
        parent_sha=parent_sha,
        attempt_dir=attempt_dir,
        templates_dir=Path(templates_dir),
        provider=provider,
        attempt_history=attempt_history,
    )

    prompt_file = attempt_dir / "proposer_prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    print(f"   Prompt saved to: {prompt_file}")
    print(f"   Prompt length: {len(prompt)} characters")

    cmd = CLI_COMMANDS[provider]
    if full_permissions:
        if provider == "codex":
            cmd += " --yolo"
        elif provider == "claude":
            cmd += " --dangerously-skip-permissions"
        elif provider == "gemini":
            cmd += " --yolo --skip-trust"

    transcript_flag = TRANSCRIPT_FLAGS.get(provider, "")
    if transcript_flag:
        cmd += f" {transcript_flag}"

    transcript_file = attempt_dir / f"proposer_{provider}_transcript.jsonl"

    print(f"▶️  Launching {provider} CLI proposer...")
    print(f"   Command: {cmd}")
    print(f"   Proposal: {proposal_path}")
    print(f"   Transcript: {transcript_file}")
    print()

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if provider == "gemini":
        env["GEMINI_CLI_IDE_DISABLE"] = "1"

    start_time = time.time()
    return_code: Optional[int] = None
    error: Optional[str] = None

    try:
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
    success = return_code == 0 and proposal_exists and error is None

    if not proposal_exists and error is None:
        error = f"proposal.md was not created at {proposal_path}"

    if success:
        print(f"✅ AutoResearch proposal generated in {elapsed:.1f}s")
    else:
        print(
            f"⚠️  AutoResearch proposer finished with issues "
            f"(return_code={return_code}, error={error})"
        )

    return {
        "success": success,
        "return_code": return_code,
        "proposal_path": str(proposal_path),
        "prompt_file": str(prompt_file),
        "transcript_file": str(transcript_file),
        "elapsed_time": elapsed,
        "error": error,
    }


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
