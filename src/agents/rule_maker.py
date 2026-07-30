"""
Rule Maker Agent

Launches a CLI agent that, given the user's idea and the resource_finder's
outputs, writes a per-run evaluation harness into the workspace under
scoring/. The harness consists of:

- scoring/eval.py: a self-contained Python program that measures the
  experiment_runner's artifact and writes scoring/results.json.
- scoring/targets.json: numeric targets and the success rule.
- scoring/interface.md: visible to the experiment_runner -- describes what
  files the runner must produce and how they will be invoked.
- scoring/rule_maker_log.md: rationale for the chosen metrics.

This agent runs between resource_finder and experiment_runner. Its outputs
should be sealed (read-only) before experiment_runner starts so the runner
cannot influence what it is being judged on.
"""

from pathlib import Path
from typing import Optional, Dict, Any
import shlex
import sys
import time
import json
import ast

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agent_runner import next_attempt_number, run_prebuilt_cli_agent
from core.agent_cli import CLI_COMMANDS, build_agent_command, build_agent_environment
from core.scorer import RESULTS_FILE_NAME

# Files the rule_maker is responsible for producing (relative to scoring/)
RULE_MAKER_OUTPUT_FILES = {
    "eval_script": "eval.py",
    "targets": "targets.json",
    "interface": "interface.md",
    "rationale_log": "rule_maker_log.md",
}


_DISALLOWED_EVALUATOR_CLI_MODULES = {"argparse", "click", "docopt", "typer"}
_EVALUATOR_RESULTS_PATH = f"scoring/{RESULTS_FILE_NAME}"
_EVALUATOR_OWNED_INTERFACE_PREFIXES = ("scoring/", "data/.test/")


def _assigned_expressions(tree: ast.AST) -> dict[str, ast.AST]:
    assignments: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                assignments[node.target.id] = node.value
    return assignments


def _path_string_parts(
    node: ast.AST,
    assignments: dict[str, ast.AST],
    *,
    resolving: Optional[set[str]] = None,
) -> list[str]:
    resolving = set(resolving or ())
    if isinstance(node, ast.Name) and node.id in assignments and node.id not in resolving:
        resolving.add(node.id)
        return _path_string_parts(
            assignments[node.id],
            assignments,
            resolving=resolving,
        )
    parts: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            value = child.value.strip().replace("\\", "/")
            if value:
                parts.append(value)
    return parts


def _is_canonical_results_path(
    node: ast.AST,
    assignments: dict[str, ast.AST],
) -> bool:
    parts = _path_string_parts(node, assignments)
    if any(part.rstrip("/").endswith(_EVALUATOR_RESULTS_PATH) for part in parts):
        return True
    if "scoring" in parts and "results.json" in parts:
        return True
    normalized = "/".join(part.strip("/") for part in parts)
    return normalized.endswith(_EVALUATOR_RESULTS_PATH)


def _write_path_expressions(tree: ast.AST) -> list[ast.AST]:
    paths: list[ast.AST] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Attribute) and function.attr in {
            "write_text",
            "write_bytes",
        }:
            paths.append(function.value)
            continue
        if isinstance(function, ast.Attribute) and function.attr == "open":
            mode = node.args[0] if node.args else None
            for keyword in node.keywords:
                if keyword.arg == "mode":
                    mode = keyword.value
            if (
                isinstance(mode, ast.Constant)
                and isinstance(mode.value, str)
                and any(flag in mode.value for flag in "wax+")
            ):
                paths.append(function.value)
            continue
        if isinstance(function, ast.Name) and function.id == "open" and node.args:
            mode = node.args[1] if len(node.args) > 1 else None
            for keyword in node.keywords:
                if keyword.arg == "mode":
                    mode = keyword.value
            if (
                isinstance(mode, ast.Constant)
                and isinstance(mode.value, str)
                and any(flag in mode.value for flag in "wax+")
            ):
                paths.append(node.args[0])
    return paths


