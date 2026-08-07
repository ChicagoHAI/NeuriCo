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
import shlex
import subprocess
import sys
import time

import yaml

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.security import sanitize_text
from core.agent_cli import CLI_COMMANDS, build_agent_command, build_agent_environment

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


def _trusted_idea_yaml(idea: Optional[Dict[str, Any]], work_dir: Path) -> str:
    """
    Serialize the TRUSTED orchestrator idea for the prompt.

    The idea passed here is the orchestrator's in-memory contract, held outside
    the worker-visible workspace, so the rule maker's targets derive from a
    source the optimizing agent cannot edit. The workspace .neurico/idea.yaml
    is worker-writable and is NOT read (a tampered copy there could steer
    weaker targets). Only when no trusted idea is provided at all (legacy
    callers) does it fall back to the workspace file, with a warning marker.
    """
    if isinstance(idea, dict) and idea:
        try:
            return yaml.safe_dump(idea, default_flow_style=False, sort_keys=False)
        except Exception as e:  # pragma: no cover - serialization is trivial
            return f"(trusted idea could not be serialized: {e})"
    idea_path = Path(work_dir) / ".neurico" / "idea.yaml"
    if not idea_path.exists():
        return "(idea.yaml not present in this workspace — design targets from manifest + literature only)"
    try:
        return ("(WARNING: no trusted idea supplied; read from worker-writable "
                "workspace copy)\n" + idea_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, OSError) as e:
        return f"(idea.yaml could not be read: {e})"


def read_prior_scoring_protocol(work_dir: Path) -> Optional[Dict[str, str]]:
    """
    Return the existing scoring protocol as {'eval','targets','interface'}, or
    None when no trusted prior exists (first generation / raw adopted repo).

    Read ONLY from the TRUSTED sealed copy under .scoring_sealed (relocated out
    of the agent-writable workspace during agent phases, i.e. the last
    validated version). The workspace copy is worker-writable, so it is NOT a
    fallback: a missing sealed copy means "no prior" and the rule maker
    regenerates fresh. Feeding an agent-edited eval.py/targets.json into the
    regeneration prompt could steer weaker targets (the eval-verifier gate is
    skipped for goal-only ideas), so this reads the trusted copy or nothing.
    """
    from core.scoring_seal import sealed_dir_for

    root = sealed_dir_for(work_dir)
    eval_path = root / "scoring" / "eval.py"
    targets_path = root / "scoring" / "targets.json"
    if eval_path.is_file() and targets_path.is_file():
        interface_path = root / "scoring" / "interface.md"
        return {
            "eval": eval_path.read_text(encoding="utf-8", errors="replace"),
            "targets": targets_path.read_text(encoding="utf-8", errors="replace"),
            "interface": (interface_path.read_text(encoding="utf-8",
                                                   errors="replace")
                          if interface_path.is_file() else ""),
        }
    return None


def _render_prior_protocol_block(prior: Optional[Dict[str, str]]) -> str:
    """Render the prior-protocol section for the prompt, or '' when none."""
    if not prior:
        return ""
    return (
        "\n\n=== PRIOR SCORING PROTOCOL (extend, do not discard) ===\n"
        "A scoring protocol already exists for this workspace. New evaluation "
        "materials have been declared, so regenerate a COHERENT protocol that "
        "extends this one: keep every existing metric unless a newly declared "
        "metric supersedes it, incorporate the new materials, and preserve the "
        "existing interface where it still applies. Do NOT read the contents "
        "of anything under data/.test.\n\n"
        "--- prior scoring/interface.md ---\n"
        f"{prior['interface']}\n"
        "--- prior scoring/targets.json ---\n"
        f"{prior['targets']}\n"
        "--- prior scoring/eval.py ---\n"
        f"{prior['eval']}\n"
        "=== END PRIOR SCORING PROTOCOL ===\n"
    )


