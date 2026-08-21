"""
Eval Verifier Agent

Launches a CLI agent that reviews the rule_maker's scoring/ outputs against
the user's declared evaluation contract (idea.evaluation and mandated
functions in idea.local_resources) BEFORE the scoring contract is sealed.

The verifier answers three questions:

1. Routing: does scoring/eval.py actually compute the mandated measurements
   by calling each required_for_evaluation function, rather than
   reimplementing or bypassing it?
2. Transcription: does scoring/targets.json carry every user-declared metric
   under its exact name with a faithful target (source: user)?
3. Format: does the artifact protocol match the user's declared
   results_format, when one was given?

It writes a verdict to scoring/verification.json. On failure the pipeline
re-runs the rule_maker once with the violations appended to its prompt.

This agent only runs when the idea actually declares a contract; ideas
without evaluation.metrics or mandated functions skip it entirely.
"""

from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import shlex
import shutil
import sys
import time
import json

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agent_cli import CLI_COMMANDS, build_agent_command, build_agent_environment
from core.agent_runner import next_attempt_number, run_prebuilt_cli_agent

VERDICT_FILE_NAME = "verification.json"


# The verdict contract, stated once: every check the eval_verifier template
# mandates, mapped to the predicate that decides whether the submitted
# contract makes it applicable. templates/agents/eval_verifier.txt states the
# same rules in prose ("only when the contract lists ..."); keep the two in
# sync. Whether the verifier runs at all (has_user_eval_contract) and which
# checks a verdict may wave off as not_applicable (interpret_verdict) are
# both derived from this table.
VERDICT_CHECKS = {
    'routing': lambda contract: bool(contract['mandated_functions']),
    'transcription': lambda contract: bool(contract['evaluation'].get('metrics')),
    'format': lambda contract: bool(contract['evaluation'].get('results_format')),
}
VERDICT_CHECK_VALUES = ('pass', 'fail', 'not_applicable')


def has_user_eval_contract(idea: Dict[str, Any]) -> bool:
    """
    Return True when the idea declares something the verifier must check,
    i.e. when at least one mandated verdict check is applicable.
    """
    contract = extract_eval_contract(idea)
    return any(applicable(contract) for applicable in VERDICT_CHECKS.values())


