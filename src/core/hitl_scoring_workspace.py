"""Runtime-owned scoring workspaces for experimental HITL AutoResearch.

The ordinary scorer continues to run against its normal workspace.  HITL
AutoResearch uses this module so evaluator inputs never need to be restored to
the public workspace where an experiment worker is running.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional, Tuple
import json
import hashlib
import os
import shutil
import tempfile

from core.hitl_git import run_git
from core.scoring_seal import SEALED_PATHS, verify_sealed_scoring_manifest
from core.hitl_util import atomic_write_bytes, sha256_file


class HitlScoringWorkspaceError(RuntimeError):
    """Raised when runtime cannot prepare an isolated HITL scorer workspace."""


def _copy_path(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _write_public_results(path: Path, source: Path) -> str:
    """Publish a scorer review copy atomically, without making it authoritative."""
    payload = source.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    atomic_write_bytes(path, payload, fsync_parent=False)
    if sha256_file(path) != digest:
        raise HitlScoringWorkspaceError("Runtime could not verify the public scoring review copy.")
    return digest


@contextmanager
def isolated_scoring_workspace(
    *,
    work_dir: Path,
    source_sha: str,
    sealed_dir: Optional[Path],
) -> Iterator[Tuple[Path, str]]:
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
    try:
        evaluator_manifest_sha256 = verify_sealed_scoring_manifest(sealed_root)
    except RuntimeError as exc:
        raise HitlScoringWorkspaceError(
            f"Runtime rejected the sealed evaluator payload: {exc}"
        ) from exc

    temporary_parent = Path(tempfile.mkdtemp(prefix="neurico-hitl-scorer-"))
    os.chmod(temporary_parent, 0o700)
    scorer_dir = temporary_parent / "workspace"
    created = False
    try:
        completed = run_git(
            work_dir,
            "worktree",
            "add",
            "--detach",
            str(scorer_dir),
            normalized_sha,
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

        # Prepared datasets are public research inputs. They can be ignored by
        # Git, so the detached candidate tree may not contain them even though
        # the worker used them to produce the candidate being scored.
        public_datasets = work_dir / "datasets"
        if public_datasets.is_dir():
            _copy_path(public_datasets, scorer_dir / "datasets")

        # The experiment's configured environment is untracked, but ordinary
        # scoring uses it for task dependencies. Make it available only inside
        # this private scorer worktree; the scored source remains immutable.
        candidate_venv = work_dir / ".venv"
        if candidate_venv.is_dir():
            (scorer_dir / ".venv").symlink_to(candidate_venv, target_is_directory=True)
        yield scorer_dir, evaluator_manifest_sha256
    finally:
        if created:
            run_git(
                work_dir,
                "worktree",
                "remove",
                "--force",
                str(scorer_dir),
                check=False,
                quiet=True,
            )
            run_git(work_dir, "worktree", "prune", check=False, quiet=True)
        shutil.rmtree(temporary_parent, ignore_errors=True)


def run_isolated_scorer(
    *,
    work_dir: Path,
    source_sha: str,
    sealed_dir: Optional[Path],
    scorer: Callable[[Path], Dict[str, Any]],
    temporary_ref: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a scorer privately and commit its result from the immutable source tree.

    The public workspace receives a review copy of ``results.json`` only. The
    retained checkpoint is committed inside the detached source worktree, so
    provider-side writes to the live workspace cannot change the scored tree.
    """
    public_work_dir = Path(work_dir).resolve()
    with isolated_scoring_workspace(
        work_dir=public_work_dir,
        source_sha=source_sha,
        sealed_dir=sealed_dir,
    ) as (scorer_work_dir, evaluator_manifest_sha256):
        raw_result = scorer(scorer_work_dir)
        if not isinstance(raw_result, dict):
            raise HitlScoringWorkspaceError("Runtime scorer must return an object.")
        result = dict(raw_result)
        results = result.get("results")
        if not isinstance(results, dict):
            raise HitlScoringWorkspaceError("Runtime scorer returned no structured results.")
        scorer_results = scorer_work_dir / "scoring" / "results.json"
        scorer_results.parent.mkdir(parents=True, exist_ok=True)
        scorer_results.write_text(
            json.dumps(results, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        commit = run_git(
            scorer_work_dir,
            "add",
            "--",
            "scoring/results.json",
            check=False,
        )
        if commit.returncode == 0:
            commit = run_git(
                scorer_work_dir,
                "commit",
                "-m",
                "HITL runtime scored result",
                check=False,
            )
        if commit.returncode != 0:
            detail = (commit.stderr or commit.stdout or "unknown Git error").strip()
            raise HitlScoringWorkspaceError(
                f"Runtime could not commit the isolated scored result: {detail}"
            )
        resolved = run_git(scorer_work_dir, "rev-parse", "HEAD", check=False)
        if resolved.returncode != 0:
            raise HitlScoringWorkspaceError("Runtime could not resolve the scored checkpoint.")
        scored_checkpoint_sha = resolved.stdout.strip()
        if temporary_ref:
            retained = run_git(
                scorer_work_dir,
                "update-ref",
                temporary_ref,
                scored_checkpoint_sha,
                check=False,
            )
            if retained.returncode != 0:
                detail = (retained.stderr or retained.stdout or "unknown Git error").strip()
                raise HitlScoringWorkspaceError(
                    f"Runtime could not retain the isolated scored checkpoint: {detail}"
                )
        public_results = public_work_dir / "scoring" / "results.json"
        results_sha256 = _write_public_results(public_results, scorer_results)
        result["results_path"] = str(public_results)
        result["source_checkpoint_sha"] = source_sha
        result["scored_checkpoint_sha"] = scored_checkpoint_sha
        if temporary_ref:
            result["scoring_ref"] = temporary_ref
        result["results_sha256"] = results_sha256
        result["evaluator_manifest_sha256"] = evaluator_manifest_sha256
        result.pop("log_path", None)
        result["isolated"] = True
        return result
