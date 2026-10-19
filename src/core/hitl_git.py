"""Shared Git subprocess plumbing for runtime-owned HITL operations."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Mapping
import uuid


@dataclass(frozen=True)
class GitCommandFailure:
    argv: tuple[str, ...]
    returncode: int
    stdout: str | bytes
    stderr: str | bytes


class HitlGitCommandError(RuntimeError):
    def __init__(self, failure: GitCommandFailure):
        detail_value = failure.stderr or failure.stdout or "unknown Git error"
        detail = (
            detail_value.decode("utf-8", errors="replace")
            if isinstance(detail_value, bytes)
            else str(detail_value)
        ).strip()
        super().__init__(f"Git command failed ({' '.join(failure.argv)}): {detail}")
        self.failure = failure


class HitlGitlinkError(RuntimeError):
    """Raised when a checkpointed nested repository cannot be used safely."""


@dataclass(frozen=True)
class CheckpointGitlink:
    """One nested repository recorded by a parent workspace checkpoint."""

    relative_path: Path
    commit_sha: str


_OBJECT_ID = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


def run_git(
    work_dir: Path,
    *args: str,
    env: Mapping[str, str] | None = None,
    text: bool = True,
    check: bool = True,
    quiet: bool = False,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    argv = ("git", "-C", str(Path(work_dir)), *map(str, args))
    completed = subprocess.run(
        list(argv),
        stdout=subprocess.DEVNULL if quiet else subprocess.PIPE,
        stderr=subprocess.DEVNULL if quiet else subprocess.PIPE,
        text=text,
        encoding="utf-8" if text else None,
        env={**os.environ, **dict(env or {})},
        check=False,
    )
    if check and completed.returncode:
        raise HitlGitCommandError(
            GitCommandFailure(
                argv=argv,
                returncode=completed.returncode,
                stdout=completed.stdout or ("" if text else b""),
                stderr=completed.stderr or ("" if text else b""),
            )
        )
    return completed


def git_stdout(work_dir: Path, *args: str, env: Mapping[str, str] | None = None) -> str:
    completed = run_git(work_dir, *args, env=env)
    return str(completed.stdout)


def git_stdout_bytes(work_dir: Path, *args: str) -> bytes:
    completed = run_git(work_dir, *args, text=False)
    return bytes(completed.stdout)


def delete_git_ref(work_dir: Path, ref_name: str, *, strict: bool) -> None:
    ref = str(ref_name).strip()
    if not ref:
        return
    removed = run_git(work_dir, "update-ref", "-d", ref, check=False)
    if removed.returncode == 0:
        return
    exists = run_git(
        work_dir,
        "rev-parse",
        "--verify",
        "--quiet",
        ref,
        check=False,
        quiet=True,
    )
    if exists.returncode == 1 or not strict:
        return
    if exists.returncode != 0:
        raise RuntimeError("Runtime could not verify its temporary Git ref.")
    raise HitlGitCommandError(
        GitCommandFailure(
            argv=("git", "-C", str(Path(work_dir)), "update-ref", "-d", ref),
            returncode=removed.returncode,
            stdout=removed.stdout or "",
            stderr=removed.stderr or "",
        )
    )


def git_failure_detail(completed: subprocess.CompletedProcess) -> str:
    """Return the useful diagnostic from a failed Git command."""
    value = completed.stderr or completed.stdout or "unknown Git error"
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()


def checkpoint_gitlinks(
    work_dir: Path,
    source_sha: str,
) -> list[CheckpointGitlink]:
    """Return every safe Gitlink path and commit recorded by a checkpoint."""
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
        raise HitlGitlinkError(
            "Runtime could not inspect checkpointed nested repositories: "
            f"{git_failure_detail(completed)}"
        )

    gitlinks: list[CheckpointGitlink] = []
    for raw_record in bytes(completed.stdout or b"").split(b"\0"):
        if not raw_record:
            continue
        metadata, separator, raw_path = raw_record.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise HitlGitlinkError(
                "Runtime received an invalid Git tree record while inspecting "
                "checkpointed nested repositories."
            )
        mode, object_type, raw_commit = fields
        if mode != b"160000":
            continue
        if object_type != b"commit" or not raw_path:
            raise HitlGitlinkError(
                "Runtime received an invalid checkpointed nested repository record."
            )

        relative_text = os.fsdecode(raw_path)
        posix_path = PurePosixPath(relative_text)
        if posix_path.is_absolute() or any(
            part in {"", ".", ".."} for part in posix_path.parts
        ):
            raise HitlGitlinkError(
                f"Runtime rejected unsafe Gitlink path: {relative_text!r}."
            )
        try:
            commit_sha = raw_commit.decode("ascii")
        except UnicodeDecodeError as exc:
            raise HitlGitlinkError(
                "Runtime received an invalid checkpointed nested repository commit."
            ) from exc
        gitlinks.append(
            CheckpointGitlink(
                relative_path=Path(*posix_path.parts),
                commit_sha=commit_sha,
            )
        )
    return gitlinks


def resolve_checkpoint_gitlinks(
    work_dir: Path,
    source_sha: str,
) -> list[tuple[CheckpointGitlink, Path]]:
    """Resolve checkpoint Gitlinks to local repositories containing their commits."""
    return resolve_gitlink_repositories(
        work_dir,
        checkpoint_gitlinks(work_dir, source_sha),
    )


def resolve_gitlink_repositories(
    work_dir: Path,
    gitlinks: list[CheckpointGitlink],
) -> list[tuple[CheckpointGitlink, Path]]:
    """Resolve known Gitlinks to local repositories containing their commits."""
    workspace = Path(work_dir).resolve()
    resolved: list[tuple[CheckpointGitlink, Path]] = []
    for gitlink in gitlinks:
        repository = (workspace / gitlink.relative_path).resolve()
        try:
            repository.relative_to(workspace)
        except ValueError as exc:
            raise HitlGitlinkError(
                "Runtime rejected checkpointed nested repository outside the workspace: "
                f"{gitlink.relative_path.as_posix()}."
            ) from exc
        relative_text = gitlink.relative_path.as_posix()
        if not repository.is_dir():
            raise HitlGitlinkError(
                f"Checkpointed nested repository `{relative_text}` is missing from the workspace."
            )

        repository_root = run_git(
            repository,
            "rev-parse",
            "--show-toplevel",
            check=False,
        )
        if (
            repository_root.returncode != 0
            or Path(str(repository_root.stdout).strip()).resolve() != repository
        ):
            raise HitlGitlinkError(
                "Checkpointed nested repository "
                f"`{relative_text}` is not available at its recorded Git root."
            )

        commit_exists = run_git(
            repository,
            "cat-file",
            "-e",
            f"{gitlink.commit_sha}^{{commit}}",
            check=False,
            quiet=True,
        )
        if commit_exists.returncode != 0:
            raise HitlGitlinkError(
                "Checkpointed nested repository "
                f"`{relative_text}` does not contain recorded commit {gitlink.commit_sha}."
            )
        resolved.append((gitlink, repository))
    return resolved


def verify_git_commit_bundle(
    work_dir: Path,
    bundle_path: Path,
    commit_sha: str,
) -> None:
    """Require one readable bundle advertising ``commit_sha``."""
    bundle = Path(bundle_path)
    if bundle.is_symlink() or not bundle.is_file():
        raise HitlGitlinkError(f"Checkpointed nested-repository bundle is missing: {bundle}")
    bundle = bundle.resolve()

    verified = run_git(work_dir, "bundle", "verify", str(bundle), check=False)
    if verified.returncode != 0:
        raise HitlGitlinkError(
            "Checkpointed nested-repository bundle is invalid: " f"{git_failure_detail(verified)}"
        )
    listed = run_git(work_dir, "bundle", "list-heads", str(bundle), check=False)
    if listed.returncode != 0:
        raise HitlGitlinkError(
            "Runtime could not inspect checkpointed nested-repository bundle: "
            f"{git_failure_detail(listed)}"
        )
    advertised = {
        line.split(maxsplit=1)[0] for line in str(listed.stdout or "").splitlines() if line.strip()
    }
    if str(commit_sha).strip() not in advertised:
        raise HitlGitlinkError(
            "Checkpointed nested-repository bundle does not advertise its recorded commit."
        )


def _git_shallow_path(repository: Path) -> Path:
    resolved = run_git(repository, "rev-parse", "--git-path", "shallow", check=False)
    if resolved.returncode != 0:
        raise HitlGitlinkError(
            "Runtime could not locate nested-repository shallow metadata: "
            f"{git_failure_detail(resolved)}"
        )
    value = Path(str(resolved.stdout).strip())
    return value if value.is_absolute() else Path(repository).resolve() / value


def git_commit_shallow_boundaries(
    repository: Path,
    commit_sha: str,
) -> tuple[str, ...]:
    """Return shallow boundaries reachable from one nested commit."""
    repo = Path(repository).resolve()
    shallow = run_git(repo, "rev-parse", "--is-shallow-repository", check=False)
    if shallow.returncode != 0:
        raise HitlGitlinkError(
            "Runtime could not inspect nested-repository shallow state: "
            f"{git_failure_detail(shallow)}"
        )
    if str(shallow.stdout).strip() != "true":
        return ()

    path = _git_shallow_path(repo)
    try:
        candidates = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise HitlGitlinkError(
            "Runtime could not read nested-repository shallow metadata."
        ) from exc

    boundaries: list[str] = []
    for raw in candidates:
        boundary = raw.strip()
        if not _OBJECT_ID.fullmatch(boundary):
            raise HitlGitlinkError(
                "Nested repository contains invalid shallow-boundary metadata."
            )
        ancestor = run_git(
            repo,
            "merge-base",
            "--is-ancestor",
            boundary,
            commit_sha,
            check=False,
            quiet=True,
        )
        if ancestor.returncode == 0:
            boundaries.append(boundary)
        elif ancestor.returncode != 1:
            raise HitlGitlinkError(
                "Runtime could not resolve nested-repository shallow boundaries."
            )
    return tuple(sorted(set(boundaries)))


def _normalize_shallow_boundaries(values: tuple[str, ...]) -> tuple[str, ...]:
    boundaries = tuple(str(value).strip() for value in values)
    if any(not _OBJECT_ID.fullmatch(value) for value in boundaries):
        raise HitlGitlinkError(
            "Checkpointed nested repository has invalid shallow-boundary metadata."
        )
    if len(set(boundaries)) != len(boundaries):
        raise HitlGitlinkError(
            "Checkpointed nested repository has duplicate shallow-boundary metadata."
        )
    return tuple(sorted(boundaries))


def _write_git_shallow(path: Path, content: bytes | None) -> None:
    if content is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def create_git_commit_bundle(
    repository: Path,
    *,
    commit_sha: str,
    destination: Path,
) -> tuple[str, ...]:
    """Create one bundle and return shallow boundaries needed to import it."""
    repo = Path(repository).resolve()
    bundle = Path(destination).resolve()
    bundle.parent.mkdir(parents=True, exist_ok=True)
    shallow_boundaries = git_commit_shallow_boundaries(repo, commit_sha)
    temporary_ref = f"refs/neurico/hitl/bundles/{uuid.uuid4().hex}"
    retained = run_git(repo, "update-ref", temporary_ref, commit_sha, check=False)
    if retained.returncode != 0:
        raise HitlGitlinkError(
            "Runtime could not retain a nested commit for bundling: "
            f"{git_failure_detail(retained)}"
        )
    try:
        created = run_git(
            repo,
            "bundle",
            "create",
            str(bundle),
            temporary_ref,
            check=False,
        )
        if created.returncode != 0:
            raise HitlGitlinkError(
                "Runtime could not bundle a checkpointed nested repository: "
                f"{git_failure_detail(created)}"
            )
        verify_git_commit_bundle(repo, bundle, commit_sha)
    finally:
        run_git(repo, "update-ref", "-d", temporary_ref, check=False, quiet=True)
    return shallow_boundaries


def prepare_git_commit_bundle_repository(
    repository: Path,
    *,
    bundle_path: Path,
    commit_sha: str,
    shallow_boundaries: tuple[str, ...] = (),
) -> None:
    """Import a bundle into a new private repository before changing live state.

    The caller owns the repository's temporary directory and its cleanup.
    Starting empty ensures Git consumes the bundle even if the live repository
    already contains the requested commit.
    """
    repo = Path(repository).resolve()
    repo.mkdir(parents=True)
    initialized = run_git(repo, "init", "--bare", "--quiet", check=False)
    if initialized.returncode != 0:
        raise HitlGitlinkError(
            "Runtime could not initialize a bundled nested repository: "
            f"{git_failure_detail(initialized)}"
        )
    fetch_git_commit_bundle(
        repo,
        bundle_path=bundle_path,
        commit_sha=commit_sha,
        shallow_boundaries=shallow_boundaries,
    )


def fetch_git_commit_bundle(
    repository: Path,
    *,
    bundle_path: Path,
    commit_sha: str,
    shallow_boundaries: tuple[str, ...] = (),
) -> None:
    """Import one bundled commit with any required shallow boundaries."""
    repo = Path(repository).resolve()
    bundle = Path(bundle_path).resolve()
    verify_git_commit_bundle(repo, bundle, commit_sha)
    fetch_git_commit(
        repo,
        source=bundle,
        commit_sha=commit_sha,
        shallow_boundaries=shallow_boundaries,
    )


def fetch_git_commit(
    repository: Path,
    *,
    source: Path,
    commit_sha: str,
    shallow_boundaries: tuple[str, ...] = (),
) -> None:
    """Import one commit from a bundle or a prepared private repository."""
    repo = Path(repository).resolve()
    source = Path(source).resolve()
    boundaries = _normalize_shallow_boundaries(shallow_boundaries)
    fetched = run_git(
        repo,
        "fetch",
        "--no-tags",
        "--update-shallow",
        str(source),
        commit_sha,
        check=False,
    )
    shallow_path: Path | None = None
    previous_shallow: bytes | None = None
    changed_shallow = False
    if fetched.returncode != 0 and boundaries:
        shallow_path = _git_shallow_path(repo)
        try:
            previous_shallow = shallow_path.read_bytes() if shallow_path.exists() else None
            existing = set(
                previous_shallow.decode("ascii").splitlines()
                if previous_shallow is not None
                else ()
            )
            _write_git_shallow(
                shallow_path,
                ("\n".join(sorted(existing | set(boundaries))) + "\n").encode("ascii"),
            )
        except (OSError, UnicodeError) as exc:
            raise HitlGitlinkError(
                "Runtime could not update destination shallow metadata."
            ) from exc
        changed_shallow = True
        fetched = run_git(
            repo,
            "fetch",
            "--no-tags",
            "--update-shallow",
            str(source),
            commit_sha,
            check=False,
        )

    try:
        if fetched.returncode != 0:
            raise HitlGitlinkError(
                "Runtime could not fetch a checkpointed nested-repository commit: "
                f"{git_failure_detail(fetched)}"
            )
        exists = run_git(
            repo,
            "cat-file",
            "-e",
            f"{commit_sha}^{{commit}}",
            check=False,
            quiet=True,
        )
        if exists.returncode != 0:
            raise HitlGitlinkError(
                "Fetched nested repository is missing its recorded commit."
            )
    except Exception:
        if changed_shallow and shallow_path is not None:
            try:
                _write_git_shallow(shallow_path, previous_shallow)
            except OSError as exc:
                raise HitlGitlinkError(
                    "Runtime could not restore destination shallow metadata after a "
                    "failed commit import."
                ) from exc
        raise
