"""Runtime-owned scoring workspaces for experimental HITL AutoResearch.

The ordinary scorer continues to run against its normal workspace.  HITL
AutoResearch uses this module so evaluator inputs never need to be restored to
the public workspace where an experiment worker is running.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional
import json
import os
import shutil
import subprocess
import tempfile

from core.scoring_seal import SEALED_PATHS


class HitlScoringWorkspaceError(RuntimeError):
    """Raised when runtime cannot prepare an isolated HITL scorer workspace."""


def _copy_path(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


@contextmanager
def isolated_scoring_workspace(
    *,
    work_dir: Path,
    source_sha: str,
    sealed_dir: Optional[Path],
) -> Iterator[Path]:
    """Yield a temporary evaluator-complete worktree owned by runtime.

    ``source_sha`` must be a public checkpoint created after the worker has
    finished but before scoring begins.  The worktree is deliberately outside
    the public workspace, and evaluator inputs are copied from the sealed
    runtime payload only for the scorer's lifetime.
    """
    work_dir = Path(work_dir).resolve()
    normalized_sha = str(source_sha).strip()
    if not normalized_sha:
        raise HitlScoringWorkspaceError("Isolated HITL scoring requires a source checkpoint SHA.")

    sealed_root = Path(sealed_dir).resolve() if sealed_dir is not None else None
    if sealed_root is None or not sealed_root.is_dir():
        raise HitlScoringWorkspaceError(
            "Isolated HITL scoring requires the runtime-owned sealed evaluator payload."
        )

    temporary_parent = Path(tempfile.mkdtemp(prefix="neurico-hitl-scorer-"))
    os.chmod(temporary_parent, 0o700)
    scorer_dir = temporary_parent / "workspace"
    created = False
    try:
        completed = subprocess.run(
            ["git", "-C", str(work_dir), "worktree", "add", "--detach", str(scorer_dir), normalized_sha],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown Git error").strip()
            raise HitlScoringWorkspaceError(
                f"Runtime could not create the isolated scorer worktree: {detail}"
            )
        created = True

        copied = 0
        for relative in SEALED_PATHS:
            source = sealed_root / relative.rstrip("/")
            if not source.exists():
                continue
            _copy_path(source, scorer_dir / relative.rstrip("/"))
            copied += 1
        if copied == 0:
            raise HitlScoringWorkspaceError(
                "The sealed evaluator payload contains none of the required scoring inputs."
            )
        yield scorer_dir
    finally:
        if created:
            subprocess.run(
                ["git", "-C", str(work_dir), "worktree", "remove", "--force", str(scorer_dir)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            subprocess.run(
                ["git", "-C", str(work_dir), "worktree", "prune"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        shutil.rmtree(temporary_parent, ignore_errors=True)


def run_isolated_scorer(
    *,
    work_dir: Path,
    source_sha: str,
    sealed_dir: Optional[Path],
    scorer: Callable[[Path], Dict[str, Any]],
) -> Dict[str, Any]:
    """Run a HITL scorer privately and materialize only ``results.json`` publicly.

    Evaluator logs and paths remain private to the runtime workspace.  The
    returned payload points at the public results artifact and is therefore
    safe to pass to the manager and downstream HITL state.
    """
    public_work_dir = Path(work_dir).resolve()
    with isolated_scoring_workspace(
        work_dir=public_work_dir,
        source_sha=source_sha,
        sealed_dir=sealed_dir,
    ) as scorer_work_dir:
        raw_result = scorer(scorer_work_dir)
        if not isinstance(raw_result, dict):
            raise HitlScoringWorkspaceError("Runtime scorer must return an object.")
        result = dict(raw_result)
        results = result.get("results")
        if isinstance(results, dict):
            public_results = public_work_dir / "scoring" / "results.json"
            public_results.parent.mkdir(parents=True, exist_ok=True)
            public_results.write_text(
                json.dumps(results, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            result["results_path"] = str(public_results)
        result.pop("log_path", None)
        result["isolated"] = True
        return result
