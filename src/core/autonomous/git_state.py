"""Git-backed snapshots for durable HITL and AutoResearch control state.

Public AutoResearch checkpoints intentionally do not contain hidden runtime
state. This module stores that state as private refs in the same Git object
database, keyed separately from public workspace node SHAs. That keeps public
node identities stable while making HITL rollback state Git-versioned.
"""

from __future__ import annotations

import io
import re
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Iterable, Sequence

from core.autonomous.git import GitCommandError, run_git
from core.autonomous.paths import (
    AUTONOMOUS_RELATIVE_ROOT,
    AUTONOMOUS_WHITEBOARD_RELATIVE_PATH,
    hitl_state_dir,
)


class GitStateError(RuntimeError):
    """Raised when a Git-backed HITL state operation cannot complete."""


# The whole HITL state directory rolls back with a failed attempt so a newly
# created private state file cannot leak into the recovered run. Capture and
# restore explicitly exclude live locks, SQLite sidecars, temporary files, and
# generated worker command wrappers; those are process artifacts, not state.
DURABLE_AUTONOMOUS_STATE_PATHS = (
    AUTONOMOUS_RELATIVE_ROOT.as_posix(),
    ".neurico/research_state.json",
)

AUTONOMOUS_AUTORESEARCH_WHITEBOARD_STATE_PATH = AUTONOMOUS_WHITEBOARD_RELATIVE_PATH.as_posix()
AUTONOMOUS_AUTORESEARCH_WHITEBOARD_REF = "refs/neurico/autonomous-autoresearch-whiteboard"
AUTORESEARCH_WHITEBOARD_ATTEMPT_TRAILER = "NeuriCo-AutoResearch-Attempt:"
AUTORESEARCH_AUTONOMOUS_ROLLBACK_REF_PREFIX = "refs/neurico/autoresearch-autonomous-rollback"


@dataclass(frozen=True)
class GitSnapshot:
    """A private Git ref containing one exact durable HITL state boundary."""

    ref: str
    commit_sha: str
    paths: tuple[str, ...]


