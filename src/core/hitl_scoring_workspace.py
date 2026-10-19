"""Runtime-owned scoring workspaces for experimental HITL AutoResearch.

The ordinary scorer continues to run against its normal workspace.  HITL
AutoResearch uses this module so evaluator inputs never need to be restored to
the public workspace where an experiment worker is running.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Iterator, Optional, Tuple
import json
import hashlib
import os
import shutil
import sys
import tarfile

from core.hitl_git import (
    HitlGitlinkError,
    git_failure_detail,
    prepare_git_commit_bundle_repository,
    resolve_checkpoint_gitlinks,
    run_git,
)
from core.hitl_artifact_snapshots import (
    HitlArtifactSnapshotError,
    capture_hitl_artifact_snapshot,
    materialize_hitl_artifact_snapshot,
    resolve_hitl_snapshot_gitlink_bundles,
)
from core.hitl_paths import hitl_artifact_contract_path
from core.scoring_seal import SEALED_PATHS, verify_sealed_scoring_manifest
from core.hitl_util import atomic_write_bytes, sha256_file
from core.research_environment import copy_workspace_mode_state, research_venv_dir


def _safe_tarfile_module(stdlib_module: Any = tarfile) -> Any:
    """Return a tarfile implementation with the safe data extraction filter."""
    if hasattr(stdlib_module, "data_filter"):
        return stdlib_module
    from backports import tarfile as backported_tarfile

    return backported_tarfile


safe_tarfile = _safe_tarfile_module()


class HitlScoringWorkspaceError(RuntimeError):
    """Raised when runtime cannot prepare an isolated HITL scorer workspace."""


def _isolated_scoring_parent(work_dir: Path) -> Path:
    """Return the single runtime-owned scorer slot for one public workspace."""
    workspace = Path(work_dir).resolve()
    workspace_id = hashlib.sha256(os.fsencode(workspace)).hexdigest()[:16]
    return workspace.parent / f".neurico-hitl-scorer-{workspace_id}"


def discard_isolated_scoring_workspace(work_dir: Path) -> None:
    """Reclaim this workspace's runtime-owned scorer slot after completion or loss."""
    workspace = Path(work_dir).resolve()
    temporary_parent = _isolated_scoring_parent(workspace)
    scorer_dir = temporary_parent / "workspace"
    run_git(
        workspace,
        "worktree",
        "remove",
        "--force",
        str(scorer_dir),
        check=False,
        quiet=True,
    )

    if temporary_parent.is_symlink() or (
        temporary_parent.exists() and not temporary_parent.is_dir()
    ):
        temporary_parent.unlink()
    elif temporary_parent.is_dir():
        shutil.rmtree(temporary_parent)

    pruned = run_git(workspace, "worktree", "prune", check=False, quiet=True)
    if pruned.returncode != 0:
        raise HitlScoringWorkspaceError(
            "Runtime could not prune isolated scorer worktree metadata: "
            f"{git_failure_detail(pruned)}"
        )


def prepare_isolated_scoring_artifacts(
    *,
    work_dir: Path,
    runtime_state: Any,
    request_key: str,
    source_checkpoint_sha: str,
    source_workspace_fingerprint: str,
    source_workspace_fingerprint_scope: Dict[str, Any],
    cached_score: Optional[Dict[str, Any]],
) -> tuple[Optional[str], Dict[str, Any]]:
    """Durably capture ignored evaluator artifacts for one scoring handoff."""
    snapshot_id = str(
        (cached_score or {}).get("artifact_snapshot_id", "")
    ).strip()
    if not snapshot_id and hitl_artifact_contract_path(work_dir).is_file():
        snapshot_id = str(request_key).strip()
    record: Dict[str, Any] = {
        "status": "prepared",
        "source_checkpoint_sha": str(source_checkpoint_sha).strip(),
        "source_workspace_fingerprint": str(source_workspace_fingerprint).strip(),
        "source_workspace_fingerprint_scope": dict(source_workspace_fingerprint_scope),
    }
    if snapshot_id:
        record["artifact_snapshot_id"] = snapshot_id
        runtime_state.update_pending_worker_command(
            request_key,
            isolated_scoring={**record, "status": "capturing"},
        )
        capture_hitl_artifact_snapshot(
            work_dir,
            snapshot_id=snapshot_id,
            source_checkpoint_sha=source_checkpoint_sha,
        )
    runtime_state.update_pending_worker_command(
        request_key,
        isolated_scoring=record,
    )
    return snapshot_id or None, record