def _validate_evaluator_abi(tree: ast.AST) -> list[str]:
    """Validate the fixed ``python scoring/eval.py`` scorer ABI."""
    issues: list[str] = []
    sys_aliases = {"sys"}
    argv_aliases: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                module = imported.name.split(".", 1)[0]
                if module in _DISALLOWED_EVALUATOR_CLI_MODULES:
                    issues.append(
                        "scoring/eval.py must use the zero-argument scorer ABI; "
                        f"command-line parser module `{module}` is not allowed."
                    )
                if imported.name == "sys":
                    sys_aliases.add(imported.asname or imported.name)
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".", 1)[0]
            if module in _DISALLOWED_EVALUATOR_CLI_MODULES:
                issues.append(
                    "scoring/eval.py must use the zero-argument scorer ABI; "
                    f"command-line parser module `{module}` is not allowed."
                )
            if node.module == "sys":
                for imported in node.names:
                    if imported.name == "argv":
                        argv_aliases.add(imported.asname or imported.name)

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "argv"
            and isinstance(node.value, ast.Name)
            and node.value.id in sys_aliases
        ) or (isinstance(node, ast.Name) and node.id in argv_aliases):
            issues.append(
                "scoring/eval.py must use the zero-argument scorer ABI; "
                "reading command-line arguments is not allowed."
            )
            break

    assignments = _assigned_expressions(tree)
    if not any(
        _is_canonical_results_path(path, assignments)
        for path in _write_path_expressions(tree)
    ):
        issues.append(
            "scoring/eval.py must write its authoritative structured result to "
            f"`{_EVALUATOR_RESULTS_PATH}`."
        )

    return list(dict.fromkeys(issues))


def generate_rule_maker_prompt(
    idea: Dict[str, Any],
    work_dir: Path,
    templates_dir: Path,
    domain: Optional[str] = None,
    *,
    hitl_phase: Optional[str] = None,
) -> str:
    """
    Build the rule_maker agent's prompt.

    Composition (mirrors the researcher prompt pattern):

      1. General body: templates/base/rule_maker.txt
         -- the universal rule_maker job description, applied to every run.
      2. Domain supplement (optional): templates/domains/<domain>/rule_maker.txt
         -- domain-specific guidelines (what metrics matter in this domain,
            calibration conventions, common reward-hacking traps, etc.).

    Placeholders substituted in the general body:
      {idea_yaml}        -- the idea spec (JSON-serialized for readability)
      {workspace}        -- absolute path to the run's workspace
      {scoring_dir}      -- absolute path to scoring/
      {output_files}     -- list of files the agent must produce
      {resource_listing} -- short summary of resource_finder outputs

    Args:
        idea: Full idea specification.
        work_dir: Path to the run's workspace.
        templates_dir: Path to the project's templates/ directory.
        domain: Domain name (e.g. 'machine_learning'). If None, extracted
            from idea['idea']['domain'] or idea['domain'], defaulting to
            'machine_learning' (matches researcher prompt's default).

    The prompt BODIES are user-owned and live in the template files. This
    function only handles loading + substitution + concatenation.
    """
    work_dir = Path(work_dir)
    templates_dir = Path(templates_dir)

    if hitl_phase not in {None, "plan", "execution", "review"}:
        raise ValueError(f"Unsupported HITL rule-maker phase: {hitl_phase}")

    # Planning/review receive research context only. The evaluator-authoring
    # procedure and domain supplement are execution-only in HITL mode.
    base_path = (
        templates_dir / "hitl" / "rule_maker_context.txt"
        if hitl_phase in {"plan", "review"}
        else templates_dir / "agents" / "rule_maker.txt"
    )
    if not base_path.exists():
        raise FileNotFoundError(
            f"rule_maker base template not found at {base_path}. "
            "Create templates/agents/rule_maker.txt before running."
        )
    base_template = base_path.read_text(encoding="utf-8")

    scoring_dir = work_dir / "scoring"
    output_files = "\n".join(f"  - scoring/{name}" for name in RULE_MAKER_OUTPUT_FILES.values())
    resource_listing = _summarize_resource_outputs(work_dir)

    try:
        idea_repr = json.dumps(idea, indent=2, default=str)
    except (TypeError, ValueError):
        idea_repr = repr(idea)

    substitutions = {
        "{idea_yaml}": idea_repr,
        "{workspace}": str(work_dir),
        "{scoring_dir}": str(scoring_dir),
        "{output_files}": output_files,
        "{resource_listing}": resource_listing,
    }

    prompt = base_template
    for placeholder, value in substitutions.items():
        prompt = prompt.replace(placeholder, value)

    if hitl_phase in {"plan", "review"}:
        prompt = prompt.replace("{hitl_phase}", hitl_phase)
    else:
        # Append per-domain supplement (if any) with a banner.
        resolved_domain = _resolve_domain(idea, domain)
        supplement = _load_domain_supplement(templates_dir, resolved_domain)
        if supplement:
            banner = "=" * 80
            domain_label = resolved_domain.upper().replace("_", " ")
            prompt = (
                f"{prompt}\n\n"
                f"{banner}\n"
                f"           RULE MAKER DOMAIN GUIDELINES: {domain_label}\n"
                f"{banner}\n\n"
                f"{supplement}\n"
            )

    return prompt


