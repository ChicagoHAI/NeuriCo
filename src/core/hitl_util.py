"""Small filesystem and serialization primitives shared by HITL stores."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
import uuid


def utc_now(*, timespec: str = "auto", zulu: bool = True) -> str:
    value = datetime.now(timezone.utc).isoformat(timespec=timespec)
    return value.replace("+00:00", "Z") if zulu else value


def fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(Path(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, payload: bytes, *, fsync_parent: bool = True) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        if fsync_parent:
            fsync_directory(target.parent)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
    fsync_parent: bool = True,
) -> None:
    atomic_write_bytes(Path(path), content.encode(encoding), fsync_parent=fsync_parent)


def atomic_write_json(
    path: Path,
    payload: Any,
    *,
    ensure_ascii: bool = False,
    indent: int | None = 2,
    trailing_newline: bool = True,
    fsync_parent: bool = True,
) -> None:
    content = json.dumps(payload, ensure_ascii=ensure_ascii, indent=indent)
    if trailing_newline:
        content += "\n"
    atomic_write_text(path, content, fsync_parent=fsync_parent)


def read_jsonl_objects(path: Path, *, record_label: str = "JSONL record") -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    records: list[dict[str, Any]] = []
    with source.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid {record_label} at line {line_number}.") from exc
            if not isinstance(record, dict):
                raise RuntimeError(f"{record_label} at line {line_number} must be an object.")
            records.append(record)
    return records


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
