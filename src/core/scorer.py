"""
Scorer Stage

Executes scoring/eval.py (written by the rule_maker agent) against the
artifact produced by experiment_runner. Captures structured results in
scoring/results.json and stdout/stderr in scoring/eval_log.txt.

The scorer is mechanical: no agent invocation, no LLM call. It simply
runs the per-run evaluation script as a subprocess and surfaces the JSON
it writes.
"""

from pathlib import Path
from typing import Optional, Dict, Any
import subprocess
import json
import sys
import time


# Files the scorer reads / writes (relative to <workspace>/scoring/)
EVAL_SCRIPT_NAME = "eval.py"
RESULTS_FILE_NAME = "results.json"
LOG_FILE_NAME = "eval_log.txt"


def _resolve_python_executable(work_dir: Path) -> str:
    """
    Pick the Python interpreter to invoke eval.py with.

    The experiment_runner creates <workspace>/.venv during its setup phase
    and installs all task-specific dependencies there. eval.py typically
    imports those same dependencies (numpy, torch, sklearn, etc.), so it
    must run under the workspace's interpreter rather than the
    orchestrator's. Falls back to sys.executable if the workspace has no
    .venv yet (e.g., during a scorer-only smoke test).
    """
    posix = work_dir / ".venv" / "bin" / "python"
    if posix.exists() and posix.is_file():
        return str(posix)
    windows = work_dir / ".venv" / "Scripts" / "python.exe"
    if windows.exists() and windows.is_file():
        return str(windows)
    return sys.executable


def run_scorer(
    work_dir: Path,
    timeout: int = 600,
    python_executable: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute scoring/eval.py against the runner's artifact.

    Args:
        work_dir: Workspace root containing scoring/eval.py and the
                  runner's outputs.
        timeout: Max execution time for eval.py in seconds.
        python_executable: Python binary to use. Defaults to the workspace's
                  own .venv interpreter (where the runner installed deps),
                  falling back to sys.executable.

    Returns:
        Dict with:
          - success: bool -- eval.py exited 0 AND results.json parsed cleanly
          - return_code: int | None -- eval.py's exit code (None on timeout)
          - results: dict | None -- parsed results.json contents
          - results_path: str -- absolute path to results.json
          - log_path: str -- absolute path to eval_log.txt
          - elapsed_time: float
          - error: str | None -- error message if anything failed
    """
    work_dir = Path(work_dir)
    scoring_dir = work_dir / "scoring"
    eval_script = scoring_dir / EVAL_SCRIPT_NAME
    results_path = scoring_dir / RESULTS_FILE_NAME
    log_path = scoring_dir / LOG_FILE_NAME

    if not eval_script.exists():
        return {
            'success': False,
            'return_code': None,
            'results': None,
            'results_path': str(results_path),
            'log_path': str(log_path),
            'elapsed_time': 0.0,
            'error': f"scoring/eval.py not found at {eval_script}",
        }

    # Clear stale results so we never read leftover values from a prior run
    if results_path.exists():
        results_path.unlink()

    python_executable = python_executable or _resolve_python_executable(work_dir)
    cmd = [python_executable, str(eval_script)]

    print(f"📊 Running scorer: {' '.join(cmd)}")
    print(f"   Working dir: {work_dir}")
    print(f"   Python: {python_executable}")
    print(f"   Log: {log_path}")

    start_time = time.time()
    return_code: Optional[int] = None
    error: Optional[str] = None

    try:
        completed = subprocess.run(
            cmd,
            cwd=str(work_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            text=True,
            encoding='utf-8',
        )
        log_path.write_text(completed.stdout or "", encoding='utf-8')
        return_code = completed.returncode
        if return_code != 0:
            error = f"eval.py exited with non-zero code {return_code}"
    except subprocess.TimeoutExpired as e:
        error = f"scorer timed out after {timeout}s"
        print(f"⏱️  {error}")
        partial = ""
        if e.stdout:
            partial = (
                e.stdout
                if isinstance(e.stdout, str)
                else e.stdout.decode('utf-8', errors='replace')
            )
        log_path.write_text(
            f"{partial}\n[TIMEOUT after {timeout}s]\n", encoding='utf-8'
        )
    except Exception as e:
        error = f"scorer exception: {e}"
        print(f"❌ {error}")

    elapsed = time.time() - start_time

    results: Optional[Dict[str, Any]] = None
    if results_path.exists():
        try:
            results = json.loads(results_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as e:
            json_err = f"results.json is not valid JSON: {e}"
            error = f"{error}; {json_err}" if error else json_err

    success = return_code == 0 and results is not None and error is None

    if success:
        print(f"✅ Scorer completed in {elapsed:.1f}s")
    else:
        print(
            f"⚠️  Scorer finished with issues "
            f"(return_code={return_code}, error={error})"
        )

    return {
        'success': success,
        'return_code': return_code,
        'results': results,
        'results_path': str(results_path),
        'log_path': str(log_path),
        'elapsed_time': elapsed,
        'error': error,
    }


def load_scoring_results(work_dir: Path) -> Optional[Dict[str, Any]]:
    """
    Read scoring/results.json from a workspace.

    Convenience for downstream consumers (paper_writer, supervisor) that
    only need the score, not the full scorer-run dict.

    Returns:
        Parsed results.json contents, or None if the file is missing or
        unparseable.
    """
    results_path = Path(work_dir) / "scoring" / RESULTS_FILE_NAME
    if not results_path.exists():
        return None
    try:
        return json.loads(results_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return None