def _resolve_domain(idea: Dict[str, Any], override: Optional[str]) -> str:
    """
    Pick the domain string used to locate the domain supplement.

    Order of precedence:
      1. Explicit `override` argument.
      2. idea['idea']['domain']  (nested spec, as elsewhere in the pipeline).
      3. idea['domain']          (flat spec).
      4. Fallback: 'machine_learning' (matches researcher default).
    """
    if override:
        return override
    nested = idea.get("idea", {}) if isinstance(idea, dict) else {}
    if isinstance(nested, dict) and nested.get("domain"):
        return nested["domain"]
    if isinstance(idea, dict) and idea.get("domain"):
        return idea["domain"]
    return "machine_learning"


def _load_domain_supplement(templates_dir: Path, domain: str) -> str:
    """
    Load templates/domains/<domain>/rule_maker.txt if present.

    Returns empty string when the supplement is missing -- the general
    body alone is then used. (No silent fallback to a different domain;
    that decision is left to the caller / pipeline.)
    """
    supplement_path = templates_dir / "domains" / domain / "rule_maker.txt"
    if not supplement_path.exists():
        return ""
    return supplement_path.read_text(encoding="utf-8")


def _summarize_resource_outputs(work_dir: Path) -> str:
    """
    Build a short, prompt-safe listing of what resource_finder produced.

    The rule_maker needs to know which files / folders exist so it can
    reference them in eval.py, but it should not have raw resource
    contents dumped into its prompt.
    """
    work_dir = Path(work_dir)
    candidates = [
        ("literature_review.md", work_dir / "literature_review.md"),
        ("resources.md", work_dir / "resources.md"),
        ("papers/", work_dir / "papers"),
        ("datasets/", work_dir / "datasets"),
        ("code/", work_dir / "code"),
    ]
    lines = []
    for label, path in candidates:
        if not path.exists():
            lines.append(f"  - {label}: (missing)")
            continue
        if path.is_dir():
            entries = sorted(p.name for p in path.iterdir())
            preview = ", ".join(entries[:8])
            extra = "" if len(entries) <= 8 else f", +{len(entries) - 8} more"
            lines.append(f"  - {label}: {len(entries)} entries [{preview}{extra}]")
        else:
            size = path.stat().st_size
            lines.append(f"  - {label}: {size} bytes")
    return "\n".join(lines) if lines else "  (no resource_finder outputs found)"


