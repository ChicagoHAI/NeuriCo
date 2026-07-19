"""Runtime checks for HITL workspace-write boundaries."""

from __future__ import annotations

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
    size: int
    modified_ns: int


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
        return cls(root, cls._snapshot_paths(root, normalized), tracked_paths=normalized)

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
            return self._snapshot_paths(self.work_dir, self.tracked_paths)
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
            states[relative] = _FileState(size=stats.st_size, modified_ns=stats.st_mtime_ns)
        return states

    @staticmethod
    def _snapshot_paths(root: Path, paths: Iterable[str]) -> dict[str, _FileState]:
        states: dict[str, _FileState] = {}
        for raw_path in paths:
            relative = HitlWorkspaceWriteGuard._normalize_relative(raw_path)
            path = root / relative
            if path.is_file() and not path.is_symlink():
                stats = path.stat()
                states[relative] = _FileState(size=stats.st_size, modified_ns=stats.st_mtime_ns)
        return states

    @staticmethod
    def _is_excluded(relative: str) -> bool:
        return bool(Path(relative).parts and Path(relative).parts[0] in _EXCLUDED_PUBLIC_PREFIXES)

    @staticmethod
    def _normalize_relative(path: str) -> str:
        candidate = Path(str(path).strip())
        if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
            raise ValueError("HITL workspace guard paths must be workspace-relative.")
        return candidate.as_posix()