def scoring_source_workspace_fingerprint(
    pending: Dict[str, Any],
    cached_score: Optional[Dict[str, Any]],
) -> str:
    """Return the reviewed fingerprint for a fresh or resumed scoring handoff."""
    if isinstance(cached_score, dict) and cached_score.get("status") in {
        "capturing",
        "prepared",
    }:
        source_fingerprint = str(
            cached_score.get("source_workspace_fingerprint", "")
        ).strip()
        if source_fingerprint:
            return source_fingerprint
    return str(pending.get("workspace_fingerprint", "")).strip()


def scoring_source_workspace_scope(
    pending: Dict[str, Any],
    cached_score: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return the frozen scope paired with the reviewed scoring fingerprint."""
    from core.hitl_workspace_guard import WorkspaceGuardScope

    if isinstance(cached_score, dict) and cached_score.get("status") in {
        "capturing",
        "prepared",
    }:
        cached_scope = cached_score.get("source_workspace_fingerprint_scope")
        if cached_scope is not None:
            return WorkspaceGuardScope.from_value(cached_scope).to_dict()
    return WorkspaceGuardScope.from_value(
        pending.get("workspace_fingerprint_scope")
    ).to_dict()


def _copy_path(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _prepare_scoring_directory(work_dir: Path) -> None:
    """Remove candidate-authored neighbors before restoring the sealed evaluator."""
    scoring_dir = work_dir / "scoring"
    if scoring_dir.is_symlink() or (scoring_dir.exists() and not scoring_dir.is_dir()):
        scoring_dir.unlink()
    elif scoring_dir.is_dir():
        shutil.rmtree(scoring_dir)
    scoring_dir.mkdir(parents=True)


def _contained_path(root: Path, relative: Path, *, description: str) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HitlScoringWorkspaceError(
            f"Runtime rejected {description} outside the workspace: {relative.as_posix()}."
        ) from exc
    return candidate


def validate_checkpoint_gitlinks(
    work_dir: Path,
    source_sha: str = "HEAD",
) -> list[str]:
    """Return issues for nested repositories that differ from their Gitlinks."""
    root = Path(work_dir).resolve()
    try:
        resolved_gitlinks = resolve_checkpoint_gitlinks(root, source_sha)
    except HitlGitlinkError as exc:
        return [str(exc)]

    issues: list[str] = []
    for gitlink, source_repo in resolved_gitlinks:
        relative = gitlink.relative_path
        commit_sha = gitlink.commit_sha
        relative_text = relative.as_posix()
        head = run_git(source_repo, "rev-parse", "HEAD", check=False)
        if head.returncode != 0:
            issues.append(
                "Could not inspect HEAD for checkpointed nested repository "
                f"`{relative_text}`: {git_failure_detail(head)}"
            )
        elif str(head.stdout).strip() != commit_sha:
            issues.append(
                "Checkpointed nested repository "
                f"`{relative_text}` is at a different commit than the workspace Gitlink."
            )

        status = run_git(
            source_repo,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            text=False,
            check=False,
        )
        if status.returncode != 0:
            issues.append(
                "Could not inspect working-tree status for checkpointed nested repository "
                f"`{relative_text}`: {git_failure_detail(status)}"
            )
        elif bytes(status.stdout or b""):
            issues.append(
                "Checkpointed nested repository "
                f"`{relative_text}` contains staged, modified, or untracked files."
            )
    return issues


def _extract_git_archive(archive_path: Path, destination: Path) -> None:
    """Extract an archive produced by Git after validating its member paths."""
    with safe_tarfile.open(archive_path, mode="r:") as archive:
        members = archive.getmembers()
        for member in members:
            member_path = PurePosixPath(member.name)
            if (
                member_path.is_absolute()
                or any(part in {"", ".", ".."} for part in member_path.parts)
                or member.isdev()
                or member.isfifo()
            ):
                raise HitlScoringWorkspaceError(
                    "Runtime rejected an unsafe path in a checkpointed nested repository."
                )
        archive.extractall(
            destination,
            members=members,
            filter=safe_tarfile.data_filter,
        )


def _materialize_checkpoint_gitlinks(
    *,
    work_dir: Path,
    scorer_dir: Path,
    source_sha: str,
    artifact_snapshot_id: Optional[str] = None,
) -> None:
    """Restore exact nested-repository contents omitted by ``git worktree``."""
    resolved_gitlinks = None
    bundle_repositories_root: Path | None = None
    try:
        if str(artifact_snapshot_id or "").strip():
            try:
                bundled_gitlinks = resolve_hitl_snapshot_gitlink_bundles(
                    work_dir,
                    snapshot_id=str(artifact_snapshot_id),
                    checkpoint_sha=source_sha,
                )
            except HitlArtifactSnapshotError as exc:
                raise HitlScoringWorkspaceError(str(exc)) from exc
            if bundled_gitlinks is not None:
                bundle_repositories_root = (
                    scorer_dir.parent / ".gitlink-bundle-repositories"
                )
                bundle_repositories_root.mkdir()
                resolved_gitlinks = []
                for index, (
                    gitlink,
                    bundle_path,
                    shallow_boundaries,
                ) in enumerate(bundled_gitlinks):
                    repository = bundle_repositories_root / f"{index:04d}.git"
                    try:
                        prepare_git_commit_bundle_repository(
                            repository,
                            bundle_path=bundle_path,
                            commit_sha=gitlink.commit_sha,
                            shallow_boundaries=shallow_boundaries,
                        )
                    except HitlGitlinkError as exc:
                        raise HitlScoringWorkspaceError(str(exc)) from exc
                    resolved_gitlinks.append((gitlink, repository))
        if resolved_gitlinks is None:
            try:
                resolved_gitlinks = resolve_checkpoint_gitlinks(work_dir, source_sha)
            except HitlGitlinkError as exc:
                raise HitlScoringWorkspaceError(str(exc)) from exc
        for index, (gitlink, source_repo) in enumerate(resolved_gitlinks):
            relative = gitlink.relative_path
            commit_sha = gitlink.commit_sha
            destination = _contained_path(
                scorer_dir,
                relative,
                description="Gitlink destination",
            )

            if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
                destination.unlink()
            elif destination.is_dir():
                shutil.rmtree(destination)
            destination.mkdir(parents=True)

            archive_path = scorer_dir.parent / f".gitlink-{index}.tar"
            archived = run_git(
                source_repo,
                "archive",
                "--format=tar",
                f"--output={archive_path}",
                commit_sha,
                check=False,
            )
            if archived.returncode != 0:
                raise HitlScoringWorkspaceError(
                    "Runtime could not export checkpointed nested repository "
                    f"{relative.as_posix()}: {git_failure_detail(archived)}"
                )
            try:
                _extract_git_archive(archive_path, destination)
            except (OSError, safe_tarfile.TarError) as exc:
                raise HitlScoringWorkspaceError(
                    "Runtime could not restore checkpointed nested repository "
                    f"{relative.as_posix()}: {exc}"
                ) from exc
            finally:
                archive_path.unlink(missing_ok=True)
    finally:
        if bundle_repositories_root is not None:
            shutil.rmtree(bundle_repositories_root, ignore_errors=True)


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
    artifact_snapshot_id: Optional[str] = None,
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

    discard_isolated_scoring_workspace(work_dir)
    temporary_parent = _isolated_scoring_parent(work_dir)
    temporary_parent.mkdir(mode=0o700)
    os.chmod(temporary_parent, 0o700)
    scorer_dir = temporary_parent / "workspace"
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
        _materialize_checkpoint_gitlinks(
            work_dir=work_dir,
            scorer_dir=scorer_dir,
            source_sha=normalized_sha,
            artifact_snapshot_id=artifact_snapshot_id,
        )

        # Prepared datasets are public research inputs. They can be ignored by
        # Git, so the detached candidate tree may not contain them even though
        # the worker used them to produce the candidate being scored.
        public_datasets = work_dir / "datasets"
        if public_datasets.is_dir():
            _copy_path(public_datasets, scorer_dir / "datasets")

        if str(artifact_snapshot_id or "").strip():
            materialize_hitl_artifact_snapshot(
                work_dir,
                snapshot_id=str(artifact_snapshot_id),
                destination=scorer_dir,
            )

        # Evaluator-owned files are restored last. Even a malformed artifact
        # contract cannot replace the sealed scorer implementation.
        _prepare_scoring_directory(scorer_dir)
        copy_workspace_mode_state(work_dir, scorer_dir)
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

        # The experiment's configured environment is untracked, but ordinary
        # scoring uses it for task dependencies. Make it available only inside
        # this private scorer worktree; the scored source remains immutable.
        candidate_venv = research_venv_dir(work_dir)
        if candidate_venv.is_dir():
            scorer_venv = research_venv_dir(scorer_dir)
            scorer_venv.parent.mkdir(parents=True, exist_ok=True)
            scorer_venv.symlink_to(candidate_venv, target_is_directory=True)
        yield scorer_dir, evaluator_manifest_sha256
    finally:
        active_error = sys.exc_info()[0] is not None
        try:
            discard_isolated_scoring_workspace(work_dir)
        except Exception as cleanup_error:
            if not active_error:
                raise
            print(
                "⚠️  Could not clean isolated scorer workspace after scoring failure: "
                f"{cleanup_error}"
            )


def run_isolated_scorer(
    *,
    work_dir: Path,
    source_sha: str,
    sealed_dir: Optional[Path],
    scorer: Callable[[Path], Dict[str, Any]],
    temporary_ref: Optional[str] = None,
    artifact_snapshot_id: Optional[str] = None,
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
        artifact_snapshot_id=artifact_snapshot_id,
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