def generate_bootstrap_rule_maker_prompt(
    curated_manifest: Dict[str, Any],
    work_dir: Path,
    templates_dir: Path,
    prior_protocol: Optional[Dict[str, str]] = None,
    idea: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build the bootstrap rule_maker prompt by substituting workspace details,
    the curated manifest, idea, and resource hint into the template.

    When prior_protocol is given (regeneration over an existing protocol after
    new evaluation materials were supplied), it is rendered into the
    {prior_scoring_protocol} placeholder so the rule maker extends it coherently
    rather than starting blind; otherwise that placeholder renders empty.
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
        "{idea_yaml}": _trusted_idea_yaml(idea, work_dir),
        "{resource_listing}": _summarize_resource_hints(work_dir),
        "{prior_scoring_protocol}": _render_prior_protocol_block(prior_protocol),
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
    prompt_suffix: str = "",
    prior_protocol: Optional[Dict[str, str]] = None,
    idea: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Launch the bootstrap rule_maker agent against a workspace.

    Args:
        prompt_suffix: Extra text appended to the generated prompt. Used by
            the eval-verifier retry loop to feed violations back into the
            rule_maker's second attempt.
        prior_protocol: An existing scoring protocol ({'eval','targets',
            'interface'}) to extend when new evaluation materials were
            supplied; None for a first, fresh generation.

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
        idea=idea,
        prior_protocol=prior_protocol,
    )
    if prompt_suffix:
        prompt += prompt_suffix

    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "bootstrap_rule_maker_prompt.txt").write_text(prompt, encoding="utf-8")

    cmd = build_agent_command(provider, full_permissions=full_permissions)

    print(f"📐 Launching Bootstrap Rule Maker ({provider})")
    print(f"   Command: {cmd}")
    print(f"   Workspace: {work_dir}")
    print(f"   Scoring dir: {scoring_dir}")
    print(f"   Prompt length: {len(prompt)} chars")
    print(f"   Timeout: {timeout}s")

    transcript_path: Optional[Path] = None
    if log_dir is not None:
        transcript_path = log_dir / f"bootstrap_rule_maker_{provider}_transcript.jsonl"

    env = build_agent_environment(provider)

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

    # Hard structural gate: a return_code=0 with all four files written can still
    # produce malformed scoring artifacts (eval.py SyntaxError, targets.json with
    # invalid directions). Gate success on the validator so downstream scorer
    # crashes turn into bootstrap-stage failures, not silent passes.
    validation: Dict[str, Any] = {}
    hard_checks_ok = False
    if all_outputs_present and return_code == 0 and error is None:
        validation = validate_bootstrap_outputs(work_dir)
        checks = validation.get("checks", {})
        hard_checks_ok = (
            checks.get("eval_parses_as_python") is True
            and checks.get("targets_parses_as_json") is True
            and checks.get("targets_has_properties") is True
            and checks.get("targets_all_directions_valid") is True
        )

    success = (
        return_code == 0
        and all_outputs_present
        and (error is None)
        and hard_checks_ok
    )

    if success:
        print(f"✅ Bootstrap rule_maker completed in {elapsed:.1f}s")
    else:
        missing = [k for k, present in outputs_exist.items() if not present]
        failed_hard_checks = [
            k for k in (
                "eval_parses_as_python",
                "targets_parses_as_json",
                "targets_has_properties",
                "targets_all_directions_valid",
            )
            if validation.get("checks", {}).get(k) is False
        ]
        print(
            f"⚠️  Bootstrap rule_maker finished with issues "
            f"(return_code={return_code}, missing={missing}, "
            f"failed_checks={failed_hard_checks}, error={error})"
        )

    return {
        "success": success,
        "return_code": return_code,
        "elapsed_time": elapsed,
        "outputs_exist": outputs_exist,
        "validation": validation,
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


def _target_map(payload: Any) -> Dict[str, Dict[str, Any]]:
    """{name: {'target': float, 'direction': str}} from a targets.json payload,
    keeping only entries with a numeric target."""
    out: Dict[str, Dict[str, Any]] = {}
    props = payload.get("properties") if isinstance(payload, dict) else None
    if not isinstance(props, dict):
        return out
    for name, spec in props.items():
        if not isinstance(spec, dict):
            continue
        try:
            target = float(spec.get("target"))
        except (TypeError, ValueError):
            continue
        out[str(name)] = {"target": target, "direction": spec.get("direction")}
    return out


def check_target_floor(work_dir: Path,
                       prior_protocol: Optional[Dict[str, str]] = None,
                       trusted_idea: Optional[Dict[str, Any]] = None) -> List[str]:
    """Reject a regenerated protocol that WEAKENS or DROPS a retained property.

    The "extend, keep existing metrics" instruction must never lower the bar on
    a property that already had a trusted target. Trusted anchors are the sealed
    prior targets.json (prior_protocol['targets']) and user-declared numeric
    targets in the trusted idea's evaluation.metrics. For a property present in
    both the anchor and the newly written targets.json: direction max requires
    new >= prior, direction min requires new <= prior. Non-numeric or
    unknown-direction cases are skipped (nothing to compare safely).

    Returns one message per weakened target; an empty list means no regression.
    """
    work_dir = Path(work_dir)
    try:
        new_payload = json.loads(
            (work_dir / "scoring" / "targets.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    new_targets = _target_map(new_payload)
    if not new_targets:
        return []

    anchors: Dict[str, Dict[str, Any]] = {}
    if prior_protocol and prior_protocol.get("targets"):
        try:
            anchors.update(_target_map(json.loads(prior_protocol["targets"])))
        except json.JSONDecodeError:
            pass
    # User-declared metric targets from the TRUSTED idea (name -> numeric target)
    if isinstance(trusted_idea, dict):
        inner = trusted_idea.get("idea", trusted_idea)
        metrics = (inner.get("evaluation") or {}).get("metrics") \
            if isinstance(inner, dict) else None
        for metric in metrics or []:
            if not isinstance(metric, dict) or not metric.get("name"):
                continue
            try:
                anchors.setdefault(str(metric["name"]),
                                   {"target": float(metric["target"]),
                                    "direction": None})
            except (TypeError, ValueError, KeyError):
                continue

    violations: List[str] = []
    for name, anchor in anchors.items():
        if name not in new_targets:
            # Dropping a retained property is a form of weakening: the "extend,
            # keep existing metrics" contract must not silently remove a target
            # that the prior protocol or the trusted idea already enforced.
            violations.append(
                f"property '{name}': present in the prior protocol / declared "
                f"metrics but dropped from the regenerated targets.json "
                f"(regeneration must retain every existing metric)")
            continue
        new = new_targets[name]
        direction = anchor.get("direction") or new.get("direction")
        prior_t, new_t = anchor["target"], new["target"]
        if direction == "max" and new_t < prior_t:
            violations.append(
                f"property '{name}': regenerated target {new_t} is weaker than "
                f"the prior target {prior_t} (direction max requires >=)")
        elif direction == "min" and new_t > prior_t:
            violations.append(
                f"property '{name}': regenerated target {new_t} is weaker than "
                f"the prior target {prior_t} (direction min requires <=)")
    return violations
