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
import tarfile
import tempfile

from core.hitl_git import run_git
from core.scoring_seal import SEALED_PATHS, verify_sealed_scoring_manifest
from core.hitl_util import atomic_write_bytes, sha256_file


class HitlScoringWorkspaceError(RuntimeError):
    """Raised when runtime cannot prepare an isolated HITL scorer workspace."""


def scoring_source_workspace_fingerprint(
    pending: Dict[str, Any],
    cached_score: Optional[Dict[str, Any]],
) -> str:
    """Return the reviewed fingerprint for a fresh or resumed scoring handoff."""
    if isinstance(cached_score, dict) and cached_score.get("status") == "prepared":
        source_fingerprint = str(
            cached_score.get("source_workspace_fingerprint", "")
        ).strip()
        if source_fingerprint:
            return source_fingerprint
    return str(pending.get("workspace_fingerprint", "")).strip()


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


def _git_failure_detail(completed: Any) -> str:
    value = completed.stderr or completed.stdout or "unknown Git error"
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()


def _checkpoint_gitlinks(work_dir: Path, source_sha: str) -> list[tuple[Path, str]]:
    """Return every Gitlink path and commit recorded by ``source_sha``."""
    completed = run_git(
        work_dir,
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        source_sha,
        text=False,
        check=False,
    )
    if completed.returncode != 0:
        raise HitlScoringWorkspaceError(
            "Runtime could not inspect the isolated scorer checkpoint: "
            f"{_git_failure_detail(completed)}"
        )

    gitlinks: list[tuple[Path, str]] = []
    for raw_record in bytes(completed.stdout or b"").split(b"\0"):
        if not raw_record:
            continue
        metadata, separator, raw_path = raw_record.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise HitlScoringWorkspaceError(
                "Runtime received an invalid Git tree record while preparing the isolated scorer."
            )
        mode, object_type, raw_commit = fields
        if mode != b"160000":
            continue
        if object_type != b"commit" or not raw_path:
            raise HitlScoringWorkspaceError(
                "Runtime received an invalid Gitlink while preparing the isolated scorer."
            )

        relative_text = os.fsdecode(raw_path)
        posix_path = PurePosixPath(relative_text)
        if posix_path.is_absolute() or any(part in {"", ".", ".."} for part in posix_path.parts):
            raise HitlScoringWorkspaceError(
                f"Runtime rejected unsafe Gitlink path: {relative_text!r}."
            )
        gitlinks.append((Path(*posix_path.parts), raw_commit.decode("ascii")))
    return gitlinks


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
        gitlinks = _checkpoint_gitlinks(root, source_sha)
    except HitlScoringWorkspaceError as exc:
        return [str(exc)]

    issues: list[str] = []
    for relative, commit_sha in gitlinks:
        try:
            source_repo = _contained_path(
                root,
                relative,
                description="Gitlink source",
            )
        except HitlScoringWorkspaceError as exc:
            issues.append(str(exc))
            continue
        relative_text = relative.as_posix()
        if not source_repo.is_dir():
            issues.append(
                "Checkpointed nested repository "
                f"`{relative_text}` is missing from the workspace."
            )
            continue

        repository_root = run_git(
            source_repo,
            "rev-parse",
            "--show-toplevel",
            check=False,
        )
        if (
            repository_root.returncode != 0
            or Path(str(repository_root.stdout).strip()).resolve() != source_repo
        ):
            issues.append(
                "Checkpointed nested repository "
                f"`{relative_text}` is not available at its recorded Git root."
            )
            continue

        head = run_git(source_repo, "rev-parse", "HEAD", check=False)
        if head.returncode != 0:
            issues.append(
                "Could not inspect HEAD for checkpointed nested repository "
                f"`{relative_text}`: {_git_failure_detail(head)}"
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
                f"`{relative_text}`: {_git_failure_detail(status)}"
            )
        elif bytes(status.stdout or b""):
            issues.append(
                "Checkpointed nested repository "
                f"`{relative_text}` contains staged, modified, or untracked files."
            )
    return issues


def _extract_git_archive(archive_path: Path, destination: Path) -> None:
    """Extract an archive produced by Git after validating its member paths."""
    with tarfile.open(archive_path, mode="r:") as archive:
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
        if hasattr(tarfile, "fully_trusted_filter"):
            archive.extractall(destination, members=members, filter="fully_trusted")
        else:  # Python 3.10 and 3.11 do not expose extraction filters.
            archive.extractall(destination, members=members)


def _materialize_checkpoint_gitlinks(
    *,
    work_dir: Path,
    scorer_dir: Path,
    source_sha: str,
) -> None:
    """Restore exact nested-repository contents omitted by ``git worktree``."""
    for index, (relative, commit_sha) in enumerate(_checkpoint_gitlinks(work_dir, source_sha)):
        source_repo = _contained_path(
            work_dir,
            relative,
            description="Gitlink source",
        )
        destination = _contained_path(
            scorer_dir,
            relative,
            description="Gitlink destination",
        )
        if not source_repo.is_dir():
            raise HitlScoringWorkspaceError(
                "Runtime could not materialize checkpointed nested repository "
                f"{relative.as_posix()}: the source repository is missing."
            )

        repository_root = run_git(
            source_repo,
            "rev-parse",
            "--show-toplevel",
            check=False,
        )
        if (
            repository_root.returncode != 0
            or Path(str(repository_root.stdout).strip()).resolve() != source_repo
        ):
            raise HitlScoringWorkspaceError(
                "Runtime could not materialize checkpointed nested repository "
                f"{relative.as_posix()}: the source path is not its Git root."
            )

        commit_exists = run_git(
            source_repo,
            "cat-file",
            "-e",
            f"{commit_sha}^{{commit}}",
            check=False,
            quiet=True,
        )
        if commit_exists.returncode != 0:
            raise HitlScoringWorkspaceError(
                "Runtime could not materialize checkpointed nested repository "
                f"{relative.as_posix()}: commit {commit_sha} is unavailable."
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
                f"{relative.as_posix()}: {_git_failure_detail(archived)}"
            )
        try:
            _extract_git_archive(archive_path, destination)
        except (OSError, tarfile.TarError) as exc:
            raise HitlScoringWorkspaceError(
                "Runtime could not restore checkpointed nested repository "
                f"{relative.as_posix()}: {exc}"
            ) from exc
        finally:
            archive_path.unlink(missing_ok=True)


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

    temporary_parent = Path(
        tempfile.mkdtemp(
            prefix=".neurico-hitl-scorer-",
            dir=work_dir.parent,
        )
    )
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

        _materialize_checkpoint_gitlinks(
            work_dir=work_dir,
            scorer_dir=scorer_dir,
            source_sha=normalized_sha,
        )

        _prepare_scoring_directory(scorer_dir)
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
