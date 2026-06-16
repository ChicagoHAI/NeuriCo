"""
Bootstrap Rule Maker Agent

Designs a scoring harness for an EXISTING research workspace whose
experiment_runner has already produced its outputs. The bootstrap rule_maker
reads the value-redacted curated manifest from the workspace_manifest feature
(plus the idea and resource_finder output), and writes the standard four-file
scoring protocol into the workspace's scoring/ directory:

    scoring/interface.md
    scoring/eval.py
    scoring/targets.json
    scoring/rule_maker_log.md

The workspace's actual artifact contents are NOT read by this agent. The
manifest is the only structural view it has; targets must derive from external
anchors (idea / literature / dataset conventions / task priors) per the
auditable-citation discipline.
"""

from __future__ import annotations

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

from core.security import sanitize_text


# CLI commands for different providers (mirrors rule_maker.py)
CLI_COMMANDS = {
    "claude": "claude -p",
    "codex": "codex exec",
    "gemini": "gemini",
}

# Verbose / structured-transcript output flags per provider
TRANSCRIPT_FLAGS = {
    "claude": "--verbose --output-format stream-json",
    "codex": "--json",
    "gemini": "--output-format stream-json",
}

# Files the bootstrap rule_maker is responsible for producing (relative to scoring/)
BOOTSTRAP_OUTPUT_FILES = {
    "interface": "interface.md",
    "eval_script": "eval.py",
    "targets": "targets.json",
    "rationale_log": "rule_maker_log.md",
}


_RESOURCE_HINT_FILES = (
    "literature_review.md",
    "resources.md",
    "papers/",
)


def _summarize_resource_hints(work_dir: Path) -> str:
    """
    Brief listing of pre-experiment context the agent may read on disk.

    Mirrors the resource_listing format of the normal rule_maker. The agent
    sees this AS A HINT only; the actual reading happens via its file tools
    inside the workspace.
    """
    work_dir = Path(work_dir)
    parts: list[str] = []
    for entry in _RESOURCE_HINT_FILES:
        path = work_dir / entry
        if path.exists():
            kind = "directory" if path.is_dir() else "file"
            parts.append(f"  - {entry} ({kind})")
    if not parts:
        return "  (no resource_finder output present in this workspace)"
    return "\n".join(parts)


def _read_idea_yaml(work_dir: Path) -> str:
    """
    Read the research idea from .neurico/idea.yaml in the workspace. Returns
    a short message if absent (some old workspaces may not have one).
    """
    idea_path = Path(work_dir) / ".neurico" / "idea.yaml"
    if not idea_path.exists():
        return "(idea.yaml not present in this workspace — design targets from manifest + literature only)"
    try:
        return idea_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        return f"(idea.yaml could not be read: {e})"


def generate_bootstrap_rule_maker_prompt(
    curated_manifest: Dict[str, Any],
    work_dir: Path,
    templates_dir: Path,
) -> str:
    """
    Build the bootstrap rule_maker prompt by substituting workspace details,
    the curated manifest, idea, and resource hint into the template.
    """
    work_dir = Path(work_dir)
    templates_dir = Path(templates_dir)
    template_path = templates_dir / "agents" / "rule_maker_bootstrap.txt"
    if not template_path.exists():
        raise FileNotFoundError(
            f"bootstrap rule_maker template not found at {template_path}"
        )
    template = template_path.read_text(encoding="utf-8")

    scoring_dir = work_dir / "scoring"

    substitutions = {
        "{workspace}": str(work_dir),
        "{scoring_dir}": str(scoring_dir),
        "{curated_manifest_json}": json.dumps(curated_manifest, indent=2),
        "{idea_yaml}": _read_idea_yaml(work_dir),
        "{resource_listing}": _summarize_resource_hints(work_dir),
    }

    prompt = template
    for placeholder, value in substitutions.items():
        prompt = prompt.replace(placeholder, value)
    return prompt