class GitStateStore:
    """Store and restore durable HITL control state through private Git refs."""

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir).resolve()

    def create_rollback_snapshot(self) -> GitSnapshot:
        ref = f"refs/neurico/autonomous-rollback/{uuid.uuid4().hex}"
        return self._capture(
            ref=ref,
            paths=DURABLE_AUTONOMOUS_STATE_PATHS,
            message="NeuriCo HITL rollback snapshot",
            retain_history=False,
        )

    def begin_autoresearch_hitl_attempt(self, attempt_id: str) -> GitSnapshot:
        """Create the private Git rollback boundary for one HITL attempt."""
        ref = self._autoresearch_hitl_rollback_ref(attempt_id)
        if self._optional_rev_parse(ref):
            raise GitStateError(
                "An HITL rollback boundary already exists for this AutoResearch attempt."
            )
        return self._capture(
            ref=ref,
            paths=DURABLE_AUTONOMOUS_STATE_PATHS,
            message=f"NeuriCo HITL AutoResearch attempt start: {attempt_id}",
            retain_history=False,
        )

    def restore_autoresearch_hitl_attempt(self, attempt_id: str) -> None:
        """Restore the private HITL state captured before an AutoResearch attempt."""
        self.restore(self._autoresearch_hitl_attempt_snapshot(attempt_id))

    def discard_autoresearch_hitl_attempt(self, attempt_id: str) -> None:
        """Remove a completed AutoResearch attempt's private rollback boundary."""
        ref = self._autoresearch_hitl_rollback_ref(attempt_id)
        if not self._ref_exists(ref):
            return
        self.discard(ref)

    def has_autoresearch_hitl_attempt_boundary(self, attempt_id: str) -> bool:
        """Return whether the attempt's deterministic private rollback ref exists."""
        return (
            self._optional_rev_parse(self._autoresearch_hitl_rollback_ref(attempt_id)) is not None
        )

    def record_hitl_autoresearch_whiteboard(self) -> GitSnapshot:
        """Append the hidden HITL AutoResearch whiteboard to private Git history."""
        return self._record_whiteboard_version(
            path=AUTONOMOUS_AUTORESEARCH_WHITEBOARD_STATE_PATH,
            ref=AUTONOMOUS_AUTORESEARCH_WHITEBOARD_REF,
            message="NeuriCo HITL AutoResearch whiteboard",
        )

    def begin_hitl_autoresearch_whiteboard_attempt(self, attempt_id: str) -> GitSnapshot:
        """Record the hidden-whiteboard rollback boundary for one HITL attempt."""
        return self._begin_whiteboard_attempt(
            attempt_id,
            path=AUTONOMOUS_AUTORESEARCH_WHITEBOARD_STATE_PATH,
            ref=AUTONOMOUS_AUTORESEARCH_WHITEBOARD_REF,
            label="NeuriCo HITL AutoResearch whiteboard",
        )

    def rollback_hitl_autoresearch_whiteboard_attempt(self, attempt_id: str) -> None:
        """Remove hidden whiteboard changes from a failed HITL attempt."""
        self._rollback_whiteboard_attempt(
            attempt_id,
            path=AUTONOMOUS_AUTORESEARCH_WHITEBOARD_STATE_PATH,
            ref=AUTONOMOUS_AUTORESEARCH_WHITEBOARD_REF,
        )

    def has_hitl_autoresearch_whiteboard_attempt_boundary(self, attempt_id: str) -> bool:
        """Return whether the hidden whiteboard has a rollback boundary."""
        return self._has_whiteboard_attempt_boundary(
            attempt_id,
            ref=AUTONOMOUS_AUTORESEARCH_WHITEBOARD_REF,
        )

    def restore(self, snapshot: GitSnapshot | str) -> None:
        ref = snapshot.ref if isinstance(snapshot, GitSnapshot) else str(snapshot)
        commit = self._rev_parse(ref)
        if isinstance(snapshot, GitSnapshot) and commit != snapshot.commit_sha:
            raise GitStateError("HITL Git snapshot ref no longer matches its recorded commit.")
        paths = (
            snapshot.paths if isinstance(snapshot, GitSnapshot) else DURABLE_AUTONOMOUS_STATE_PATHS
        )
        self._restore_commit(commit, paths)

    def discard(self, snapshot: GitSnapshot | str) -> None:
        ref = snapshot.ref if isinstance(snapshot, GitSnapshot) else str(snapshot)
        self._run_git("update-ref", "-d", ref)

    def has_snapshot(self, ref: str) -> bool:
        try:
            self._rev_parse(str(ref))
        except GitStateError:
            return False
        return True

    def has_recorded_snapshot(self, snapshot: GitSnapshot) -> bool:
        try:
            return self._rev_parse(snapshot.ref) == snapshot.commit_sha
        except GitStateError:
            return False

    def _capture(
        self,
        *,
        ref: str,
        paths: Sequence[str],
        message: str,
        retain_history: bool,
    ) -> GitSnapshot:
        self._ensure_repository()
        normalized_paths = self._normalize_paths(paths)
        present_paths = self._present_snapshot_paths(normalized_paths)
        snapshot_guard = self._manager_conversation_snapshot_guard(normalized_paths)
        with snapshot_guard:
            with tempfile.TemporaryDirectory(prefix="neurico-autonomous-git-index-") as temp_dir:
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
        return GitSnapshot(ref=ref, commit_sha=commit_sha, paths=tuple(normalized_paths))

    def _manager_conversation_snapshot_guard(self, paths: Sequence[str]):
        hitl_dir = hitl_state_dir(self.work_dir)
        if AUTONOMOUS_RELATIVE_ROOT.as_posix() not in paths or not (
            hitl_dir / "manager" / "history.sqlite"
        ).exists():
            return nullcontext()
        from core.autonomous.manager_history import ManagerHistory

        return ManagerHistory.snapshot_lock(hitl_dir / "manager")

    def _restore_commit(self, commit: str, paths: Sequence[str]) -> None:
        normalized_paths = self._normalize_paths(paths)
        for relative_path in normalized_paths:
            target = self.work_dir / relative_path
            if relative_path == AUTONOMOUS_RELATIVE_ROOT.as_posix() and target.is_dir():
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
                    raise GitStateError("Git HITL snapshot contains an unsafe path.")
                destination = (self.work_dir / Path(*relative.parts)).resolve()
                try:
                    destination.relative_to(self.work_dir)
                except ValueError as exc:
                    raise GitStateError("Git HITL snapshot escapes the workspace.") from exc
                source = tar.extractfile(member)
                if source is None:
                    raise GitStateError("Git HITL snapshot contains an unreadable file.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as handle:
                    shutil.copyfileobj(source, handle)

    def _present_snapshot_paths(self, paths: Sequence[str]) -> list[str]:
        """Expand durable paths while omitting ephemeral HITL process files."""
        present: list[str] = []
        for relative_path in paths:
            target = self.work_dir / relative_path
            if relative_path == AUTONOMOUS_RELATIVE_ROOT.as_posix() and target.is_dir():
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
        root = AUTONOMOUS_RELATIVE_ROOT.parts
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
            or name in {"history.sqlite-wal", "history.sqlite-shm", "manager_mcp.json"}
        )

    def _clear_durable_hitl_directory(self, hitl_dir: Path) -> None:
        """Remove rollback-controlled files while leaving live lock/wrapper paths alone."""
        for path in sorted(hitl_dir.rglob("*"), reverse=True):
            relative = path.relative_to(self.work_dir).as_posix()
            if path.name in {
                "history.sqlite-wal",
                "history.sqlite-shm",
                "manager_mcp.json",
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
        process = run_git(self.work_dir, "rev-parse", "--verify", ref, check=False)
        if process.returncode:
            return None
        return process.stdout.strip()

    def _ref_exists(self, ref: str) -> bool:
        process = run_git(
            self.work_dir,
            "rev-parse",
            "--verify",
            "--quiet",
            ref,
            check=False,
        )
        if process.returncode == 0:
            return True
        if process.returncode == 1:
            return False
        raise GitStateError("Git could not verify the HITL rollback boundary.")

    def _record_whiteboard_version(
        self,
        *,
        path: str,
        ref: str,
        message: str,
    ) -> GitSnapshot:
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
    ) -> GitSnapshot:
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
        except GitStateError:
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
        raise GitStateError(
            "Git whiteboard history has no rollback boundary for the active AutoResearch attempt."
        )

    def _autoresearch_hitl_attempt_snapshot(self, attempt_id: str) -> GitSnapshot:
        ref = self._autoresearch_hitl_rollback_ref(attempt_id)
        return GitSnapshot(
            ref=ref,
            commit_sha=self._rev_parse(ref),
            paths=DURABLE_AUTONOMOUS_STATE_PATHS,
        )

    def _autoresearch_hitl_rollback_ref(self, attempt_id: str) -> str:
        safe_attempt_id = self._require_attempt_id(attempt_id)
        return f"{AUTORESEARCH_AUTONOMOUS_ROLLBACK_REF_PREFIX}/{safe_attempt_id}"

    def _rev_parse(self, ref: str) -> str:
        return self._run_git("rev-parse", "--verify", ref).strip()

    def _run_git(self, *args: str, env: dict[str, str] | None = None) -> str:
        try:
            process = run_git(self.work_dir, *args, env=env)
        except GitCommandError as exc:
            raise GitStateError(str(exc)) from exc
        return str(process.stdout)

    def _run_git_bytes(self, *args: str) -> bytes:
        try:
            process = run_git(self.work_dir, *args, text=False)
        except GitCommandError as exc:
            raise GitStateError(str(exc)) from exc
        return bytes(process.stdout)

    @staticmethod
    def _require_attempt_id(value: str) -> str:
        attempt_id = str(value).strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/attempt_\d+", attempt_id):
            raise GitStateError("Invalid AutoResearch attempt id.")
        return attempt_id

    @staticmethod
    def _normalize_paths(paths: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        for value in paths:
            path = PurePosixPath(str(value))
            if path.is_absolute() or not path.parts or ".." in path.parts:
                raise GitStateError("Invalid HITL state path.")
            normalized.append(path.as_posix())
        return normalized

    @staticmethod
    def rollback_paths() -> tuple[str, ...]:
        """Return the fixed durable path boundary for AutoResearch rollback."""
        return DURABLE_AUTONOMOUS_STATE_PATHS
