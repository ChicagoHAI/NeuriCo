"""Runtime checks for HITL workspace-write boundaries."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from core.hitl_util import sha256_file

_EXCLUDED_PUBLIC_PREFIXES = {
    ".claude",
    ".codex",
    ".gemini",
    ".git",
    ".neurico",
    ".venv",
    "__pycache__",
    "logs",
    # Runtime-owned: PipelineState._save() rewrites it during guarded phases,
    # so snapshotting it turns the runtime's own write into a worker violation.
    "STATE.md",
}


@dataclass(frozen=True)
class _FileState:
    kind: str
    size: int
    modified_ns: int
    sha256: str | None = None


class HitlWorkspaceWriteGuard:
    """Compare a bounded workspace view at one runtime-owned phase boundary.

    The guard records file type and content hashes rather than copying research
    data. HITL workers are expected to follow the runtime protocol; this
    mechanical gate catches accidental or unauthorized public writes before
    progression.
    """

    def __init__(
        self,
        work_dir: Path,
        baseline: dict[str, _FileState],
        tracked_paths: tuple[str, ...] | None = None,
    ) -> None:
        self.work_dir = Path(work_dir).resolve()
        self.baseline = dict(baseline)
        self.tracked_paths = tracked_paths

    @classmethod
    def capture_public(cls, work_dir: Path) -> "HitlWorkspaceWriteGuard":
        root = Path(work_dir).resolve()
        return cls(root, cls._snapshot(root, include_hidden=False))

    @classmethod
    def public_fingerprint(cls, work_dir: Path) -> str:
        """Return a stable digest of the public workspace at one boundary."""
        root = Path(work_dir).resolve()
        states = cls._snapshot(root, include_hidden=False)
        digest = hashlib.sha256()
        for path, state in sorted(states.items()):
            digest.update(path.encode("utf-8"))
            digest.update(repr(state).encode("utf-8"))
        return digest.hexdigest()

    @classmethod
    def capture_paths(cls, work_dir: Path, paths: Iterable[str]) -> "HitlWorkspaceWriteGuard":
        root = Path(work_dir).resolve()
        normalized = tuple(cls._normalize_relative(path) for path in paths)
        return cls(
            root,
            cls._snapshot_paths(root, normalized, hash_content=True),
            tracked_paths=normalized,
        )

    def allow_only(self, paths: Iterable[str]) -> dict[str, object]:
        allowed = {self._normalize_relative(path) for path in paths}
        return self._validate(allowed=allowed)

    def require_unchanged(self) -> dict[str, object]:
        return self._validate(allowed=set())

    def _validate(self, *, allowed: set[str]) -> dict[str, object]:
        current = self._current_snapshot()
        changed = sorted(
            path
            for path in set(self.baseline) | set(current)
            if self.baseline.get(path) != current.get(path)
            and not self._path_is_allowed(path, allowed)
        )
        if not changed:
            return {"valid": True, "issues": []}
        return {
            "valid": False,
            "issues": ["Runtime detected writes outside this HITL boundary: " + ", ".join(changed)],
        }

    @staticmethod
    def _path_is_allowed(path: str, allowed: set[str]) -> bool:
        """Allow an explicitly permitted path and its required parent directories."""
        return path in allowed or any(allowed_path.startswith(path + "/") for allowed_path in allowed)

    def _current_snapshot(self) -> dict[str, _FileState]:
        if self.tracked_paths is not None:
            return self._snapshot_paths(self.work_dir, self.tracked_paths, hash_content=True)
        return self._snapshot(self.work_dir, include_hidden=False)

    @staticmethod
    def _snapshot(root: Path, *, include_hidden: bool) -> dict[str, _FileState]:
        states: dict[str, _FileState] = {}
        for path in root.rglob("*"):
            relative = path.relative_to(root).as_posix()
            if not include_hidden and HitlWorkspaceWriteGuard._is_excluded(relative):
                continue
            try:
                stats = path.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(stats.st_mode):
                states[relative] = _FileState(
                    kind="symlink",
                    size=stats.st_size,
                    modified_ns=stats.st_mtime_ns,
                    sha256=os.readlink(path),
                )
            elif stat.S_ISREG(stats.st_mode):
                states[relative] = _FileState(
                    kind="file",
                    size=stats.st_size,
                    modified_ns=stats.st_mtime_ns,
                    sha256=sha256_file(path),
                )
        return states

    @staticmethod
    def _snapshot_paths(
        root: Path,
        paths: Iterable[str],
        *,
        hash_content: bool,
    ) -> dict[str, _FileState]:
        states: dict[str, _FileState] = {}
        for raw_path in paths:
            relative = HitlWorkspaceWriteGuard._normalize_relative(raw_path)
            path = root / relative
            try:
                stats = path.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(stats.st_mode):
                states[relative] = _FileState(
                    kind="symlink",
                    size=stats.st_size,
                    modified_ns=stats.st_mtime_ns,
                    sha256=os.readlink(path),
                )
            elif stat.S_ISREG(stats.st_mode):
                states[relative] = _FileState(
                    kind="file",
                    size=stats.st_size,
                    modified_ns=stats.st_mtime_ns,
                    sha256=sha256_file(path) if hash_content else None,
                )
            else:
                states[relative] = _FileState(
                    kind="other",
                    size=stats.st_size,
                    modified_ns=stats.st_mtime_ns,
                )
        return states

    @staticmethod
    def _is_excluded(relative: str) -> bool:
        parts = Path(relative).parts
        return bool(parts and (parts[0] in _EXCLUDED_PUBLIC_PREFIXES or ".git" in parts))

    @staticmethod
    def _normalize_relative(path: str) -> str:
        candidate = Path(str(path).strip())
        if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
            raise ValueError("HITL workspace guard paths must be workspace-relative.")
        return candidate.as_posix()
