"""Opt-in analysis records, separate from Harbor's public artifact bundle."""

from __future__ import annotations

from contextlib import closing, nullcontext
from dataclasses import replace
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
from typing import Any

from core.hitl_manager_history import HitlManagerHistory
from core.hitl_util import atomic_write_bytes
from core.trace_retention import TRACE_GAP_MARKER

from .artifacts import (
    TraceRedactor, WorkspaceBaseline, _CACHE_DIR_NAMES, _DEPENDENCY_DIR_NAMES,
    _PROVIDER_HOME_DIR_NAMES, _decode_text_payload, _stat_fingerprint,
    _is_credential_path, _safe_text_payload, _sanitize_free_text_lines,
    _sanitize_trace_text, _validate_run_id, _write_json,
    _runtime_inventory, _git_output,
)
from .scratch import EphemeralRunScratch, PrivateOutputSpool


DEFAULT_INTERNAL_TRACE_ROOT = Path("/logs/agent/neurico")
_RESEARCH_ROOTS = {
    "logs", ".neurico", "plans", "discussions", "results", "figures",
    "artifacts", "outputs", "notebooks",
}


class InternalTraceArchive:
    """One persistent private directory; failed collection never resets it."""

    def __init__(self, directory: Path, redactor: TraceRedactor):
        self.directory = directory
        self.redactor = replace(redactor, redact_sensitive_paths=False)
        self.files: dict[str, dict[str, Any]] = {}
        self.gaps: list[dict[str, str]] = []
        self.observations: list[dict[str, Any]] = []
        self.status = "pending"

    @classmethod
    def create(cls, root: Path, run_id: str, redactor: TraceRedactor) -> InternalTraceArchive:
        _validate_run_id(run_id)
        if not root.is_absolute():
            raise ValueError("Internal trace root must be absolute")
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        if root.is_symlink():
            raise ValueError("Internal trace root must not be a symlink")
        directory = root / run_id
        directory.mkdir(mode=0o700)
        return cls(directory, redactor)

    def gap(self, source: str, reason: str) -> None:
        self.gaps.append({"source": source, "reason": reason})

    def _destination(self, relative: Path) -> Path:
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid internal archive path")
        destination = self.directory / relative
        destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        return destination

    def _index(self, relative: Path, family: str, *, sanitized: bool = False) -> None:
        path = self.directory / relative
        digest = sha256()
        size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        self.files[relative.as_posix()] = {
            "path": relative.as_posix(), "bytes": size, "sha256": digest.hexdigest(),
            "family": family, "sanitized": sanitized,
        }

    def _publish(self, relative: Path, payload: bytes, family: str, *, sanitized: bool) -> None:
        destination = self._destination(relative)
        atomic_write_bytes(destination, payload)
        destination.chmod(0o600)
        self._index(relative, family, sanitized=sanitized)

    def _sqlite_payload(self, source: Path) -> tuple[bytes, bool]:
        """Back up native SQLite and redact text in the copy, never in live state."""
        with tempfile.TemporaryDirectory(prefix="neurico-trace-sqlite-") as temp:
            copy = Path(temp) / "records.sqlite"
            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
                with closing(sqlite3.connect(copy)) as database:
                    original.backup(database)
            changed = False
            with closing(sqlite3.connect(copy)) as database:
                database.execute("PRAGMA journal_mode=DELETE")
                database.execute("PRAGMA secure_delete=ON")
                tables = database.execute("PRAGMA table_list").fetchall()
                for _schema, name, kind, *_rest in tables:
                    if kind not in {"table", "virtual"} or name.startswith("sqlite_"):
                        continue
                    quoted = '"' + name.replace('"', '""') + '"'
                    columns = database.execute(f"PRAGMA table_info({quoted})").fetchall()
                    text_columns = [column[1] for column in columns]
                    for column in text_columns:
                        col = '"' + column.replace('"', '""') + '"'
                        for (value,) in database.execute(
                            f"SELECT DISTINCT {col} FROM {quoted} WHERE typeof({col})='text'"
                        ).fetchall():
                            clean = _sanitize_trace_text(value, ".json", self.redactor)
                            if clean != value:
                                database.execute(
                                    f"UPDATE {quoted} SET {col}=? WHERE {col}=?", (clean, value)
                                )
                                changed = True
                    if changed and kind == "virtual":
                        definition = database.execute(
                            "SELECT sql FROM sqlite_master WHERE name=?", (name,)
                        ).fetchone()
                        if definition and "using fts" in definition[0].lower():
                            # Rebuild recall indexes so deleted secret terms do not
                            # survive in old FTS segments of the copied database.
                            database.execute(f"INSERT INTO {quoted}({quoted}) VALUES ('rebuild')")
                database.commit()
                if changed:
                    database.execute("VACUUM")
            payload = copy.read_bytes()
            self._check_binary_credentials(payload)
            return payload, changed

    def _check_binary_credentials(self, payload: bytes) -> None:
        # Never corrupt binary analysis outputs by replacing arbitrary bytes.
        # If known/recognizable credentials occur, report an explicit omission.
        if self.redactor.contains_secret(payload.decode("utf-8", errors="replace")):
            raise ValueError("credential-bearing binary cannot be retained unchanged")

    def copy_file(self, source: Path, relative: Path, family: str) -> None:
        try:
            if _is_credential_path(relative, self.redactor):
                return
            info = source.lstat()
            if not stat.S_ISREG(info.st_mode) or source.is_symlink():
                self.gap(relative.as_posix(), "not_regular_file")
                return
            with source.open("rb") as handle:
                header = handle.read(16)
            if header == b"SQLite format 3\x00":
                payload, sanitized = self._sqlite_payload(source)
            else:
                raw = source.read_bytes()
                if _decode_text_payload(raw) is not None:
                    safe = _safe_text_payload(raw, source.suffix, self.redactor)
                    if safe is None:
                        raise ValueError("text could not be sanitized")
                    payload, sanitized = safe
                else:
                    self._check_binary_credentials(raw)
                    payload, sanitized = raw, False
            self._publish(relative, payload, family, sanitized=sanitized)
            if family == "provider" and source.suffix == ".jsonl":
                self._observe_provider(relative, payload)
        except Exception as error:
            self.gap(relative.as_posix(), type(error).__name__)

    def _observe_provider(self, relative: Path, payload: bytes) -> None:
        for line in payload.splitlines():
            try:
                event = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(event, dict) or event.get("type") not in {"session_meta", "turn_context"}:
                continue
            data = event.get("payload", {})
            if not isinstance(data, dict):
                continue
            observed = {key: data[key] for key in (
                "id", "model", "model_provider", "effort", "reasoning_effort", "cli_version"
            ) if key in data}
            if observed:
                record = {"source": relative.as_posix(), "type": event["type"], **observed}
                if record not in self.observations:
                    self.observations.append(record)

    def tree(self, source: Path, relative: Path, family: str) -> None:
        if not source.exists():
            return
        if source.is_symlink():
            self.gap(relative.as_posix(), "symlink")
            return
        if source.is_file():
            self.copy_file(source, relative, family)
            return
        for current, directories, filenames in os.walk(source, followlinks=False,
                onerror=lambda error: self.gap(relative.as_posix(), type(error).__name__)):
            parent = Path(current)
            for name in list(directories):
                child = parent / name
                target = relative / child.relative_to(source)
                if _is_credential_path(target, self.redactor) or name in (
                    _CACHE_DIR_NAMES | _DEPENDENCY_DIR_NAMES | {".git"}
                ):
                    directories.remove(name)
                elif child.is_symlink():
                    directories.remove(name)
                    self.gap(target.as_posix(), "symlink")
            for name in sorted(filenames):
                if name.endswith((".sqlite-wal", ".sqlite-shm", ".db-wal", ".db-shm")):
                    continue  # SQLite backup includes committed WAL records.
                self.copy_file(parent / name, relative / (parent / name).relative_to(source), family)

    def workspace(self, workspace: Path, baseline: WorkspaceBaseline) -> None:
        manager = workspace / ".neurico/hitl/manager"
        lock = (HitlManagerHistory.snapshot_lock(manager)
                if (manager / "history.sqlite").is_file() else nullcontext())
        with lock:
            for name in sorted(_RESEARCH_ROOTS):
                self.tree(workspace / name, Path(name), "research")
        # Existing baseline locates additional changed task solutions/outputs.
        # Dependency/cache/provider homes are not research output archives.
        for current, directories, filenames in os.walk(workspace, followlinks=False):
            parent = Path(current)
            directories[:] = [name for name in directories if name not in (
                _CACHE_DIR_NAMES | _DEPENDENCY_DIR_NAMES | _PROVIDER_HOME_DIR_NAMES
                | {".git"} | (_RESEARCH_ROOTS if parent == workspace else set())
            ) and not (parent / name).is_symlink()
                and not _is_credential_path((parent / name).relative_to(workspace), self.redactor)]
            for name in sorted(filenames):
                source = parent / name
                relative = source.relative_to(workspace)
                if _is_credential_path(relative, self.redactor):
                    continue
                try:
                    if not baseline.complete and relative.as_posix() not in baseline.fingerprints:
                        continue
                    if _stat_fingerprint(source.lstat()) != baseline.fingerprints.get(relative.as_posix()):
                        self.copy_file(source, relative, "research")
                except OSError as error:
                    self.gap(relative.as_posix(), type(error).__name__)
        if not baseline.complete:
            self.gap("workspace", "additional_output_inventory_incomplete")

    def stream(self, spool: PrivateOutputSpool | None) -> None:
        relative = Path("streams/stdout-stderr.log")
        if spool is None:
            self.gap(str(relative), "spool_unavailable")
            return
        temporary = None
        try:
            spool.handle.flush()
            spool.handle.seek(0)
            destination = self._destination(relative)
            sanitized = False
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
                temporary = Path(output.name)
                # Read complete lines: read-chunk boundaries cannot split a credential.
                lines = io.TextIOWrapper(spool.handle, encoding="utf-8", errors="strict")
                try:
                    if any("\n" in value or "\r" in value for value in self.redactor.exact_values):
                        text = self.redactor.sanitize(lines.read())
                        source_lines = text.splitlines(keepends=True)
                    else:
                        source_lines = lines
                    for clean in _sanitize_free_text_lines(source_lines, self.redactor):
                        if TRACE_GAP_MARKER in clean:
                            self.gap("retention_hooks", "recording_failed")
                        if self.redactor.contains_secret(clean):
                            raise ValueError("stream could not be sanitized")
                        sanitized = sanitized or "[REDACTED" in clean
                        output.write(clean.encode("utf-8"))
                finally:
                    lines.detach()
            os.replace(temporary, destination)
            self._index(relative, "stream", sanitized=sanitized)
            if spool.truncated:
                self.gap(str(relative), "stream_truncated")
        except Exception as error:
            self.gap(str(relative), type(error).__name__)
            # The temporary stream contains only already-sanitized output.
            # Preserve its available prefix if a later read/write fails.
            if temporary is not None and temporary.is_file():
                try:
                    os.replace(temporary, self._destination(relative))
                    self._index(relative, "stream", sanitized=sanitized)
                except OSError as storage_error:
                    self.gap(str(relative), type(storage_error).__name__)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def scratch(self, scratch: EphemeralRunScratch | None, workspace: Path) -> None:
        if scratch is None:
            return
        metadata = scratch.run_dir / "scratch.json"
        if not metadata.is_file():
            self.gap("scratch", "manifest_unavailable")
            return
        self.copy_file(metadata, Path("scratch.json"), "scratch")
        payload = json.loads(metadata.read_text())
        for record in payload.get("files", []):
            relative = Path(record["path"])
            if relative == Path("streams/stdout-stderr.raw"):
                continue  # Full spool collected directly.
            if relative.parts[:1] == ("workspace",):
                destination = Path(*relative.parts[1:])
                if destination.as_posix() in self.files:
                    continue
                source = workspace / destination
                if source.is_file():
                    self.copy_file(source, destination, "research")
                else:
                    self.copy_file(scratch.run_dir / relative, destination, "scratch")
                    if record.get("truncated"):
                        self.gap(destination.as_posix(), "scratch_prefix_only")
        for error in payload.get("errors", []):
            self.gap("scratch", error["type"])

    def collect(self, *, workspace: Path, control_dir: Path | None,
                baseline: WorkspaceBaseline, spool: PrivateOutputSpool | None,
                scratch: EphemeralRunScratch | None) -> None:
        # Independent source families keep collecting after an isolated error.
        sources = [
            ("stream", lambda: self.stream(spool)),
            ("workspace", lambda: self.workspace(workspace, baseline)),
            ("scratch", lambda: self.scratch(scratch, workspace)),
            ("retention_hooks", self.retained_records),
        ]
        if control_dir is not None:
            sources.extend([
                ("instruction", lambda: self.tree(control_dir / "instruction.txt",
                                                  Path("instruction.txt"), "input")),
                ("idea_registry", lambda: self.tree(control_dir / "ideas",
                                                    Path("idea_registry"), "idea")),
                ("provider", lambda: self.provider(control_dir / "codex-home")),
            ])
        for family, operation in sources:
            try:
                operation()
            except Exception as error:
                self.gap(family, type(error).__name__)

    def provider(self, home: Path) -> None:
        # Session/log/state sources only, never the whole home (auth, installed
        # extensions and caches). Preserve native formats and session identities.
        names = {"sessions", "archived_sessions", "log", "logs", "history.jsonl",
                 "session_index.jsonl", "shell_snapshots", "config.toml"}
        if home.is_dir():
            names.update(path.name for path in home.glob("*.sqlite"))
            names.update(path.name for path in home.glob("*.db"))
        for name in sorted(names):
            self.tree(home / name, Path("provider") / name, "provider")

    def retained_records(self) -> None:
        for name in ("invocations", "snapshots"):
            root = self.directory / name
            if root.is_dir():
                for path in sorted(root.rglob("*")):
                    if path.is_file() and not path.is_symlink():
                        self._index(path.relative_to(self.directory), "retention", sanitized=True)
        gaps = self.directory / "retention-gaps.json"
        if gaps.is_file():
            self._index(Path("retention-gaps.json"), "retention", sanitized=True)
            self.gaps.extend(json.loads(gaps.read_text()))

    def invocation_inventory(self) -> list[dict[str, Any]]:
        """Relate retained calls to the native sessions they actually emitted."""
        sessions = {item["id"]: item["source"] for item in self.observations
                    if item["type"] == "session_meta" and "id" in item}
        records = []
        for folder in sorted((self.directory / "invocations").glob("*")):
            if not folder.is_dir():
                continue
            relative = folder.relative_to(self.directory).as_posix()
            record = {"path": relative, "sessions": []}
            records.append(record)
            try:
                inputs = json.loads((folder / "input.json").read_text())
                record["kind"] = inputs["kind"]
                if not (folder / "outcome.json").is_file():
                    self.gap(relative, "invocation_interrupted")
                    continue
                outcome = json.loads((folder / "outcome.json").read_text())["outcome"]
                if inputs["kind"] == "manager":
                    provider = json.loads((folder / "provider_output.json").read_text())
                    if not (folder / "provider_input.json").is_file():
                        self.gap(relative, "provider_input_missing")
                    output = provider["stdout"]
                    success = provider.get("return_code") == 0
                else:
                    output_path = folder / Path(inputs["transcript_file"]).name
                    output = output_path.read_text() if output_path.is_file() else ""
                    success = outcome.get("success", False)
                    if outcome.get("process_started") and not output_path.is_file():
                        self.gap(relative, "worker_transcript_missing")
                ids = set()
                for line in output.splitlines():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(event, dict) and event.get("type") == "thread.started":
                        if event.get("thread_id"):
                            ids.add(event["thread_id"])
                record["sessions"] = [{"id": identity, "source": sessions.get(identity)}
                                      for identity in sorted(ids)]
                for identity in sorted(ids):
                    if identity not in sessions:
                        self.gap(relative, f"native_session_missing:{identity}")
                if success and not ids:
                    self.gap(relative, "successful_call_session_unobservable")
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.gap(relative, f"invocation_record_unreadable:{type(error).__name__}")
        return records

    def finalize(self, *, run_id: str, run_configuration: dict[str, Any],
                 outcome: str, return_code: int | None,
                 lifecycle: dict[str, Any] | None = None) -> None:
        invocations = self.invocation_inventory()
        if (return_code == 0 and run_configuration.get("workflow") == "focused-managed-ordinary"
                and {record.get("kind") for record in invocations} != {"manager", "worker"}):
            self.gap("invocations", "successful_workflow_records_missing")
        self.status = "partial" if self.gaps else "complete"
        manifest = {
            "schema_version": 1, "run_id": run_id, "configuration": run_configuration,
            "outcome": outcome, "return_code": return_code, "finalized": True,
            "collection_status": self.status,
            "files": [self.files[key] for key in sorted(self.files)],
            "invocations": invocations,
            "gaps": self.gaps, "observed_provider_settings": self.observations,
            "lifecycle": lifecycle or {}, "runtime": _runtime_inventory(),
            "adapter_revision": _git_output(Path(__file__).resolve().parents[3], "rev-parse", "HEAD"),
        }
        _write_json(self.directory / "manifest.json", manifest, redactor=self.redactor)
        (self.directory / "manifest.json").chmod(0o600)
