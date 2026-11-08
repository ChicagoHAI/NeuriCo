"""Persistent, redacted research artifacts for Harbor trials."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from importlib import metadata as importlib_metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
from typing import Any, Iterable

from core.security import sanitize_text, sensitive_env_values


DEFAULT_HARBOR_ARTIFACT_DIR = Path("/logs/artifacts/neurico")

_TRACE_SUFFIXES = frozenset({".json", ".jsonl", ".log", ".md", ".txt", ".yaml", ".yml"})
_PROVIDER_HOME_DIR_NAMES = frozenset({".claude", ".codex", ".gemini"})
_DEPENDENCY_ENVIRONMENT_DIR_NAMES = frozenset({".tox", ".venv", "env", "node_modules", "venv"})
_DEPENDENCY_CACHE_DIR_NAMES = frozenset(
    {
        ".ipynb_checkpoints",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
    }
)
_SNAPSHOT_PROTECTED_PREFIXES = (
    "data/.test",
    "data/test",
    "data/holdout",
    ".scoring_sealed",
)
_SECRET_FILE_NAMES = frozenset(
    {
        ".netrc",
        ".npmrc",
        ".pypirc",
        "auth.json",
        "credential",
        "credential.json",
        "credentials",
        "credentials.json",
        "id_ed25519",
        "id_rsa",
        "manager_mcp.json",
        "secrets.json",
        "service-account.json",
        "service_account.json",
        "token",
        "tokens.json",
    }
)
_SECRET_FILE_SUFFIXES = (".key", ".kubeconfig", ".p12", ".pem", ".pfx")
_CORE_DUMP_NAME = re.compile(r"^core(?:\.\d+)?$")
_SHA256_NAME = re.compile(r"^[0-9a-f]{64}$")
_SNAPSHOT_MAX_FILE_BYTES = 64 * 1024 * 1024
_SNAPSHOT_INPUT_OBJECT_BUDGET_BYTES = 256 * 1024 * 1024
_SNAPSHOT_TOTAL_OBJECT_BUDGET_BYTES = 512 * 1024 * 1024
_SNAPSHOT_MIN_FREE_BYTES = 256 * 1024 * 1024
_SNAPSHOT_MAX_CAPTURE_SECONDS = 30.0
_READABLE_TRACE_BUDGET_BYTES = 128 * 1024 * 1024
_MANAGER_HISTORY_MAX_BYTES = 128 * 1024 * 1024
_GIT_COMMAND_TIMEOUT_SECONDS = 3.0
_SAFE_ENVIRONMENT_VALUES = frozenset(
    {
        "LANG",
        "LC_ALL",
        "NEURICO_HARBOR_AUTORESEARCH_ITERATIONS",
        "NEURICO_HARBOR_TIME_LIMIT_SECONDS",
        "NEURICO_MODEL",
        "PATH",
        "PYTHONPATH",
        "TZ",
        "UV_PROJECT_ENVIRONMENT",
        "VIRTUAL_ENV",
    }
)
_STATE_FILES = (
    Path(".neurico/pipeline_state.json"),
    Path(".neurico/pipeline_results.json"),
    Path(".neurico/research_state.json"),
    Path(".neurico/research_environment.json"),
    Path(".neurico/idea.yaml"),
    Path(".neurico/hitl/idea/idea.jsonl"),
    Path(".neurico/hitl/runtime.json"),
    Path(".neurico/hitl/launch.json"),
    Path(".neurico/hitl/artifact_contract.json"),
    Path(".neurico/hitl/whiteboard/whiteboard.json"),
    Path(".neurico/hitl/manager/context.jsonl"),
    Path("REPORT.md"),
    Path("STATE.md"),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_sanitized(destination: Path, content: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(sanitize_text(content), encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_exclusion_reason(relative: Path, *, artifact_relative: Path | None) -> str | None:
    normalized = relative.as_posix().lower()
    lowered_parts = tuple(part.lower() for part in relative.parts)
    name = relative.name.lower()
    if artifact_relative is not None and (
        relative == artifact_relative or artifact_relative in relative.parents
    ):
        return "artifact_output"
    if ".git" in lowered_parts:
        return "git_object_database"
    if any(part in _PROVIDER_HOME_DIR_NAMES for part in lowered_parts):
        return "provider_home"
    if any(part in _DEPENDENCY_ENVIRONMENT_DIR_NAMES for part in lowered_parts):
        return "dependency_environment"
    if any(part in _DEPENDENCY_CACHE_DIR_NAMES for part in lowered_parts):
        return "dependency_cache"
    if ".scoring_sealed" in lowered_parts:
        return "sealed_or_hidden_evaluation_data"
    if any(
        normalized == prefix or normalized.startswith(f"{prefix}/")
        for prefix in _SNAPSHOT_PROTECTED_PREFIXES
    ):
        return "sealed_or_hidden_evaluation_data"
    if (
        name == ".env"
        or name.startswith(".env.")
        or name in _SECRET_FILE_NAMES
        or name.startswith("credential")
        or name.startswith("credentials")
        or name.startswith("secrets")
        or name.startswith(("token.", "token_", "tokens.", "tokens_"))
        or name.startswith("service-account")
        or name.startswith("service_account")
        or name.endswith(_SECRET_FILE_SUFFIXES)
    ):
        return "credential_like_path"
    if normalized.startswith(".neurico/hitl/bin/"):
        return "runtime_command_wrapper"
    if name.endswith((".lock", ".sock", ".tmp")):
        return "live_runtime_control"
    if normalized.endswith(
        (
            ".neurico/hitl/manager/history.sqlite",
            ".neurico/hitl/manager/history.sqlite-shm",
            ".neurico/hitl/manager/history.sqlite-wal",
        )
    ):
        return "manager_database_exported_as_redacted_jsonl"
    return None


def _artifact_relative_to_workspace(workspace: Path, artifact_dir: Path) -> Path | None:
    try:
        return artifact_dir.resolve().relative_to(workspace.resolve())
    except ValueError:
        return None


def _record_exclusion(
    excluded: dict[str, dict[str, int]],
    excluded_entries: list[dict[str, Any]],
    reason: str,
    *,
    relative: Path,
    entry_type: str,
    byte_count: int = 0,
) -> None:
    record = excluded.setdefault(reason, {"entries": 0, "bytes": 0})
    record["entries"] += 1
    record["bytes"] += max(0, byte_count)
    entry: dict[str, Any] = {
        "path": relative.as_posix(),
        "type": entry_type,
        "reason": reason,
    }
    if entry_type == "file":
        entry["bytes"] = max(0, byte_count)
    excluded_entries.append(entry)


def _write_snapshot_object(object_path: Path, payload: bytes) -> None:
    if object_path.is_file():
        if (
            object_path.stat().st_size != len(payload)
            or _sha256_file(object_path) != sha256(payload).hexdigest()
        ):
            raise OSError(f"Existing snapshot object failed integrity validation: {object_path}")
        return
    object_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = object_path.with_name(f".{object_path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, object_path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_regular_file_without_following_symlinks(source: Path) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    try:
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise OSError(f"Snapshot source is not a regular file: {source}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read(), opened_stat
    finally:
        os.close(descriptor)


def _runtime_inventory() -> dict[str, Any]:
    packages: dict[str, str] = {}
    try:
        distributions = importlib_metadata.distributions()
        for distribution in distributions:
            try:
                name = str(distribution.metadata.get("Name", "")).strip()
                version = distribution.version
            except (OSError, UnicodeError, ValueError):
                continue
            if name:
                packages[name] = version
    except (OSError, UnicodeError, ValueError):
        pass
    return {
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "platform": platform.platform(),
        },
        "environment": {
            "names": sorted(os.environ),
            "selected_values": {
                name: sanitize_text(os.environ[name])
                for name in sorted(_SAFE_ENVIRONMENT_VALUES)
                if name in os.environ
            },
        },
        "python_packages": dict(sorted(packages.items(), key=lambda item: item[0].lower())),
    }


def capture_workspace_snapshot(
    *,
    workspace: Path,
    artifact_dir: Path,
    phase: str,
) -> dict[str, Any]:
    """Capture a content-addressed, deduplicated input or final workspace snapshot."""
    if phase not in {"input", "final"}:
        raise ValueError("Workspace snapshot phase must be input or final")
    capture_started_monotonic = time.monotonic()
    workspace = workspace.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    objects_dir = artifact_dir / "workspace/snapshots/objects"
    objects_dir.mkdir(parents=True, exist_ok=True)
    artifact_relative = _artifact_relative_to_workspace(workspace, artifact_dir)
    object_budget = (
        _SNAPSHOT_INPUT_OBJECT_BUDGET_BYTES
        if phase == "input"
        else _SNAPSHOT_TOTAL_OBJECT_BUDGET_BYTES
    )
    object_store_bytes = sum(
        path.stat().st_size
        for path in objects_dir.rglob("*")
        if path.is_file() and _SHA256_NAME.fullmatch(path.name)
    )
    capture_deadline = capture_started_monotonic + _SNAPSHOT_MAX_CAPTURE_SECONDS
    capture_complete = True
    capture_stop_reason: str | None = None

    files: list[dict[str, Any]] = []
    directories: list[dict[str, Any]] = []
    symlinks: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    excluded: dict[str, dict[str, int]] = {}
    excluded_entries: list[dict[str, Any]] = []
    configured_secret_values = [value.encode("utf-8") for value in sensitive_env_values() if value]

    for directory, directory_names, file_names in os.walk(workspace, followlinks=False):
        if time.monotonic() >= capture_deadline:
            capture_complete = False
            capture_stop_reason = "capture_time_budget_exhausted"
            break
        directory_path = Path(directory)
        directory_relative = directory_path.relative_to(workspace)
        if directory_relative.parts:
            try:
                directory_stat = directory_path.stat()
            except OSError as error:
                errors.append(
                    {"path": directory_relative.as_posix(), "error": sanitize_text(str(error))}
                )
            else:
                directories.append(
                    {
                        "path": directory_relative.as_posix(),
                        "mode": oct(stat.S_IMODE(directory_stat.st_mode)),
                        "mtime_ns": directory_stat.st_mtime_ns,
                    }
                )
        retained_directories: list[str] = []
        for name in sorted(directory_names):
            candidate = directory_path / name
            relative = candidate.relative_to(workspace)
            if candidate.is_symlink():
                link_stat = candidate.lstat()
                symlinks.append(
                    {
                        "path": relative.as_posix(),
                        "target": sanitize_text(os.readlink(candidate)),
                        "mtime_ns": link_stat.st_mtime_ns,
                    }
                )
                continue
            reason = _snapshot_exclusion_reason(
                relative,
                artifact_relative=artifact_relative,
            )
            if reason is not None:
                _record_exclusion(
                    excluded,
                    excluded_entries,
                    reason,
                    relative=relative,
                    entry_type="directory",
                )
                continue
            retained_directories.append(name)
        directory_names[:] = retained_directories

        for name in sorted(file_names):
            if time.monotonic() >= capture_deadline:
                capture_complete = False
                capture_stop_reason = "capture_time_budget_exhausted"
                break
            source = directory_path / name
            relative = source.relative_to(workspace)
            if source.is_symlink():
                link_stat = source.lstat()
                symlinks.append(
                    {
                        "path": relative.as_posix(),
                        "target": sanitize_text(os.readlink(source)),
                        "mtime_ns": link_stat.st_mtime_ns,
                    }
                )
                continue
            try:
                source_stat = source.lstat()
            except OSError as error:
                errors.append({"path": relative.as_posix(), "error": sanitize_text(str(error))})
                continue
            reason = _snapshot_exclusion_reason(
                relative,
                artifact_relative=artifact_relative,
            )
            if reason is not None:
                _record_exclusion(
                    excluded,
                    excluded_entries,
                    reason,
                    relative=relative,
                    entry_type="file",
                    byte_count=source_stat.st_size,
                )
                continue
            if stat.S_ISLNK(source_stat.st_mode):
                symlinks.append(
                    {
                        "path": relative.as_posix(),
                        "target": sanitize_text(os.readlink(source)),
                        "mtime_ns": source_stat.st_mtime_ns,
                    }
                )
                continue
            if not stat.S_ISREG(source_stat.st_mode):
                _record_exclusion(
                    excluded,
                    excluded_entries,
                    "non_regular_file",
                    relative=relative,
                    entry_type="file",
                    byte_count=source_stat.st_size,
                )
                continue
            if source_stat.st_size > _SNAPSHOT_MAX_FILE_BYTES:
                _record_exclusion(
                    excluded,
                    excluded_entries,
                    "file_size_limit",
                    relative=relative,
                    entry_type="file",
                    byte_count=source_stat.st_size,
                )
                continue
            try:
                raw_payload, opened_stat = _read_regular_file_without_following_symlinks(source)
            except OSError as error:
                errors.append({"path": relative.as_posix(), "error": sanitize_text(str(error))})
                continue
            replaced_before_capture = (
                opened_stat.st_dev != source_stat.st_dev or opened_stat.st_ino != source_stat.st_ino
            )
            source_stat = opened_stat
            if _CORE_DUMP_NAME.fullmatch(source.name) and raw_payload.startswith(b"\x7fELF"):
                _record_exclusion(
                    excluded,
                    excluded_entries,
                    "core_dump",
                    relative=relative,
                    entry_type="file",
                    byte_count=source_stat.st_size,
                )
                continue
            raw_digest = sha256(raw_payload).hexdigest()
            encoding = "binary"
            redacted = False
            artifact_payload = raw_payload
            try:
                decoded = raw_payload.decode("utf-8")
            except UnicodeDecodeError:
                if any(secret in raw_payload for secret in configured_secret_values):
                    _record_exclusion(
                        excluded,
                        excluded_entries,
                        "binary_contains_configured_secret",
                        relative=relative,
                        entry_type="file",
                        byte_count=source_stat.st_size,
                    )
                    continue
            else:
                sanitized = sanitize_text(decoded)
                artifact_payload = sanitized.encode("utf-8")
                encoding = "utf-8"
                redacted = artifact_payload != raw_payload
            artifact_digest = sha256(artifact_payload).hexdigest()
            object_path = objects_dir / artifact_digest[:2] / artifact_digest
            object_already_present = object_path.is_file()
            if not object_already_present:
                available_bytes = shutil.disk_usage(artifact_dir).free
                if object_store_bytes + len(artifact_payload) > object_budget:
                    _record_exclusion(
                        excluded,
                        excluded_entries,
                        "snapshot_object_budget",
                        relative=relative,
                        entry_type="file",
                        byte_count=source_stat.st_size,
                    )
                    continue
                if available_bytes - len(artifact_payload) < _SNAPSHOT_MIN_FREE_BYTES:
                    _record_exclusion(
                        excluded,
                        excluded_entries,
                        "artifact_disk_reserve",
                        relative=relative,
                        entry_type="file",
                        byte_count=source_stat.st_size,
                    )
                    continue
            _write_snapshot_object(object_path, artifact_payload)
            if not object_path.is_file():
                raise OSError(f"Snapshot object was not created: {object_path}")
            if not object_already_present:
                object_store_bytes += len(artifact_payload)
            try:
                final_stat = source.lstat()
            except OSError:
                unstable = True
            else:
                unstable = (
                    replaced_before_capture
                    or not stat.S_ISREG(final_stat.st_mode)
                    or final_stat.st_dev != source_stat.st_dev
                    or final_stat.st_ino != source_stat.st_ino
                    or final_stat.st_size != source_stat.st_size
                    or final_stat.st_mtime_ns != source_stat.st_mtime_ns
                )
            files.append(
                {
                    "path": relative.as_posix(),
                    "bytes": len(raw_payload),
                    "sha256": raw_digest,
                    "mode": oct(stat.S_IMODE(source_stat.st_mode)),
                    "mtime_ns": source_stat.st_mtime_ns,
                    "device": source_stat.st_dev,
                    "inode": source_stat.st_ino,
                    "link_count": source_stat.st_nlink,
                    "encoding": encoding,
                    "redacted": redacted,
                    "artifact_bytes": len(artifact_payload),
                    "artifact_sha256": artifact_digest,
                    "object": object_path.relative_to(artifact_dir).as_posix(),
                    "unstable_during_capture": unstable,
                }
            )

    manifest = {
        "schema_version": 2,
        "phase": phase,
        "captured_at": _utc_now(),
        "capture_elapsed_seconds": round(
            max(0.0, time.monotonic() - capture_started_monotonic),
            6,
        ),
        "workspace": sanitize_text(str(workspace)),
        "policy": {
            "text": "UTF-8 content is copied after credential redaction.",
            "binary": "Binary content is byte-exact unless it contains a configured secret.",
            "symlinks": "Link targets are recorded but never followed.",
            "objects": "Input and final snapshots share content-addressed objects.",
            "limits": {
                "maximum_file_bytes": _SNAPSHOT_MAX_FILE_BYTES,
                "object_budget_bytes": object_budget,
                "minimum_free_bytes": _SNAPSHOT_MIN_FREE_BYTES,
                "maximum_capture_seconds": _SNAPSHOT_MAX_CAPTURE_SECONDS,
            },
        },
        "capture_complete": capture_complete,
        "capture_stop_reason": capture_stop_reason,
        "totals": {
            "files": len(files),
            "source_bytes": sum(entry["bytes"] for entry in files),
            "artifact_bytes": sum(entry["artifact_bytes"] for entry in files),
            "directories": len(directories),
            "symlinks": len(symlinks),
            "redacted_files": sum(bool(entry["redacted"]) for entry in files),
            "binary_files": sum(entry["encoding"] == "binary" for entry in files),
            "unique_objects_referenced": len({entry["object"] for entry in files}),
            "excluded_entries": sum(item["entries"] for item in excluded.values()),
            "excluded_known_bytes": sum(item["bytes"] for item in excluded.values()),
            "errors": len(errors),
        },
        "directories": directories,
        "files": files,
        "symlinks": symlinks,
        "exclusion_summary": excluded,
        "excluded_entries": excluded_entries,
        "errors": errors,
    }
    manifest_path = artifact_dir / f"workspace/snapshots/{phase}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    _write_sanitized(
        manifest_path,
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )
    return manifest


def _copy_text_file(source: Path, destination: Path, *, remaining_bytes: int) -> int:
    if not source.is_file() or source.is_symlink():
        return 0
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_bytes = source.stat().st_size
        if source_bytes > _SNAPSHOT_MAX_FILE_BYTES or source_bytes > remaining_bytes:
            return 0
        if shutil.disk_usage(destination.parent).free - source_bytes < _SNAPSHOT_MIN_FREE_BYTES:
            return 0
        content = source.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    _write_sanitized(destination, content)
    return destination.stat().st_size


def _workspace_trace_files(workspace: Path) -> Iterable[tuple[Path, Path]]:
    logs_dir = workspace / "logs"
    if logs_dir.is_dir():
        for source in sorted(logs_dir.rglob("*")):
            if (
                source.is_file()
                and not source.is_symlink()
                and source.suffix.lower() in _TRACE_SUFFIXES
            ):
                yield source, Path("workspace/logs") / source.relative_to(logs_dir)
    for relative in _STATE_FILES:
        source = workspace / relative
        if source.is_file() and not source.is_symlink():
            yield source, Path("workspace") / relative


def _export_manager_history(workspace: Path, destination: Path) -> bool:
    database = workspace / ".neurico" / "hitl" / "manager" / "history.sqlite"
    if not database.is_file():
        return False
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                "SELECT sequence, record_id, record_type, speaker, content, "
                "created_at, metadata_json FROM conversation_records ORDER BY sequence"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8") as handle:
                written_bytes = 0
                for row in rows:
                    record = dict(row)
                    raw_metadata = record.pop("metadata_json", "{}")
                    try:
                        metadata = json.loads(str(raw_metadata))
                    except json.JSONDecodeError:
                        metadata = {}
                    record["metadata"] = metadata if isinstance(metadata, dict) else {}
                    rendered = json.dumps(record, ensure_ascii=False, sort_keys=True)
                    rendered_line = sanitize_text(rendered) + "\n"
                    line_bytes = len(rendered_line.encode("utf-8"))
                    if (
                        shutil.disk_usage(destination.parent).free - line_bytes
                        < _SNAPSHOT_MIN_FREE_BYTES
                    ):
                        truncation_reason = "artifact_disk_reserve"
                    elif written_bytes + line_bytes > _MANAGER_HISTORY_MAX_BYTES:
                        truncation_reason = "manager_history_export_budget"
                    else:
                        truncation_reason = None
                    if truncation_reason is not None:
                        truncation = json.dumps(
                            {
                                "record_type": "trace_truncation",
                                "reason": truncation_reason,
                                "maximum_bytes": _MANAGER_HISTORY_MAX_BYTES,
                            },
                            sort_keys=True,
                        )
                        handle.write(truncation + "\n")
                        break
                    handle.write(rendered_line)
                    written_bytes += line_bytes
            os.replace(temporary, destination)
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        temporary.unlink(missing_ok=True)
        return False
    return True


def _git_output(repository: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=_GIT_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout


def _write_git_provenance(repository: Path, destination: Path) -> None:
    commands = {
        "head.txt": ("rev-parse", "HEAD"),
        "status.txt": ("status", "--short"),
        "refs.txt": ("show-ref", "--head"),
        "recent-commits.txt": ("log", "--all", "-100", "--format=%H %P %aI %s"),
        "working-tree-stat.txt": ("diff", "--no-ext-diff", "--stat"),
        "working-tree-files.txt": ("diff", "--no-ext-diff", "--name-status"),
        "index-stat.txt": ("diff", "--cached", "--no-ext-diff", "--stat"),
        "index-files.txt": ("diff", "--cached", "--no-ext-diff", "--name-status"),
    }
    for name, arguments in commands.items():
        output = _git_output(repository, *arguments)
        if output is not None:
            _write_sanitized(destination / name, output)


def _artifact_manifest(artifact_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    objects_dir = artifact_dir / "workspace/snapshots/objects"
    for path in sorted(artifact_dir.rglob("*")):
        if not path.is_file() or path == artifact_dir / "manifest.json":
            continue
        try:
            object_relative = path.relative_to(objects_dir)
        except ValueError:
            object_relative = None
        if (
            object_relative is not None
            and len(object_relative.parts) == 2
            and _SHA256_NAME.fullmatch(path.name)
        ):
            digest = path.name
        else:
            digest = _sha256_file(path)
        entries.append(
            {
                "path": path.relative_to(artifact_dir).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": digest,
            }
        )
    return entries


def export_harbor_research_artifacts(
    *,
    workspace: Path,
    artifact_dir: Path,
    project_root: Path,
    instruction: str,
    run_configuration: dict[str, Any],
    started_at: str,
    elapsed_seconds: float,
    result: dict[str, Any] | None,
    error: BaseException | None,
    trace_capture_errors: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Export readable traces and a reproducible, secret-aware workspace snapshot."""
    workspace = workspace.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    capture_errors = list(trace_capture_errors or [])

    try:
        capture_workspace_snapshot(
            workspace=workspace,
            artifact_dir=artifact_dir,
            phase="final",
        )
    except Exception as snapshot_error:
        capture_errors.append(
            {
                "phase": "final",
                "type": type(snapshot_error).__name__,
                "message": sanitize_text(str(snapshot_error)),
            }
        )

    readable_trace_bytes = 0
    for source, relative_destination in _workspace_trace_files(workspace):
        readable_trace_bytes += _copy_text_file(
            source,
            artifact_dir / relative_destination,
            remaining_bytes=max(0, _READABLE_TRACE_BUDGET_BYTES - readable_trace_bytes),
        )
    _export_manager_history(
        workspace,
        artifact_dir / "workspace/.neurico/hitl/manager/history.jsonl",
    )
    _write_git_provenance(workspace, artifact_dir / "workspace/git")
    _write_git_provenance(project_root, artifact_dir / "adapter-source/git")
    _write_sanitized(artifact_dir / "instruction.txt", instruction)
    _write_sanitized(
        artifact_dir / "runtime.json",
        json.dumps(_runtime_inventory(), indent=2, sort_keys=True) + "\n",
    )

    run_record = {
        "schema_version": 2,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "elapsed_seconds": round(max(0.0, elapsed_seconds), 6),
        "instruction_sha256": sha256(instruction.encode("utf-8")).hexdigest(),
        "configuration": run_configuration,
        "trace_capture_errors": capture_errors,
        "result": result,
        "error": (
            {"type": type(error).__name__, "message": str(error)} if error is not None else None
        ),
    }
    _write_sanitized(
        artifact_dir / "run.json",
        json.dumps(run_record, indent=2, sort_keys=True, default=str) + "\n",
    )

    manifest = {
        "schema_version": 1,
        "generated_at": _utc_now(),
        "files": _artifact_manifest(artifact_dir),
    }
    (artifact_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
