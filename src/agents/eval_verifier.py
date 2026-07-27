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
from typing import Optional, Dict, Any
import subprocess
import shlex
import shutil
import os
import sys
import threading
import time
import json

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.security import sanitize_text

# CLI commands for different providers (mirrors rule_maker.py)
CLI_COMMANDS = {
    'claude': 'claude -p',
    'codex': 'codex exec',
    'gemini': 'gemini',
}

# Verbose / structured-transcript output flags per provider
TRANSCRIPT_FLAGS = {
    'claude': '--verbose --output-format stream-json',
    'codex': '--json',
    'gemini': '--output-format stream-json',
}

VERDICT_FILE_NAME = "verification.json"


def has_user_eval_contract(idea: Dict[str, Any]) -> bool:
    """
    Return True when the idea declares something the verifier must check:
    structured evaluation metrics, a declared results format, or a mandated
    evaluation function.
    """
    idea_spec = idea.get('idea', idea) if isinstance(idea, dict) else {}
    if not isinstance(idea_spec, dict):
        return False

    evaluation = idea_spec.get('evaluation')
    if isinstance(evaluation, dict) and (
        evaluation.get('metrics') or evaluation.get('results_format')
    ):
        return True

    resources = idea_spec.get('local_resources')
    if isinstance(resources, dict):
        for func in resources.get('functions') or []:
            if isinstance(func, dict) and func.get('required_for_evaluation'):
                return True

    return False


def extract_eval_contract(idea: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pull the contract-relevant slices of the idea for the verifier's prompt:
    the structured evaluation spec plus any mandated evaluation functions.
    """
    idea_spec = idea.get('idea', idea) if isinstance(idea, dict) else {}
    resources = idea_spec.get('local_resources') or {}
    mandated = [
        func for func in (resources.get('functions') or [])
        if isinstance(func, dict) and func.get('required_for_evaluation')
    ]
    return {
        'evaluation': idea_spec.get('evaluation') or {},
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
    attempt = 1
    while (logs_dir / f"eval_verifier_{provider}_attempt{attempt}.log").exists():
        attempt += 1
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

    # Build CLI command
    cmd = CLI_COMMANDS[provider]
    if full_permissions:
        if provider == "codex":
            cmd += " --yolo"
        elif provider == "claude":
            cmd += " --dangerously-skip-permissions"
        elif provider == "gemini":
            cmd += " --yolo --skip-trust"

    transcript_flag = TRANSCRIPT_FLAGS.get(provider, '')
    if transcript_flag:
        cmd += f" {transcript_flag}"

    print(f"▶️  Launching {provider} CLI agent...")
    print(f"   Command: {cmd}")
    print(f"   Log file: {log_file}")
    print()
    print("=" * 80)
    print("EVAL VERIFIER OUTPUT (streaming)")
    print("=" * 80)

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    if provider == "gemini":
        env['GEMINI_CLI_IDE_DISABLE'] = '1'

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

    try:
        with open(log_file, 'w', encoding='utf-8') as log_f, \
                open(transcript_file, 'w', encoding='utf-8') as transcript_f:
            process = subprocess.Popen(
                shlex.split(cmd),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                encoding='utf-8',
                bufsize=1,
                cwd=str(work_dir),
            )
            process.stdin.write(prompt)
            process.stdin.close()

            # Drain stdout on a helper thread so the timeout below is
            # enforced on wall clock. Reading to EOF inline would block for
            # as long as the agent keeps stdout open, so wait(timeout=...)
            # would never be reached and a stuck verifier would hang the
            # pipeline indefinitely.
            def _drain():
                try:
                    for line in iter(process.stdout.readline, ''):
                        if line:
                            sanitized = sanitize_text(line)
                            print(sanitized, end='')
                            log_f.write(sanitized)
                            transcript_f.write(sanitized)
                except ValueError:
                    # Log files closed after a timeout kill while an
                    # orphaned child still held the pipe open — drop the
                    # remaining output rather than crash the thread.
                    pass

            reader = threading.Thread(target=_drain, daemon=True)
            reader.start()
            try:
                return_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Kill inside the with-block so the reader hits EOF and
                # finishes before the log files close.
                process.kill()
                process.wait()
                reader.join(timeout=10)
                raise
            reader.join(timeout=10)

        print()
        print("=" * 80)
        elapsed = time.time() - start_time
        print(
            f"⏱️  Eval verifier completed in {elapsed:.1f}s "
            f"({elapsed / 60:.1f} minutes)"
        )

        if return_code == 0:
            print("✅ Agent process exited cleanly.")
        else:
            print(f"⚠️  Agent exited with return code: {return_code}")

    except subprocess.TimeoutExpired:
        # Fail closed: a verdict the agent managed to write before the kill
        # must not be trusted — the review never finished.
        print(f"\n⏱️  Eval verifier timed out after {timeout} seconds")
        process.kill()
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

    except Exception as e:
        print(f"\n❌ Error during eval_verifier execution: {e}")
        raise

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

    passed, verdict_violations = interpret_verdict(verdict)
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


def interpret_verdict(verdict: Dict[str, Any]) -> tuple:
    """
    Strictly interpret a verification.json verdict.

    Only JSON true counts as a pass: bool() coercion would accept any
    non-empty string — including "false" — as passing. A non-boolean
    'pass' value fails and is surfaced as its own violation.

    Returns:
        (passed, violations)
    """
    raw_pass = verdict.get('pass')
    passed = raw_pass is True
    violations = verdict.get('violations') or []
    if not passed and not isinstance(raw_pass, bool):
        violations = list(violations) + [{
            'check': 'verdict',
            'detail': f"verification.json 'pass' must be a JSON boolean, got {raw_pass!r}",
        }]
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