def extract_eval_contract(idea: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pull the contract-relevant slices of the idea for the verifier's prompt
    and for verdict interpretation: the structured evaluation spec plus any
    mandated evaluation functions. Malformed (non-mapping) slices normalize
    to empty so the VERDICT_CHECKS predicates never trip on bad input.
    """
    idea_spec = idea.get('idea', idea) if isinstance(idea, dict) else {}
    if not isinstance(idea_spec, dict):
        idea_spec = {}
    evaluation = idea_spec.get('evaluation')
    if not isinstance(evaluation, dict):
        evaluation = {}
    resources = idea_spec.get('local_resources')
    if not isinstance(resources, dict):
        resources = {}
    mandated = [
        func for func in (resources.get('functions') or [])
        if isinstance(func, dict) and func.get('required_for_evaluation')
    ]
    return {
        'evaluation': evaluation,
        'mandated_functions': mandated,
    }


def generate_eval_verifier_prompt(
    idea: Dict[str, Any],
    work_dir: Path,
    templates_dir: Path,
) -> str:
    """
    Build the eval_verifier agent's prompt.

    Placeholders substituted in the template body:
      {eval_contract} -- the user's declarations (JSON-serialized)
      {workspace}     -- absolute path to the run's workspace
      {scoring_dir}   -- absolute path to scoring/
      {verdict_file}  -- absolute path to scoring/verification.json

    The prompt BODY is user-owned and lives in the template file. This
    function only handles loading + substitution.
    """
    work_dir = Path(work_dir)
    templates_dir = Path(templates_dir)

    base_path = templates_dir / "agents" / "eval_verifier.txt"
    if not base_path.exists():
        raise FileNotFoundError(
            f"eval_verifier template not found at {base_path}. "
            "Create templates/agents/eval_verifier.txt before running."
        )
    base_template = base_path.read_text(encoding='utf-8')

    scoring_dir = work_dir / "scoring"
    contract = extract_eval_contract(idea)
    try:
        contract_repr = json.dumps(contract, indent=2, default=str)
    except (TypeError, ValueError):
        contract_repr = repr(contract)

    substitutions = {
        '{eval_contract}': contract_repr,
        '{workspace}': str(work_dir),
        '{scoring_dir}': str(scoring_dir),
        '{verdict_file}': str(scoring_dir / VERDICT_FILE_NAME),
    }

    prompt = base_template
    for placeholder, value in substitutions.items():
        prompt = prompt.replace(placeholder, value)

    return prompt


def run_eval_verifier(
    idea: Dict[str, Any],
    work_dir: Path,
    provider: str = "claude",
    templates_dir: Optional[Path] = None,
    timeout: int = 600,  # 10 min; this is a read-and-judge task
    full_permissions: bool = True,
) -> Dict[str, Any]:
    """
    Launch the eval_verifier CLI agent.

    Returns:
        Dict with: success (agent ran and produced a parseable verdict),
        passed (the verdict itself), violations, log_file, transcript_file,
        elapsed_time.
    """
    if provider not in CLI_COMMANDS:
        raise ValueError(
            f"Unsupported provider: {provider}. "
            f"Choose from: {list(CLI_COMMANDS.keys())}"
        )

    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent.parent / "templates"

    work_dir = Path(work_dir)
    scoring_dir = work_dir / "scoring"
    logs_dir = work_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Per-attempt artifact names: the orchestrator re-runs the verifier once
    # after a rule-maker retry, and fixed names would overwrite the first
    # attempt's audit trail (log, transcript, prompt, and failed verdict).
    attempt = next_attempt_number(
        logs_dir, lambda n: f"eval_verifier_{provider}_attempt{n}.log")
    log_file = logs_dir / f"eval_verifier_{provider}_attempt{attempt}.log"
    transcript_file = logs_dir / f"eval_verifier_{provider}_attempt{attempt}_transcript.jsonl"

    # Remove any stale verdict so a crashed agent cannot pass on old results,
    # archiving it first so a rejected earlier attempt stays auditable.
    verdict_path = scoring_dir / VERDICT_FILE_NAME
    if verdict_path.exists():
        archive = logs_dir / (f"eval_verifier_{provider}_verification_"
                              f"before_attempt{attempt}.json")
        try:
            shutil.move(str(verdict_path), str(archive))
        except OSError:
            verdict_path.unlink(missing_ok=True)

    print(f"🔎 Starting Eval Verifier Agent")
    print(f"   Provider: {provider}")
    print(f"   Work dir: {work_dir}")
    print(f"   Timeout: {timeout}s ({timeout // 60} minutes)")
    print("=" * 80)

    # Generate prompt and persist it for debugging
    prompt = generate_eval_verifier_prompt(idea, work_dir, templates_dir)
    prompt_file = logs_dir / f"eval_verifier_prompt_attempt{attempt}.txt"
    prompt_file.write_text(prompt, encoding='utf-8')
    print(f"   Prompt saved to: {prompt_file}")
    print(f"   Prompt length: {len(prompt)} characters")

    cmd = build_agent_command(provider, full_permissions=full_permissions)

    print(f"▶️  Launching {provider} CLI agent...")
    print(f"   Command: {cmd}")
    print(f"   Log file: {log_file}")
    print()
    print("=" * 80)
    print("EVAL VERIFIER OUTPUT (streaming)")
    print("=" * 80)

    env = build_agent_environment(provider)

    # The verifier's mandate is to REPORT on the scoring contract, not to
    # edit it — but the agent process necessarily has filesystem access to
    # scoring/. Snapshot the reviewed files (None = absent, so a file the
    # agent CREATES is also caught) so any modification can be detected,
    # restored, and turned into a failing verdict.
    reviewed_files = {}
    for reviewed_name in ('eval.py', 'targets.json', 'rule_maker_log.md'):
        reviewed_path = scoring_dir / reviewed_name
        reviewed_files[reviewed_name] = (
            reviewed_path.read_bytes() if reviewed_path.exists() else None)

    start_time = time.time()

    # The shared deadline-aware runner streams sanitized output to console,
    # log, and transcript, and enforces the timeout on wall clock (a stuck
    # verifier keeping stdout open cannot hang the pipeline).
    launch = run_prebuilt_cli_agent(
        command_argv=shlex.split(cmd),
        prompt=prompt,
        work_dir=work_dir,
        log_file=log_file,
        transcript_file=transcript_file,
        env=env,
        timeout=timeout,
    )

    if launch["timed_out"]:
        # Fail closed: a verdict the agent managed to write before the kill
        # must not be trusted — the review never finished.
        print(f"\n⏱️  Eval verifier timed out after {timeout} seconds")
        verdict_path.unlink(missing_ok=True)
        return {
            'success': False,
            'passed': False,
            'violations': [
                {'check': 'timeout',
                 'detail': f"verifier timed out after {timeout}s; any partial "
                           f"verdict was discarded"}
            ],
            'log_file': str(log_file),
            'transcript_file': str(transcript_file),
            'elapsed_time': time.time() - start_time,
        }

    print()
    print("=" * 80)
    elapsed = time.time() - start_time
    print(
        f"⏱️  Eval verifier completed in {elapsed:.1f}s "
        f"({elapsed / 60:.1f} minutes)"
    )

    return_code = launch["return_code"]
    if return_code == 0:
        print("✅ Agent process exited cleanly.")
    else:
        print(f"⚠️  Agent exited with return code: {return_code}")

    # Enforce read-only review: restore any reviewed file the agent touched
    # and fail the verification outright — a verifier that edits the
    # contract it reviews cannot be trusted to have judged it.
    tampered = []
    for reviewed_name, original_bytes in reviewed_files.items():
        reviewed_path = scoring_dir / reviewed_name
        current = reviewed_path.read_bytes() if reviewed_path.exists() else None
        if current != original_bytes:
            if original_bytes is None:
                reviewed_path.unlink(missing_ok=True)  # agent created it
            else:
                reviewed_path.write_bytes(original_bytes)
            tampered.append(reviewed_name)
    if tampered:
        print(f"⚠️  Verifier modified reviewed scoring files "
              f"({', '.join(tampered)}); originals restored, verification failed.")
        return {
            'success': True,
            'passed': False,
            'violations': [
                {'check': 'read_only',
                 'detail': f"verifier modified reviewed scoring files: "
                           f"{', '.join(tampered)} (restored)"}
            ],
            'log_file': str(log_file),
            'transcript_file': str(transcript_file),
            'elapsed_time': time.time() - start_time,
        }

    # Read the verdict
    verdict = read_verdict(work_dir)
    if verdict is None:
        print("⚠️  Eval verifier produced no parseable verification.json")
        return {
            'success': False,
            'passed': False,
            'violations': [
                {'check': 'verdict', 'detail': 'verifier produced no parseable verification.json'}
            ],
            'log_file': str(log_file),
            'transcript_file': str(transcript_file),
            'elapsed_time': time.time() - start_time,
        }

    passed, verdict_violations = interpret_verdict(verdict, extract_eval_contract(idea))
    violations = verdict_violations
    if passed:
        print("✅ Scoring contract verified against user declarations.")
    else:
        print("⚠️  Scoring contract violates user declarations:")
        for violation in violations:
            detail = violation.get('detail', violation) if isinstance(violation, dict) else violation
            print(f"     - {detail}")

    return {
        'success': True,
        'passed': passed,
        'violations': violations,
        'log_file': str(log_file),
        'transcript_file': str(transcript_file),
        'elapsed_time': time.time() - start_time,
    }


def interpret_verdict(
    verdict: Dict[str, Any],
    contract: Dict[str, Any],
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Strictly interpret a verification.json verdict against the structure the
    eval_verifier template mandates and against the user's declared contract
    (the output of extract_eval_contract for the submitted idea). Every check
    below fails closed and is surfaced as its own violation:

    - `pass` must be a JSON boolean; bool() coercion would accept any non-empty
      string — including "false" — as passing.
    - `violations` must always be present as an array of mappings each
      carrying a concrete detail; a missing key, null, or any other shape is
      a failed verdict, never an exception, so a malformed verifier response
      still reaches the normal retry path.
    - `checks` must report every mandated check (routing, transcription,
      format) with pass/fail/not_applicable; a check that does not apply must
      say `not_applicable` explicitly rather than be omitted, so a verifier
      cannot silently skip part of the contract.
    - A check the contract makes applicable (per VERDICT_CHECKS) must not be
      reported `not_applicable`: the verifier only runs because the contract
      declares that component, so waving it off is a silent skip.
    - `pass` must be consistent with the evidence in BOTH directions: true
      requires no failing check AND an empty violations list (a reported
      defect contradicts a pass), while false requires at least one recorded
      violation (a failing verdict must justify itself).

    Net invariant: a verdict passes iff `pass` is true, every mandated check
    is reported, every applicable check passed, and `violations` is exactly
    empty.

    Returns:
        (passed, violations)
    """
    raw_pass = verdict.get('pass')
    passed = raw_pass is True

    # Validate the violations container once; everything below reads only the
    # validated list. The template mandates `violations` as an always-present
    # array (empty when passing), so a missing key or null fails too.
    declared_violations = verdict.get('violations')
    bad_container = not isinstance(declared_violations, list)
    if bad_container:
        bad_value = declared_violations
        declared_violations = []

    violations = list(declared_violations)

    def reject(detail: str) -> None:
        nonlocal passed
        passed = False
        violations.append({'check': 'verdict', 'detail': detail})

    if bad_container:
        reject(f"verification.json 'violations' must be an array (empty when "
               f"the verdict passes), got {bad_value!r}")

    if not isinstance(raw_pass, bool):
        reject(f"verification.json 'pass' must be a JSON boolean, got {raw_pass!r}")

    checks = verdict.get('checks')
    if not isinstance(checks, dict) or not checks:
        reject(f"verification.json must include a non-empty 'checks' mapping, got {checks!r}")
    else:
        failed = []
        for name, value in checks.items():
            if name not in VERDICT_CHECKS:
                reject(f"unknown check {name!r}; expected one of {list(VERDICT_CHECKS)}")
            if value not in VERDICT_CHECK_VALUES:
                reject(f"check {name!r} has invalid value {value!r}; "
                       f"expected one of {list(VERDICT_CHECK_VALUES)}")
            elif value == 'fail':
                failed.append(name)
        missing = [name for name in VERDICT_CHECKS if name not in checks]
        if missing:
            reject(f"verification.json 'checks' must report every mandated check "
                   f"(use 'not_applicable' when a check does not apply); missing: {missing}")
        # A check the submitted contract makes applicable cannot be waved off:
        # the verifier only ran because at least one of these components was
        # declared, so an all-not_applicable verdict would verify nothing.
        waved_off = [
            name for name, applicable in VERDICT_CHECKS.items()
            if applicable(contract) and checks.get(name) == 'not_applicable'
        ]
        if waved_off:
            reject(f"checks {waved_off} are applicable under the submitted "
                   f"contract but were reported 'not_applicable'")
        # `pass` is true only when every applicable check passes.
        if raw_pass is True and failed:
            reject(f"'pass' is true but these checks failed: {failed}")

    # `pass` and the violations list must agree in both directions: a failing
    # verdict must justify itself, and a passing verdict cannot carry a
    # defect report it claims to have cleared.
    if raw_pass is False and not declared_violations:
        reject("verification.json reports pass=false with no violations listed")
    if raw_pass is True and declared_violations:
        reject(f"'pass' is true but {len(declared_violations)} violation(s) "
               f"were reported; a reported defect contradicts a pass")

    # Each declared violation must be a mapping carrying a concrete detail.
    for entry in declared_violations:
        if not isinstance(entry, dict) or not str(entry.get('detail', '')).strip():
            reject(f"malformed violation entry: {entry!r}")

    return passed, violations


def read_verdict(work_dir: Path) -> Optional[Dict[str, Any]]:
    """
    Load scoring/verification.json. Returns None when missing or unparseable
    (both are treated as verification failure by the caller).
    """
    verdict_path = Path(work_dir) / "scoring" / VERDICT_FILE_NAME
    if not verdict_path.exists():
        return None
    try:
        verdict = json.loads(verdict_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return verdict if isinstance(verdict, dict) else None


def format_violations_for_retry(violations) -> str:
    """
    Render verifier violations as a block to append to the rule_maker's
    retry prompt.
    """
    lines = []
    for violation in violations or []:
        if isinstance(violation, dict):
            check = violation.get('check', 'contract')
            detail = violation.get('detail', '')
            evidence = violation.get('evidence', '')
            line = f"- [{check}] {detail}"
            if evidence:
                line += f"\n  Evidence: {evidence}"
            lines.append(line)
        else:
            lines.append(f"- {violation}")
    listing = "\n".join(lines) if lines else "- (no detail provided)"
    return (
        "\n" + "=" * 80 + "\n"
        "        VERIFIER FINDINGS FROM YOUR PREVIOUS ATTEMPT (MUST FIX)\n"
        + "=" * 80 + "\n\n"
        "A verifier reviewed your previous scoring/ outputs against the user's\n"
        "declared evaluation contract and rejected them. Rewrite the deliverables\n"
        "so every finding below is resolved:\n\n"
        f"{listing}\n"
    )


# --- Manager-facing conformance report ------------------------------------- #
#
# The HITL manager must not read the sealed evaluator files (scoring/eval.py,
# targets.json). The verifier can, so it produces a conformance report the
# manager reads as advisory evidence when it reviews the rule maker.
#
# The report is leak-proof BY CONSTRUCTION: it is assembled only from a fixed
# status (PASS / CONCERNS / UNAVAILABLE) and canned, code-owned descriptions
# keyed by the verifier's recognized check names. It never echoes the verdict's
# `detail` or `evidence` strings, an unrecognized check name, or any other value
# derived from the sealed files, so no sealed content can reach the manager
# through it. The verifier learns "which named check failed"; it does not relay
# what the evaluator contains.

_MANAGER_CONCERN_DESCRIPTIONS = {
    "transcription": "the scoring targets may not carry the metrics or targets "
                     "the user declared",
    "routing": "the evaluator may not compute the mandated measurements or use a "
               "required function",
    "format": "the declared results format may not be honored",
}
_MANAGER_GENERIC_CONCERN = "a declared evaluation requirement may not be met"


def build_manager_conformance_report(verdict: Dict[str, Any]) -> str:
    """Render a verifier verdict as a leak-proof, manager-facing report.

    - verifier could not complete -> UNAVAILABLE (not a signal about the design)
    - contract satisfied          -> PASS
    - contract not satisfied      -> CONCERNS with canned per-check categories

    Contains no code, file contents, `detail`/`evidence` strings, or any value
    derived from the sealed evaluator. Every byte comes from a fixed status
    string or a canned description keyed by a recognized check name.
    """
    verdict = verdict or {}
    if not verdict.get("success"):
        return (
            "Automated conformance check: UNAVAILABLE. The verifier could not "
            "complete, so this is not a signal about the scoring design. Decide "
            "from your own review of the public design."
        )
    if verdict.get("passed"):
        return (
            "Automated conformance check: PASS. The scoring design is reported to "
            "satisfy the user's declared evaluation contract (mandated metrics, "
            "targets, evaluation split, and required functions)."
        )
    # CONCERNS: emit only canned category descriptions, deduplicated. An
    # unrecognized check name is mapped to the generic description and never
    # echoed, so nothing agent- or file-derived reaches the manager.
    descriptions: List[str] = []
    for violation in verdict.get("violations") or []:
        check = violation.get("check") if isinstance(violation, dict) else None
        described = _MANAGER_CONCERN_DESCRIPTIONS.get(str(check), _MANAGER_GENERIC_CONCERN)
        if described not in descriptions:
            descriptions.append(described)
    if not descriptions:
        descriptions.append(_MANAGER_GENERIC_CONCERN)
    lines = [
        "Automated conformance check: CONCERNS. The scoring design may not satisfy "
        "the user's declared evaluation contract:"
    ]
    lines.extend(f"- {described}" for described in descriptions)
    lines.append(
        "This is advisory and carries no detail from the sealed evaluator. If a "
        "concern looks real, return feedback asking the rule maker to recheck that "
        "requirement against its own scoring/ files; otherwise decide from your "
        "own review."
    )
    return "\n".join(lines)
