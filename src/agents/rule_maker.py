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
import subprocess
import shlex
import os
import sys
import time
import json
import ast

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.security import sanitize_text


# CLI commands for different providers (mirrors resource_finder.py)
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

# Files the rule_maker is responsible for producing (relative to scoring/)
RULE_MAKER_OUTPUT_FILES = {
    'eval_script': 'eval.py',
    'targets': 'targets.json',
    'interface': 'interface.md',
    'rationale_log': 'rule_maker_log.md',
}


def generate_rule_maker_prompt(
    idea: Dict[str, Any],
    work_dir: Path,
    templates_dir: Path,
    domain: Optional[str] = None,
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

    # Load the general body. It lives at templates/agents/rule_maker.txt,
    # alongside the other per-run agents (resource_finder.txt, paper_writer.txt).
    # Per-domain supplements live separately at templates/domains/<d>/rule_maker.txt.
    base_path = templates_dir / "agents" / "rule_maker.txt"
    if not base_path.exists():
        raise FileNotFoundError(
            f"rule_maker base template not found at {base_path}. "
            "Create templates/agents/rule_maker.txt before running."
        )
    base_template = base_path.read_text(encoding='utf-8')

    scoring_dir = work_dir / "scoring"
    output_files = "\n".join(
        f"  - scoring/{name}" for name in RULE_MAKER_OUTPUT_FILES.values()
    )
    resource_listing = _summarize_resource_outputs(work_dir)

    try:
        idea_repr = json.dumps(idea, indent=2, default=str)
    except (TypeError, ValueError):
        idea_repr = repr(idea)

    substitutions = {
        '{idea_yaml}': idea_repr,
        '{workspace}': str(work_dir),
        '{scoring_dir}': str(scoring_dir),
        '{output_files}': output_files,
        '{resource_listing}': resource_listing,
    }

    prompt = base_template
    for placeholder, value in substitutions.items():
        prompt = prompt.replace(placeholder, value)

    # Append per-domain supplement (if any) with a banner.
    resolved_domain = _resolve_domain(idea, domain)
    supplement = _load_domain_supplement(templates_dir, resolved_domain)
    if supplement:
        banner = "=" * 80
        domain_label = resolved_domain.upper().replace('_', ' ')
        prompt = (
            f"{prompt}\n\n"
            f"{banner}\n"
            f"           RULE MAKER DOMAIN GUIDELINES: {domain_label}\n"
            f"{banner}\n\n"
            f"{supplement}\n"
        )

    return prompt


def _resolve_domain(
    idea: Dict[str, Any], override: Optional[str]
) -> str:
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
    nested = idea.get('idea', {}) if isinstance(idea, dict) else {}
    if isinstance(nested, dict) and nested.get('domain'):
        return nested['domain']
    if isinstance(idea, dict) and idea.get('domain'):
        return idea['domain']
    return 'machine_learning'


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
    return supplement_path.read_text(encoding='utf-8')


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
            lines.append(
                f"  - {label}: {len(entries)} entries [{preview}{extra}]"
            )
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
) -> Dict[str, Any]:
    """
    Launch the rule_maker CLI agent.

    Returns:
        Dict with: success, outputs (paths of generated files), issues,
        log_file, transcript_file, elapsed_time.
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
    scoring_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = work_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    print(f"📐 Starting Rule Maker Agent")
    print(f"   Provider: {provider}")
    print(f"   Work dir: {work_dir}")
    print(f"   Timeout: {timeout}s ({timeout // 60} minutes)")
    print("=" * 80)

    # Generate prompt and persist it for debugging
    prompt = generate_rule_maker_prompt(idea, work_dir, templates_dir)
    prompt_file = logs_dir / "rule_maker_prompt.txt"
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

    log_file = logs_dir / f"rule_maker_{provider}.log"
    transcript_file = logs_dir / f"rule_maker_{provider}_transcript.jsonl"

    print(f"▶️  Launching {provider} CLI agent...")
    print(f"   Command: {cmd}")
    print(f"   Log file: {log_file}")
    print()
    print("=" * 80)
    print("RULE MAKER OUTPUT (streaming)")
    print("=" * 80)

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    if provider == "gemini":
        env['GEMINI_CLI_IDE_DISABLE'] = '1'

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

            for line in iter(process.stdout.readline, ''):
                if line:
                    sanitized = sanitize_text(line)
                    print(sanitized, end='')
                    log_f.write(sanitized)
                    transcript_f.write(sanitized)

            return_code = process.wait(timeout=timeout)

        print()
        print("=" * 80)
        elapsed = time.time() - start_time
        print(
            f"⏱️  Rule maker completed in {elapsed:.1f}s "
            f"({elapsed / 60:.1f} minutes)"
        )

        if return_code == 0:
            print("✅ Agent process exited cleanly.")
        else:
            print(f"⚠️  Agent exited with return code: {return_code}")

    except subprocess.TimeoutExpired:
        print(f"\n⏱️  Rule maker timed out after {timeout} seconds")
        process.kill()

    except Exception as e:
        print(f"\n❌ Error during rule_maker execution: {e}")
        raise

    # Validate outputs
    print()
    print("📦 Validating rule_maker outputs...")
    validation = validate_rule_maker_outputs(work_dir)
    success = validation['valid']
    if success:
        print("✅ All required rule_maker outputs present and parseable.")
    else:
        print("⚠️  Rule maker outputs incomplete or invalid:")
        for issue in validation['issues']:
            print(f"     - {issue}")

    return {
        'success': success,
        'outputs': validation['found'],
        'issues': validation['issues'],
        'log_file': str(log_file),
        'transcript_file': str(transcript_file),
        'elapsed_time': time.time() - start_time,
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

    eval_path = scoring_dir / RULE_MAKER_OUTPUT_FILES['eval_script']
    if not eval_path.exists():
        issues.append(f"missing: {eval_path}")
    else:
        try:
            ast.parse(eval_path.read_text(encoding='utf-8'))
            found['eval_script'] = str(eval_path)
        except SyntaxError as e:
            issues.append(f"eval.py has syntax error: {e}")

    targets_path = scoring_dir / RULE_MAKER_OUTPUT_FILES['targets']
    if not targets_path.exists():
        issues.append(f"missing: {targets_path}")
    else:
        try:
            json.loads(targets_path.read_text(encoding='utf-8'))
            found['targets'] = str(targets_path)
        except json.JSONDecodeError as e:
            issues.append(f"targets.json is not valid JSON: {e}")

    interface_path = scoring_dir / RULE_MAKER_OUTPUT_FILES['interface']
    if not interface_path.exists():
        issues.append(f"missing: {interface_path}")
    elif interface_path.stat().st_size == 0:
        issues.append(f"empty: {interface_path}")
    else:
        found['interface'] = str(interface_path)

    rationale_path = scoring_dir / RULE_MAKER_OUTPUT_FILES['rationale_log']
    if rationale_path.exists():
        found['rationale_log'] = str(rationale_path)

    return {
        'valid': len(issues) == 0,
        'found': found,
        'issues': issues,
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
    interface_path = (
        Path(work_dir) / "scoring" / RULE_MAKER_OUTPUT_FILES['interface']
    )
    if not interface_path.exists():
        raise FileNotFoundError(
            f"scoring/interface.md not found at {interface_path}. "
            "rule_maker must run successfully before experiment_runner."
        )
    return interface_path.read_text(encoding='utf-8')