def run_rule_maker(
    idea: Dict[str, Any],
    work_dir: Path,
    provider: str = "claude",
    templates_dir: Optional[Path] = None,
    timeout: int = 1800,  # 30 min
    full_permissions: bool = True,
    prompt_suffix: str = "",
    completion_mode: str = "outputs",
    log_prefix: str = "rule_maker",
    include_hitl_outputs: bool = False,
    env_extra: Optional[Dict[str, str]] = None,
    prompt_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Launch the rule_maker CLI agent.

    Args:
        prompt_suffix: Extra text appended to the generated prompt. Used by
            the eval-verifier retry loop to feed violations back into the
            rule_maker's second attempt.

    Returns:
        Dict with: success, outputs (paths of generated files), issues,
        log_file, transcript_file, elapsed_time.
    """
    if provider not in CLI_COMMANDS:
        raise ValueError(
            f"Unsupported provider: {provider}. " f"Choose from: {list(CLI_COMMANDS.keys())}"
        )

    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent.parent / "templates"

    work_dir = Path(work_dir)
    scoring_dir = work_dir / "scoring"
    scoring_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = work_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    print("📐 Starting Rule Maker Agent")
    print(f"   Provider: {provider}")
    print(f"   Work dir: {work_dir}")
    print(f"   Timeout: {timeout}s ({timeout // 60} minutes)")
    print("=" * 80)

    # Per-attempt artifact names: the orchestrator re-runs the rule maker
    # once after a verifier rejection, and fixed names would overwrite the
    # first attempt's audit trail (prompt, log, and transcript).
    attempt = next_attempt_number(
        logs_dir, lambda n: f"{log_prefix}_{provider}_attempt{n}.log")

    # Generate prompt and persist it for debugging
    if prompt_override is not None:
        prompt = prompt_override
    else:
        prompt = generate_rule_maker_prompt(idea, work_dir, templates_dir)
        if prompt_suffix:
            prompt += prompt_suffix
    prompt_file = logs_dir / f"{log_prefix}_prompt_attempt{attempt}.txt"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(prompt, encoding="utf-8")
    print(f"   Prompt saved to: {prompt_file}")
    print(f"   Prompt length: {len(prompt)} characters")

    # Build CLI command
    cmd = build_agent_command(provider, full_permissions=full_permissions)

    log_file = logs_dir / f"{log_prefix}_{provider}_attempt{attempt}.log"
    transcript_file = logs_dir / f"{log_prefix}_{provider}_attempt{attempt}_transcript.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    transcript_file.parent.mkdir(parents=True, exist_ok=True)

    print(f"▶️  Launching {provider} CLI agent...")
    print(f"   Command: {cmd}")
    print(f"   Log file: {log_file}")
    print()
    print("=" * 80)
    print("RULE MAKER OUTPUT (streaming)")
    print("=" * 80)

    env = build_agent_environment(provider, env_extra)

    start_time = time.time()
    return_code: Optional[int] = None

    try:
        # The shared deadline-aware runner enforces the timeout on wall
        # clock. Reading stdout to EOF inline would block for as long as the
        # agent keeps the pipe open, so wait(timeout=...) would never be
        # reached: HITL workers legitimately stay active while emitting
        # output, and a wedged ordinary agent must not hang the pipeline.
        launch = run_prebuilt_cli_agent(
            command_argv=shlex.split(cmd),
            prompt=prompt,
            work_dir=work_dir,
            log_file=log_file,
            transcript_file=transcript_file,
            env=env,
            timeout=timeout,
        )
        return_code = launch["return_code"]
        if launch["timed_out"]:
            print(f"\n⏱️  Rule maker timed out after {timeout} seconds")

        print()
        print("=" * 80)
        elapsed = time.time() - start_time
        print(f"⏱️  Rule maker completed in {elapsed:.1f}s " f"({elapsed / 60:.1f} minutes)")

        if return_code == 0:
            print("✅ Agent process exited cleanly.")
        else:
            print(f"⚠️  Agent exited with return code: {return_code}")

    except Exception as e:
        print(f"\n❌ Error during rule_maker execution: {e}")
        raise

    # Validate outputs
    print()
    print("📦 Validating rule_maker outputs...")
    validation = validate_rule_maker_outputs(work_dir)
    validation_success = validation["valid"]
    if validation_success:
        print("✅ All required rule_maker outputs present and parseable.")
    else:
        print("⚠️  Rule maker outputs incomplete or invalid:")
        for issue in validation["issues"]:
            print(f"     - {issue}")

    if completion_mode == "hitl_runtime":
        success = bool(launch.get("success"))
        print("ℹ️  HITL runtime completion mode; orchestrator will review finish state.")
    elif completion_mode == "outputs":
        success = validation_success
    else:
        raise ValueError("completion_mode must be 'outputs' or 'hitl_runtime' for rule_maker")

    outputs = dict(validation["found"])
    if include_hitl_outputs:
        plan_path = work_dir / "plans" / "rule_maker_plan.md"
        if plan_path.exists():
            outputs["hitl_plan"] = str(plan_path)

    return {
        "success": success,
        "outputs": outputs,
        "issues": validation["issues"],
        "log_file": str(log_file),
        "transcript_file": str(transcript_file),
        "elapsed_time": time.time() - start_time,
        "background_processes_terminated": bool(launch.get("background_processes_terminated"))
        if completion_mode == "hitl_runtime"
        else False,
    }


def validate_rule_maker_outputs(work_dir: Path) -> Dict[str, Any]:
    """
    Verify the rule_maker produced the expected files in a usable form.

    Checks:
      - scoring/eval.py exists and parses as valid Python
      - scoring/targets.json exists and parses as valid JSON
      - scoring/interface.md exists and is non-empty
      - scoring/rule_maker_log.md exists (informational; not required)

    Returns:
        {'valid': bool, 'found': {name: path}, 'issues': [str, ...]}
    """
    work_dir = Path(work_dir)
    scoring_dir = work_dir / "scoring"
    found: Dict[str, str] = {}
    issues = []

    eval_path = scoring_dir / RULE_MAKER_OUTPUT_FILES["eval_script"]
    if not eval_path.exists():
        issues.append(f"missing: {eval_path}")
    else:
        try:
            evaluator_tree = ast.parse(eval_path.read_text(encoding="utf-8"))
            evaluator_issues = _validate_evaluator_abi(evaluator_tree)
            if evaluator_issues:
                issues.extend(evaluator_issues)
            else:
                found["eval_script"] = str(eval_path)
        except SyntaxError as e:
            issues.append(f"eval.py has syntax error: {e}")

    targets_path = scoring_dir / RULE_MAKER_OUTPUT_FILES["targets"]
    if not targets_path.exists():
        issues.append(f"missing: {targets_path}")
    else:
        try:
            targets = json.loads(targets_path.read_text(encoding="utf-8"))
            declared_result = (
                str(targets.get("result_file", "")).strip().replace("\\", "/")
                if isinstance(targets, dict)
                else ""
            )
            if declared_result and declared_result != _EVALUATOR_RESULTS_PATH:
                issues.append(
                    "scoring/targets.json declares a conflicting result_file; "
                    f"the evaluator ABI requires `{_EVALUATOR_RESULTS_PATH}`."
                )
            else:
                found["targets"] = str(targets_path)
        except json.JSONDecodeError as e:
            issues.append(f"targets.json is not valid JSON: {e}")

    interface_path = scoring_dir / RULE_MAKER_OUTPUT_FILES["interface"]
    if not interface_path.exists():
        issues.append(f"missing: {interface_path}")
    elif interface_path.stat().st_size == 0:
        issues.append(f"empty: {interface_path}")
    else:
        # The experiment runner cannot repair this evaluator-owned contract.
        # Validate the exact grammar while the rule maker still owns it.
        try:
            from core.hitl import HitlValidationError, parse_required_artifacts

            artifacts = parse_required_artifacts(interface_path)
            evaluator_owned = [
                artifact.path
                for artifact in artifacts
                if artifact.path.startswith(_EVALUATOR_OWNED_INTERFACE_PREFIXES)
            ]
            if evaluator_owned:
                issues.append(
                    "scoring/interface.md assigns evaluator-owned paths to the "
                    "experiment runner: "
                    + ", ".join(evaluator_owned)
                )
            else:
                found["interface"] = str(interface_path)
        except (OSError, HitlValidationError) as exc:
            issues.append(f"invalid artifact contract in {interface_path}: {exc}")

    rationale_path = scoring_dir / RULE_MAKER_OUTPUT_FILES["rationale_log"]
    if rationale_path.exists():
        found["rationale_log"] = str(rationale_path)

    return {
        "valid": len(issues) == 0,
        "found": found,
        "issues": issues,
    }


def load_interface_for_runner(work_dir: Path) -> str:
    """
    Read scoring/interface.md to inject into the experiment_runner's prompt.

    This is the ONE channel by which rule_maker's output reaches the runner.
    Everything else under scoring/ (eval.py, targets.json) is hidden from
    the runner.

    Raises:
        FileNotFoundError: If interface.md is missing -- the pipeline should
        not proceed to experiment_runner without it.
    """
    interface_path = Path(work_dir) / "scoring" / RULE_MAKER_OUTPUT_FILES["interface"]
    if not interface_path.exists():
        raise FileNotFoundError(
            f"scoring/interface.md not found at {interface_path}. "
            "rule_maker must run successfully before experiment_runner."
        )
    return interface_path.read_text(encoding="utf-8")
