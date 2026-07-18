"""Git-backed snapshots for durable HITL and AutoResearch control state.

Public AutoResearch checkpoints intentionally do not contain hidden runtime
state. This module stores that state as private refs in the same Git object
database, keyed separately from public workspace node SHAs. That keeps public
node identities stable while making HITL rollback state Git-versioned.
"""

from __future__ import annotations

import io
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Iterable, Sequence


class HitlGitStateError(RuntimeError):
    """Raised when a Git-backed HITL state operation cannot complete."""


# The whole HITL state directory rolls back with a failed attempt so a newly
# created private state file cannot leak into the recovered run. Capture and
# restore explicitly exclude live locks, SQLite sidecars, temporary files, and
# generated worker command wrappers; those are process artifacts, not state.
DURABLE_HITL_STATE_PATHS = (
    ".neurico/hitl",
    ".neurico/research_state.json",
)

WHITEBOARD_STATE_PATH = "logs/experiment-autoresearch/whiteboard.json"
AUTORESEARCH_WHITEBOARD_REF = "refs/neurico/autoresearch-whiteboard"
HITL_AUTORESEARCH_WHITEBOARD_STATE_PATH = ".neurico/hitl/whiteboard/whiteboard.json"
HITL_AUTORESEARCH_WHITEBOARD_REF = "refs/neurico/hitl-autoresearch-whiteboard"
AUTORESEARCH_WHITEBOARD_ATTEMPT_TRAILER = "NeuriCo-AutoResearch-Attempt:"
AUTORESEARCH_HITL_ROLLBACK_REF_PREFIX = "refs/neurico/autoresearch-hitl-rollback"


@dataclass(frozen=True)
class HitlGitSnapshot:
    """A private Git ref containing one exact durable HITL state boundary."""

    ref: str
    commit_sha: str
    paths: tuple[str, ...]