def run_bootstrap_rule_maker(
    curated_manifest: Dict[str, Any],
    work_dir: Path,
    provider: str = "claude",
    templates_dir: Optional[Path] = None,
    timeout: int = 1800,
    full_permissions: bool = True,
    log_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Launch the bootstrap rule_maker agent against a workspace.

    Returns a dict with success, return_code, elapsed_time, transcript_file,
    prompt_file, and a per-output-file existence summary.
    """
    if provider not in CLI_COMMANDS:
        raise ValueError(
            f"Unsupported provider: {provider}. Choose from: {list(CLI_COMMANDS.keys())}"
        )

    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent.parent / "templates"

    work_dir = Path(work_dir)
    scoring_dir = work_dir / "scoring"
    scoring_dir.mkdir(parents=True, exist_ok=True)

    prompt = generate_bootstrap_rule_maker_prompt(
        curated_manifest=curated_manifest,
        work_dir=work_dir,
        templates_dir=Path(templates_dir),
    )

    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "bootstrap_rule_maker_prompt.txt").write_text(prompt, encoding="utf-8")

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

    print(f"📐 Launching Bootstrap Rule Maker ({provider})")
    print(f"   Command: {cmd}")
    print(f"   Workspace: {work_dir}")
    print(f"   Scoring dir: {scoring_dir}")
    print(f"   Prompt length: {len(prompt)} chars")
    print(f"   Timeout: {timeout}s")

    transcript_path: Optional[Path] = None
    if log_dir is not None:
        transcript_path = log_dir / f"bootstrap_rule_maker_{provider}_transcript.jsonl"

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if provider == "gemini":
        env["GEMINI_CLI_IDE_DISABLE"] = "1"

    start_time = time.time()
    return_code: Optional[int] = None
    error: Optional[str] = None

    try:
        process = subprocess.Popen(
            shlex.split(cmd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=str(work_dir),
        )

        transcript_file = transcript_path.open("w", encoding="utf-8") if transcript_path else None
        try:
            process.stdin.write(prompt)
            process.stdin.close()

            for line in iter(process.stdout.readline, ""):
                if not line:
                    continue
                clean = sanitize_text(line)
                if transcript_file is not None:
                    transcript_file.write(clean)

            return_code = process.wait(timeout=timeout)
        finally:
            if transcript_file is not None:
                transcript_file.close()
    except subprocess.TimeoutExpired:
        process.kill()
        error = f"bootstrap rule_maker timed out after {timeout}s"
        print(f"⏱️  {error}")
    except Exception as e:
        error = f"bootstrap rule_maker error: {e}"
        print(f"❌ {error}")
        raise

    elapsed = time.time() - start_time

    outputs_exist = {
        key: (scoring_dir / fname).exists()
        for key, fname in BOOTSTRAP_OUTPUT_FILES.items()
    }
    all_outputs_present = all(outputs_exist.values())
    success = (return_code == 0) and all_outputs_present and (error is None)

    if success:
        print(f"✅ Bootstrap rule_maker completed in {elapsed:.1f}s")
    else:
        missing = [k for k, present in outputs_exist.items() if not present]
        print(
            f"⚠️  Bootstrap rule_maker finished with issues "
            f"(return_code={return_code}, missing={missing}, error={error})"
        )

    return {
        "success": success,
        "return_code": return_code,
        "elapsed_time": elapsed,
        "outputs_exist": outputs_exist,
        "transcript_file": str(transcript_path) if transcript_path else None,
        "prompt_file": str(log_dir / "bootstrap_rule_maker_prompt.txt") if log_dir else None,
        "error": error,
    }


def validate_bootstrap_outputs(work_dir: Path) -> Dict[str, Any]:
    """
    Mechanical post-run validation of the four scoring files. Mirrors the
    normal rule_maker's validate_rule_maker_outputs but does not require
    that targets references match any specific source.

    Returns a dict with per-file existence + parsability checks.
    """
    import ast
    work_dir = Path(work_dir)
    scoring_dir = work_dir / "scoring"
    result: Dict[str, Any] = {"workspace": work_dir.name, "checks": {}}

    interface = scoring_dir / BOOTSTRAP_OUTPUT_FILES["interface"]
    result["checks"]["interface_exists"] = interface.exists()
    if interface.exists():
        text = interface.read_text(encoding="utf-8", errors="replace")
        result["checks"]["interface_has_primary_outputs_section"] = (
            "## Primary outputs" in text or "## primary outputs" in text.lower()
        )
        result["checks"]["interface_has_producer_api_section"] = (
            "## Producer API" in text or "producer api" in text.lower()
        )

    eval_py = scoring_dir / BOOTSTRAP_OUTPUT_FILES["eval_script"]
    result["checks"]["eval_exists"] = eval_py.exists()
    if eval_py.exists():
        text = eval_py.read_text(encoding="utf-8", errors="replace")
        try:
            ast.parse(text)
            result["checks"]["eval_parses_as_python"] = True
        except SyntaxError as e:
            result["checks"]["eval_parses_as_python"] = False
            result["checks"]["eval_syntax_error"] = str(e)
        result["checks"]["eval_reads_targets_json"] = "targets.json" in text
        result["checks"]["eval_writes_results_json"] = "results.json" in text

    targets = scoring_dir / BOOTSTRAP_OUTPUT_FILES["targets"]
    result["checks"]["targets_exists"] = targets.exists()
    if targets.exists():
        try:
            payload = json.loads(targets.read_text(encoding="utf-8"))
            result["checks"]["targets_parses_as_json"] = True
            props = payload.get("properties")
            result["checks"]["targets_has_properties"] = isinstance(props, dict) and len(props) > 0
            if isinstance(props, dict):
                directions = {p.get("direction") for p in props.values() if isinstance(p, dict)}
                result["checks"]["targets_all_directions_valid"] = directions.issubset({"max", "min"})
                result["checks"]["targets_property_count"] = len(props)
        except json.JSONDecodeError as e:
            result["checks"]["targets_parses_as_json"] = False
            result["checks"]["targets_json_error"] = str(e)

    log = scoring_dir / BOOTSTRAP_OUTPUT_FILES["rationale_log"]
    result["checks"]["log_exists"] = log.exists()
    if log.exists():
        text = log.read_text(encoding="utf-8", errors="replace")
        result["checks"]["log_has_target_justifications"] = "Target justifications" in text
        result["checks"]["log_has_anchor_types"] = any(
            anchor in text for anchor in (
                "stated_success_criterion", "literature_baseline",
                "dataset_convention", "task_prior",
            )
        )

    result["all_files_present"] = all(
        result["checks"].get(f"{key}_exists", False)
        for key in ("interface", "eval", "targets", "log")
    )
    return result
