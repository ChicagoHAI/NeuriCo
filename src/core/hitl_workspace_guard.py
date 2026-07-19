"""Runtime checks for HITL workspace-write boundaries."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_EXCLUDED_PUBLIC_PREFIXES = {
    ".claude",
    ".codex",
    ".gemini",
    ".git",
    ".neurico",
    ".venv",
    "__pycache__",
    "logs",
}


@dataclass(frozen=True)
class _FileState:
    kind: str
    size: int
    modified_ns: int
    sha256: str | None = None


class HitlWorkspaceWriteGuard:
    """Compare a bounded workspace view at one runtime-owned phase boundary.

    The guard deliberately uses file metadata rather than copying research data.
    HITL workers are expected to follow the runtime protocol; this mechanical
    gate catches accidental or unauthorized public writes before progression.
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
            if self.baseline.get(path) != current.get(path) and path not in allowed
        )
        if not changed:
            return {"valid": True, "issues": []}
        return {
            "valid": False,
            "issues": ["Runtime detected writes outside this HITL boundary: " + ", ".join(changed)],
        }

    def _current_snapshot(self) -> dict[str, _FileState]:
        if self.tracked_paths is not None:
            return self._snapshot_paths(self.work_dir, self.tracked_paths, hash_content=True)
        return self._snapshot(self.work_dir, include_hidden=False)

    @staticmethod
    def _snapshot(root: Path, *, include_hidden: bool) -> dict[str, _FileState]:
        states: dict[str, _FileState] = {}
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix()
            if not include_hidden and HitlWorkspaceWriteGuard._is_excluded(relative):
                continue
            stats = path.stat()
            states[relative] = _FileState(
                kind="file",
                size=stats.st_size,
                modified_ns=stats.st_mtime_ns,
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
                    sha256=HitlWorkspaceWriteGuard._sha256(path) if hash_content else None,
                )
            else:
                states[relative] = _FileState(
                    kind="other",
                    size=stats.st_size,
                    modified_ns=stats.st_mtime_ns,
                )
        return states

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _is_excluded(relative: str) -> bool:
        return bool(Path(relative).parts and Path(relative).parts[0] in _EXCLUDED_PUBLIC_PREFIXES)

    @staticmethod
    def _normalize_relative(path: str) -> str:
        candidate = Path(str(path).strip())
        if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
            raise ValueError("HITL workspace guard paths must be workspace-relative.")
        return candidate.as_posix()