class HitlGitStateStore:
    """Store and restore durable HITL control state through private Git refs."""

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir).resolve()

    def create_rollback_snapshot(self) -> HitlGitSnapshot:
        ref = f"refs/neurico/hitl-rollback/{uuid.uuid4().hex}"
        return self._capture(
            ref=ref,
            paths=DURABLE_HITL_STATE_PATHS,
            message="NeuriCo HITL rollback snapshot",
            retain_history=False,
        )

    def begin_autoresearch_hitl_attempt(self, attempt_id: str) -> HitlGitSnapshot:
        """Create the private Git rollback boundary for one HITL attempt."""
        ref = self._autoresearch_hitl_rollback_ref(attempt_id)
        if self._optional_rev_parse(ref):
            raise HitlGitStateError(
                "An HITL rollback boundary already exists for this AutoResearch attempt."
            )
        return self._capture(
            ref=ref,
            paths=DURABLE_HITL_STATE_PATHS,
            message=f"NeuriCo HITL AutoResearch attempt start: {attempt_id}",
            retain_history=False,
        )

    def restore_autoresearch_hitl_attempt(self, attempt_id: str) -> None:
        """Restore the private HITL state captured before an AutoResearch attempt."""
        self.restore(self._autoresearch_hitl_attempt_snapshot(attempt_id))

    def discard_autoresearch_hitl_attempt(self, attempt_id: str) -> None:
        """Remove a completed AutoResearch attempt's private rollback boundary."""
        self.discard(self._autoresearch_hitl_attempt_snapshot(attempt_id))

    def has_autoresearch_hitl_attempt_boundary(self, attempt_id: str) -> bool:
        """Return whether the attempt's deterministic private rollback ref exists."""
        return (
            self._optional_rev_parse(self._autoresearch_hitl_rollback_ref(attempt_id)) is not None
        )

    def record_autoresearch_whiteboard(self) -> HitlGitSnapshot:
        """Append the live AutoResearch whiteboard to its private Git history."""
        return self._record_whiteboard_version(
            path=WHITEBOARD_STATE_PATH,
            ref=AUTORESEARCH_WHITEBOARD_REF,
            message="NeuriCo AutoResearch whiteboard",
        )

    def begin_autoresearch_whiteboard_attempt(self, attempt_id: str) -> HitlGitSnapshot:
        """Record the rollback boundary for one active AutoResearch attempt."""
        return self._begin_whiteboard_attempt(
            attempt_id,
            path=WHITEBOARD_STATE_PATH,
            ref=AUTORESEARCH_WHITEBOARD_REF,
            label="NeuriCo AutoResearch whiteboard",
        )

    def rollback_autoresearch_whiteboard_attempt(self, attempt_id: str) -> None:
        """Undo only a failed attempt's whiteboard changes from Git history.

        Rejected scored attempts deliberately do not call this method: their
        whiteboard learning is valid cross-attempt state. This method is the
        transaction rollback reserved for failed or interrupted attempts.
        """
        self._rollback_whiteboard_attempt(
            attempt_id,
            path=WHITEBOARD_STATE_PATH,
            ref=AUTORESEARCH_WHITEBOARD_REF,
        )

    def has_autoresearch_whiteboard_attempt_boundary(self, attempt_id: str) -> bool:
        """Return whether the private whiteboard history can roll back an attempt."""
        return self._has_whiteboard_attempt_boundary(
            attempt_id,
            ref=AUTORESEARCH_WHITEBOARD_REF,
        )

    def record_hitl_autoresearch_whiteboard(self) -> HitlGitSnapshot:
        """Append the hidden HITL AutoResearch whiteboard to private Git history."""
        return self._record_whiteboard_version(
            path=HITL_AUTORESEARCH_WHITEBOARD_STATE_PATH,
            ref=HITL_AUTORESEARCH_WHITEBOARD_REF,
            message="NeuriCo HITL AutoResearch whiteboard",
        )

    def begin_hitl_autoresearch_whiteboard_attempt(self, attempt_id: str) -> HitlGitSnapshot:
        """Record the hidden-whiteboard rollback boundary for one HITL attempt."""
        return self._begin_whiteboard_attempt(
            attempt_id,
            path=HITL_AUTORESEARCH_WHITEBOARD_STATE_PATH,
            ref=HITL_AUTORESEARCH_WHITEBOARD_REF,
            label="NeuriCo HITL AutoResearch whiteboard",
        )

    def rollback_hitl_autoresearch_whiteboard_attempt(self, attempt_id: str) -> None:
        """Remove hidden whiteboard changes from a failed HITL attempt."""
        self._rollback_whiteboard_attempt(
            attempt_id,
            path=HITL_AUTORESEARCH_WHITEBOARD_STATE_PATH,
            ref=HITL_AUTORESEARCH_WHITEBOARD_REF,
        )

    def has_hitl_autoresearch_whiteboard_attempt_boundary(self, attempt_id: str) -> bool:
        """Return whether the hidden whiteboard has a rollback boundary."""
        return self._has_whiteboard_attempt_boundary(
            attempt_id,
            ref=HITL_AUTORESEARCH_WHITEBOARD_REF,
        )

    def restore(self, snapshot: HitlGitSnapshot | str) -> None:
        ref = snapshot.ref if isinstance(snapshot, HitlGitSnapshot) else str(snapshot)
        commit = self._rev_parse(ref)
        if isinstance(snapshot, HitlGitSnapshot) and commit != snapshot.commit_sha:
            raise HitlGitStateError("HITL Git snapshot ref no longer matches its recorded commit.")
        paths = (
            snapshot.paths if isinstance(snapshot, HitlGitSnapshot) else DURABLE_HITL_STATE_PATHS
        )
        self._restore_commit(commit, paths)

    def discard(self, snapshot: HitlGitSnapshot | str) -> None:
        ref = snapshot.ref if isinstance(snapshot, HitlGitSnapshot) else str(snapshot)
        self._run_git("update-ref", "-d", ref)

    def has_snapshot(self, ref: str) -> bool:
        try:
            self._rev_parse(str(ref))
        except HitlGitStateError:
            return False
        return True

    def has_recorded_snapshot(self, snapshot: HitlGitSnapshot) -> bool:
        try:
            return self._rev_parse(snapshot.ref) == snapshot.commit_sha
        except HitlGitStateError:
            return False

    def _capture(
        self,
        *,
        ref: str,
        paths: Sequence[str],
        message: str,
        retain_history: bool,
    ) -> HitlGitSnapshot:
        self._ensure_repository()
        normalized_paths = self._normalize_paths(paths)
        present_paths = self._present_snapshot_paths(normalized_paths)
        snapshot_guard = self._manager_conversation_snapshot_guard(normalized_paths)
        with snapshot_guard:
            with tempfile.TemporaryDirectory(prefix="neurico-hitl-git-index-") as temp_dir:
                index_path = Path(temp_dir) / "index"
                env = {"GIT_INDEX_FILE": str(index_path)}
                self._run_git("read-tree", "--empty", env=env)
                if present_paths:
                    self._run_git("add", "-f", "--", *present_paths, env=env)
                tree = self._run_git("write-tree", env=env).strip()

            commit_args = ["commit-tree", tree, "-m", message]
            if retain_history:
                previous = self._optional_rev_parse(ref)
                if previous:
                    commit_args.extend(["-p", previous])
            commit_sha = self._run_git(*commit_args).strip()
            self._run_git("update-ref", ref, commit_sha)
        return HitlGitSnapshot(ref=ref, commit_sha=commit_sha, paths=tuple(normalized_paths))

    def _manager_conversation_snapshot_guard(self, paths: Sequence[str]):
        hitl_dir = self.work_dir / ".neurico" / "hitl"
        if ".neurico/hitl" not in paths or not (hitl_dir / "manager" / "history.sqlite").exists():
            return nullcontext()
        from core.hitl_manager_history import HitlManagerHistory

        return HitlManagerHistory.snapshot_lock(hitl_dir / "manager")

    def _restore_commit(self, commit: str, paths: Sequence[str]) -> None:
        normalized_paths = self._normalize_paths(paths)
        for relative_path in normalized_paths:
            target = self.work_dir / relative_path
            if relative_path == ".neurico/hitl" and target.is_dir():
                self._clear_durable_hitl_directory(target)
            elif target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()

        if not self._run_git("ls-tree", "-r", "--name-only", commit).strip():
            return
        # The private commit contains only present controlled paths. Archiving
        # the whole commit lets an absent path mean "remove the current copy"
        # instead of turning a valid earlier snapshot into a pathspec error.
        archive = self._run_git_bytes("archive", "--format=tar", commit)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            for member in tar.getmembers():
                relative = PurePosixPath(member.name)
                if member.isdir() or not member.isfile():
                    continue
                if relative.is_absolute() or ".." in relative.parts:
                    raise HitlGitStateError("Git HITL snapshot contains an unsafe path.")
                destination = (self.work_dir / Path(*relative.parts)).resolve()
                try:
                    destination.relative_to(self.work_dir)
                except ValueError as exc:
                    raise HitlGitStateError("Git HITL snapshot escapes the workspace.") from exc
                source = tar.extractfile(member)
                if source is None:
                    raise HitlGitStateError("Git HITL snapshot contains an unreadable file.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as handle:
                    shutil.copyfileobj(source, handle)

    def _present_snapshot_paths(self, paths: Sequence[str]) -> list[str]:
        """Expand durable paths while omitting ephemeral HITL process files."""
        present: list[str] = []
        for relative_path in paths:
            target = self.work_dir / relative_path
            if relative_path == ".neurico/hitl" and target.is_dir():
                for path in target.rglob("*"):
                    if not path.is_file():
                        continue
                    rel = path.relative_to(self.work_dir).as_posix()
                    if not self._is_ephemeral_hitl_path(rel):
                        present.append(rel)
            elif target.exists():
                present.append(relative_path)
        return present

    @staticmethod
    def _is_ephemeral_hitl_path(relative_path: str) -> bool:
        path = PurePosixPath(relative_path)
        parts = path.parts
        root = (".neurico", "hitl")
        if parts[: len(root)] != root:
            return False
        suffix = parts[len(root) :]
        if not suffix:
            return False
        name = suffix[-1]
        return (
            suffix[0] == "bin"
            or name.endswith(".lock")
            or name.endswith(".tmp")
            or name in {"history.sqlite-wal", "history.sqlite-shm"}
        )

    def _clear_durable_hitl_directory(self, hitl_dir: Path) -> None:
        """Remove rollback-controlled files while leaving live lock/wrapper paths alone."""
        for path in sorted(hitl_dir.rglob("*"), reverse=True):
            relative = path.relative_to(self.work_dir).as_posix()
            if path.name in {
                "history.sqlite-wal",
                "history.sqlite-shm",
            } or path.name.endswith(".tmp"):
                if path.is_file():
                    path.unlink()
                continue
            if self._is_ephemeral_hitl_path(relative):
                continue
            if path.is_file():
                path.unlink()
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()

    def _ensure_repository(self) -> None:
        self._run_git("rev-parse", "--git-dir")

    def _optional_rev_parse(self, ref: str) -> str | None:
        process = subprocess.run(
            ["git", "-C", str(self.work_dir), "rev-parse", "--verify", ref],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if process.returncode:
            return None
        return process.stdout.strip()

    def _record_whiteboard_version(
        self,
        *,
        path: str,
        ref: str,
        message: str,
    ) -> HitlGitSnapshot:
        return self._capture(
            ref=ref,
            paths=(path,),
            message=message,
            retain_history=True,
        )

    def _begin_whiteboard_attempt(
        self,
        attempt_id: str,
        *,
        path: str,
        ref: str,
        label: str,
    ) -> HitlGitSnapshot:
        safe_attempt_id = self._require_attempt_id(attempt_id)
        return self._capture(
            ref=ref,
            paths=(path,),
            message=(
                f"{label} attempt start\n\n"
                f"{AUTORESEARCH_WHITEBOARD_ATTEMPT_TRAILER} {safe_attempt_id}"
            ),
            retain_history=True,
        )

    def _rollback_whiteboard_attempt(
        self,
        attempt_id: str,
        *,
        path: str,
        ref: str,
    ) -> None:
        boundary = self._find_whiteboard_attempt_boundary(attempt_id, ref=ref)
        self._restore_commit(boundary, (path,))
        self._run_git("update-ref", ref, boundary)

    def _has_whiteboard_attempt_boundary(self, attempt_id: str, *, ref: str) -> bool:
        try:
            self._find_whiteboard_attempt_boundary(attempt_id, ref=ref)
        except HitlGitStateError:
            return False
        return True

    def _find_whiteboard_attempt_boundary(self, attempt_id: str, *, ref: str) -> str:
        safe_attempt_id = self._require_attempt_id(attempt_id)
        history = self._run_git("rev-list", ref).splitlines()
        trailer = f"{AUTORESEARCH_WHITEBOARD_ATTEMPT_TRAILER} {safe_attempt_id}"
        for commit_sha in history:
            message = self._run_git("show", "-s", "--format=%B", commit_sha)
            if trailer in message.splitlines():
                return commit_sha
        raise HitlGitStateError(
            "Git whiteboard history has no rollback boundary for the active AutoResearch attempt."
        )

    def _autoresearch_hitl_attempt_snapshot(self, attempt_id: str) -> HitlGitSnapshot:
        ref = self._autoresearch_hitl_rollback_ref(attempt_id)
        return HitlGitSnapshot(
            ref=ref,
            commit_sha=self._rev_parse(ref),
            paths=DURABLE_HITL_STATE_PATHS,
        )

    def _autoresearch_hitl_rollback_ref(self, attempt_id: str) -> str:
        safe_attempt_id = self._require_attempt_id(attempt_id)
        return f"{AUTORESEARCH_HITL_ROLLBACK_REF_PREFIX}/{safe_attempt_id}"

    def _rev_parse(self, ref: str) -> str:
        return self._run_git("rev-parse", "--verify", ref).strip()

    def _run_git(self, *args: str, env: dict[str, str] | None = None) -> str:
        process = subprocess.run(
            ["git", "-C", str(self.work_dir), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, **(env or {})},
            check=False,
        )
        if process.returncode:
            raise HitlGitStateError("Git could not complete the HITL state operation.")
        return process.stdout

    def _run_git_bytes(self, *args: str) -> bytes:
        process = subprocess.run(
            ["git", "-C", str(self.work_dir), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if process.returncode:
            raise HitlGitStateError("Git could not read the HITL state snapshot.")
        return process.stdout

    @staticmethod
    def _require_attempt_id(value: str) -> str:
        attempt_id = str(value).strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/attempt_\d+", attempt_id):
            raise HitlGitStateError("Invalid AutoResearch attempt id.")
        return attempt_id

    @staticmethod
    def _normalize_paths(paths: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        for value in paths:
            path = PurePosixPath(str(value))
            if path.is_absolute() or not path.parts or ".." in path.parts:
                raise HitlGitStateError("Invalid HITL state path.")
            normalized.append(path.as_posix())
        return normalized

    @staticmethod
    def rollback_paths() -> tuple[str, ...]:
        """Return the fixed durable path boundary for AutoResearch rollback."""
        return DURABLE_HITL_STATE_PATHS
