"""Persistent, redacted research artifacts for Harbor trials."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
from typing import Any, Iterable

from core.security import sanitize_text


DEFAULT_HARBOR_ARTIFACT_DIR = Path("/logs/artifacts/neurico")

_TRACE_SUFFIXES = frozenset({".json", ".jsonl", ".log", ".md", ".txt", ".yaml", ".yml"})
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


def _copy_text_file(source: Path, destination: Path) -> bool:
    if not source.is_file() or source.is_symlink():
        return False
    try:
        content = source.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    _write_sanitized(destination, content)
    return True


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
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                "SELECT sequence, record_id, record_type, speaker, content, "
                "created_at, metadata_json FROM conversation_records ORDER BY sequence"
            ).fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return False

    rendered: list[str] = []
    for row in rows:
        record = dict(row)
        raw_metadata = record.pop("metadata_json", "{}")
        try:
            metadata = json.loads(str(raw_metadata))
        except json.JSONDecodeError:
            metadata = {}
        record["metadata"] = metadata if isinstance(metadata, dict) else {}
        rendered.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
    _write_sanitized(destination, "\n".join(rendered) + ("\n" if rendered else ""))
    return True


def _git_output(repository: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout


def _write_git_provenance(repository: Path, destination: Path) -> None:
    commands = {
        "head.txt": ("rev-parse", "HEAD"),
        "status.txt": ("status", "--short"),
        "recent-commits.txt": ("log", "-20", "--format=%H %aI %s"),
    }
    for name, arguments in commands.items():
        output = _git_output(repository, *arguments)
        if output is not None:
            _write_sanitized(destination / name, output)


def _artifact_manifest(artifact_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(artifact_dir.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        payload = path.read_bytes()
        entries.append(
            {
                "path": path.relative_to(artifact_dir).as_posix(),
                "bytes": len(payload),
                "sha256": sha256(payload).hexdigest(),
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
) -> dict[str, Any]:
    """Export selected NeuriCo traces without copying credentials or live control files."""
    workspace = workspace.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    for source, relative_destination in _workspace_trace_files(workspace):
        _copy_text_file(source, artifact_dir / relative_destination)
    _export_manager_history(
        workspace,
        artifact_dir / "workspace/.neurico/hitl/manager/history.jsonl",
    )
    _write_git_provenance(workspace, artifact_dir / "workspace/git")
    _write_git_provenance(project_root, artifact_dir / "adapter-source/git")
    _write_sanitized(artifact_dir / "instruction.txt", instruction)

    run_record = {
        "schema_version": 1,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "elapsed_seconds": round(max(0.0, elapsed_seconds), 6),
        "instruction_sha256": sha256(instruction.encode("utf-8")).hexdigest(),
        "configuration": run_configuration,
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
