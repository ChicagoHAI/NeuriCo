"""Read-only public-workspace inspection for the HITL manager.

This follows the bounded LS/Glob/Grep/Read contract used by Portable Agent's
computer device. HITL keeps the same separation but exposes only public
research-workspace artifacts; NeuriCo runtime state stays behind its dedicated
HITL tools.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable

_HIDDEN_PATH_PARTS = {
    ".claude",
    ".codex",
    ".gemini",
    ".git",
    ".neurico",
    ".venv",
    "__pycache__",
}
_PROTECTED_RELATIVE_PATHS = {
    "scoring/eval.py",
    "scoring/rule_maker_log.md",
    "scoring/targets.json",
}
_PROTECTED_PREFIXES = {"data/.test"}
_SECRET_FILE_NAMES = {
    "credentials",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "secrets.json",
    "service-account.json",
    "service_account.json",
    "token",
    "tokens.json",
}
_SECRET_FILE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".kubeconfig")
_MAX_DIRECTORY_ENTRIES = 500
_MAX_FILE_MATCHES = 1000
_MAX_READ_BYTES = 400_000
_MAX_SEARCH_COLUMNS = 500
_SEARCH_TIMEOUT_SECONDS = 30


class HitlWorkspaceInspectionError(ValueError):
    """A manager workspace-inspection request cannot be completed safely."""


class HitlWorkspaceInspector:
    """Read public workspace files through bounded, manager-safe operations."""

    def __init__(
        self,
        work_dir: Path,
        *,
        listed_protected_paths: Iterable[str] = (),
    ) -> None:
        self.work_dir = work_dir.resolve()
        self.listed_protected_paths = frozenset(
            str(path).strip().replace("\\", "/")
            for path in listed_protected_paths
            if str(path).strip().replace("\\", "/") in _PROTECTED_RELATIVE_PATHS
        )

    def list_workspace(self, path: str = ".") -> str:
        """Return one public directory listing."""
        target = self._resolve_path(path, expect="directory")
        entries = []
        for item in sorted(
            target.iterdir(), key=lambda candidate: (not candidate.is_dir(), candidate.name)
        ):
            if self._is_hidden(item) or self._is_secret(item) or self._is_protected_prefix(item):
                continue
            if self._is_protected(item) and self._relative_path(item) not in self.listed_protected_paths:
                continue
            protected_listing = self._is_protected(item)
            entries.append(
                {
                    "name": item.name + ("/" if item.is_dir() else ""),
                    "kind": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                    **({"integrity": self._integrity_metadata(item)} if protected_listing else {}),
                }
            )
        return self._render(
            {
                "path": self._relative_path(target),
                "entries": entries[:_MAX_DIRECTORY_ENTRIES],
                "truncated": len(entries) > _MAX_DIRECTORY_ENTRIES,
            }
        )

    def find_workspace_files(self, pattern: str, path: str = ".") -> str:
        """Return public files matching one workspace-relative glob pattern."""
        normalized_pattern = self._require_text(pattern, "pattern")
        candidate_pattern = Path(normalized_pattern)
        if candidate_pattern.is_absolute() or ".." in candidate_pattern.parts:
            raise HitlWorkspaceInspectionError(
                "pattern must be a workspace-relative glob that does not contain '..'."
            )
        root = self._resolve_path(path, expect="directory")
        matches = []
        for item in root.glob(normalized_pattern):
            if item.is_file() and (
                not self._is_protected(item)
                or self._relative_path(item) in self.listed_protected_paths
            ):
                matches.append(item)
        matches.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return self._render(
            {
                "path": self._relative_path(root),
                "pattern": normalized_pattern,
                "matches": [self._relative_path(item) for item in matches[:_MAX_FILE_MATCHES]],
                "truncated": len(matches) > _MAX_FILE_MATCHES,
            }
        )

    def search_workspace(
        self,
        pattern: str,
        path: str = ".",
        glob: str | None = None,
        case_insensitive: bool = False,
    ) -> str:
        """Search public workspace text with ripgrep and return line-numbered matches."""
        normalized_pattern = self._require_text(pattern, "pattern")
        target = self._resolve_path(path)
        if target.is_file():
            self._read_text(target)
        normalized_glob = self._optional_text(glob)
        if normalized_glob:
            candidate_glob = Path(normalized_glob)
            if candidate_glob.is_absolute() or ".." in candidate_glob.parts:
                raise HitlWorkspaceInspectionError(
                    "glob must be workspace-relative and must not contain '..'."
                )
        if not isinstance(case_insensitive, bool):
            raise HitlWorkspaceInspectionError("case_insensitive must be true or false.")
        command = [
            "rg",
            "--hidden",
            "--color",
            "never",
            "--no-heading",
            "--with-filename",
            "--line-number",
            "--max-columns",
            str(_MAX_SEARCH_COLUMNS),
        ]
        for hidden in sorted(_HIDDEN_PATH_PARTS):
            command.extend(["--glob", f"!**/{hidden}/**"])
            command.extend(["--glob", f"!**/{hidden}"])
        for protected in sorted(_PROTECTED_RELATIVE_PATHS):
            command.extend(["--glob", f"!{protected}"])
        for protected in sorted(_PROTECTED_PREFIXES):
            command.extend(["--glob", f"!{protected}/**"])
            command.extend(["--glob", f"!{protected}"])
        for secret_pattern in (
            ".env",
            ".env.*",
            "credentials*",
            "id_rsa*",
            "secrets*",
            "token*",
        ):
            command.extend(["--glob", f"!**/{secret_pattern}"])
        if case_insensitive:
            command.append("-i")
        if normalized_glob:
            command.extend(["--glob", normalized_glob])
        command.extend(["-e", normalized_pattern, str(target)])
        try:
            completed = subprocess.run(
                command,
                cwd=self.work_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=_SEARCH_TIMEOUT_SECONDS,
                check=False,
            )
        except FileNotFoundError as exc:
            raise HitlWorkspaceInspectionError("search_workspace requires ripgrep (`rg`).") from exc
        except subprocess.TimeoutExpired as exc:
            raise HitlWorkspaceInspectionError(
                "search_workspace timed out. Narrow path or pattern and retry."
            ) from exc
        if completed.returncode == 1:
            matches: list[dict[str, Any]] = []
        elif completed.returncode != 0:
            raise HitlWorkspaceInspectionError(completed.stderr.strip() or "ripgrep search failed.")
        else:
            matches = self._parse_search_matches(completed.stdout)
        return self._render(
            {
                "path": self._relative_path(target),
                "pattern": normalized_pattern,
                "matches": matches[:_MAX_FILE_MATCHES],
                "truncated": len(matches) > _MAX_FILE_MATCHES,
            }
        )

    def read_workspace_file(self, path: str, offset: int = 1, limit: int = 200) -> str:
        """Read a bounded, line-numbered range from one public text file."""
        target = self._resolve_path(path, expect="file")
        normalized_offset = self._positive_int(offset, "offset")
        normalized_limit = self._positive_int(limit, "limit")
        lines, truncated_by_bytes = self._read_text(target)
        selected = lines[normalized_offset - 1 : normalized_offset - 1 + normalized_limit]
        numbered = "\n".join(
            f"{line_number:>6}\t{line}"
            for line_number, line in enumerate(selected, start=normalized_offset)
        )
        return self._render(
            {
                "path": self._relative_path(target),
                "line_start": normalized_offset,
                "line_count": len(selected),
                "total_lines": len(lines),
                "truncated": truncated_by_bytes
                or normalized_offset - 1 + normalized_limit < len(lines),
                "content": numbered,
            }
        )

    def _resolve_path(self, path: str, *, expect: str | None = None) -> Path:
        normalized_path = self._optional_text(path) or "."
        candidate = Path(normalized_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise HitlWorkspaceInspectionError(
                "path must be relative to the research workspace and must not contain '..'."
            )
        resolved = (self.work_dir / candidate).resolve()
        try:
            resolved.relative_to(self.work_dir)
        except ValueError as exc:
            raise HitlWorkspaceInspectionError(
                "path must remain inside the research workspace."
            ) from exc
        if self._is_protected(resolved):
            raise HitlWorkspaceInspectionError(
                "This path is protected from HITL manager inspection. "
                "Use public interfaces, runtime-derived results, or dedicated HITL tools instead."
            )
        if not resolved.exists():
            raise HitlWorkspaceInspectionError(
                f"workspace path does not exist: {normalized_path}. Inspect the parent directory and retry."
            )
        if expect == "directory" and not resolved.is_dir():
            raise HitlWorkspaceInspectionError(
                f"'{normalized_path}' is a file. Use read_workspace_file instead."
            )
        if expect == "file" and not resolved.is_file():
            raise HitlWorkspaceInspectionError(
                f"'{normalized_path}' is a directory. Use list_workspace instead."
            )
        return resolved

    def _read_text(self, path: Path) -> tuple[list[str], bool]:
        with path.open("rb") as handle:
            data = handle.read(_MAX_READ_BYTES + 1)
        truncated = len(data) > _MAX_READ_BYTES
        data = data[:_MAX_READ_BYTES]
        if b"\x00" in data:
            raise HitlWorkspaceInspectionError("binary files cannot be read or searched.")
        try:
            return data.decode("utf-8").splitlines(), truncated
        except UnicodeDecodeError as exc:
            raise HitlWorkspaceInspectionError(
                "only UTF-8 text files can be read or searched."
            ) from exc

    def _parse_search_matches(self, output: str) -> list[dict[str, Any]]:
        matches = []
        for raw_line in output.splitlines():
            raw_path, separator, remainder = raw_line.partition(":")
            if not separator:
                continue
            raw_line_number, separator, text = remainder.partition(":")
            if not separator:
                continue
            try:
                line_number = int(raw_line_number)
            except ValueError:
                continue
            path = Path(raw_path).resolve()
            if self._is_protected(path):
                continue
            try:
                relative_path = self._relative_path(path)
            except ValueError:
                continue
            matches.append(
                {
                    "path": relative_path,
                    "line_number": line_number,
                    "line": text[:1000],
                }
            )
        return matches

    def _is_hidden(self, path: Path) -> bool:
        try:
            relative_parts = path.resolve().relative_to(self.work_dir).parts
        except ValueError:
            return True
        return any(part in _HIDDEN_PATH_PARTS for part in relative_parts)

    def _is_protected(self, path: Path) -> bool:
        try:
            relative = path.resolve().relative_to(self.work_dir)
        except ValueError:
            return True
        if self._is_hidden(path):
            return True
        normalized = relative.as_posix()
        if normalized in _PROTECTED_RELATIVE_PATHS:
            return True
        if any(
            normalized == prefix or normalized.startswith(f"{prefix}/")
            for prefix in _PROTECTED_PREFIXES
        ):
            return True
        name = relative.name.lower()
        return (
            name == ".env"
            or name.startswith(".env.")
            or name in _SECRET_FILE_NAMES
            or name.startswith("credentials")
            or name.startswith("secrets")
            or name.startswith("token")
            or name.startswith("service-account")
            or name.startswith("service_account")
            or name.endswith(_SECRET_FILE_SUFFIXES)
        )

    def _is_protected_prefix(self, path: Path) -> bool:
        try:
            normalized = path.resolve().relative_to(self.work_dir).as_posix()
        except ValueError:
            return True
        return any(
            normalized == prefix or normalized.startswith(f"{prefix}/")
            for prefix in _PROTECTED_PREFIXES
        )

    def _is_secret(self, path: Path) -> bool:
        try:
            name = path.resolve().relative_to(self.work_dir).name.lower()
        except ValueError:
            return True
        return (
            name == ".env"
            or name.startswith(".env.")
            or name in _SECRET_FILE_NAMES
            or name.startswith("credentials")
            or name.startswith("secrets")
            or name.startswith("token")
            or name.startswith("service-account")
            or name.startswith("service_account")
            or name.endswith(_SECRET_FILE_SUFFIXES)
        )

    @staticmethod
    def _integrity_metadata(path: Path) -> dict[str, Any]:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return {"sha256": digest.hexdigest()}

    def _relative_path(self, path: Path) -> str:
        return path.resolve().relative_to(self.work_dir).as_posix()

    @staticmethod
    def _require_text(value: object, name: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise HitlWorkspaceInspectionError(f"{name} must be a non-empty string.")
        return text

    @staticmethod
    def _optional_text(value: object) -> str:
        return str(value or "").strip()

    @staticmethod
    def _positive_int(value: object, name: str) -> int:
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise HitlWorkspaceInspectionError(f"{name} must be a positive integer.") from exc
        if normalized < 1:
            raise HitlWorkspaceInspectionError(f"{name} must be a positive integer.")
        return normalized

    @staticmethod
    def _render(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2)
