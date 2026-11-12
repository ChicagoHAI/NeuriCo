"""Private, bounded, task-lifetime scratch retention for Harbor runs.

Scratch is deliberately separate from the sanitized public trace bundle.  It
retains raw mixed-authority output and uncertain generated files for later
inspection inside the task container, but it is never referenced by ACP
messages or files under ``/logs/artifacts``.  Harbor normally destroys this
state with the task container.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import BinaryIO
from typing import Any
from uuid import uuid4


DEFAULT_HARBOR_SCRATCH_ROOT = Path("/tmp/neurico-trace-scratch")

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SCRATCH_MAX_FILE_BYTES = 64 * 1024 * 1024
SCRATCH_BUDGET_BYTES = 512 * 1024 * 1024


def _safe_relative(path: Path) -> Path:
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Scratch paths must be safe relative paths")
    return path


@dataclass
class PrivateOutputSpool:
    """An unlinked parent-held stream spool used only while the child runs."""

    handle: BinaryIO
    retained_bytes: int = 0
    truncated: bool = False

    @classmethod
    def create(cls) -> "PrivateOutputSpool":
        handle = tempfile.TemporaryFile(mode="w+b", prefix="neurico-trace-output-")
        os.fchmod(handle.fileno(), 0o600)
        return cls(handle=handle)

    def append_output(self, payload: bytes) -> bool:
        try:
            allowance = max(0, SCRATCH_MAX_FILE_BYTES - self.retained_bytes)
            retained = payload[:allowance]
            if retained:
                self.handle.write(retained)
            self.retained_bytes += len(retained)
            if len(retained) != len(payload):
                self.truncated = True
            return len(retained) == len(payload)
        except Exception:
            self.truncated = True
            return False

    def transfer_to(self, scratch: "EphemeralRunScratch") -> None:
        try:
            self.handle.flush()
            self.handle.seek(0)
            while payload := self.handle.read(64 * 1024):
                scratch.append_output(payload)
            if self.truncated:
                scratch.mark_truncated(Path("streams/stdout-stderr.raw"))
        except Exception:
            return

    def close(self) -> None:
        try:
            self.handle.close()
        except Exception:
            pass


@dataclass
class EphemeralRunScratch:
    """One private scratch directory that lives until the task container exits."""

    run_id: str
    run_dir: Path
    total_bytes: int = 0
    _records: dict[str, dict[str, Any]] = field(default_factory=dict)
    _errors: Counter[str] = field(default_factory=Counter)

    @classmethod
    def create(
        cls,
        *,
        root: Path,
        run_id: str,
    ) -> "EphemeralRunScratch":
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("Harbor scratch run ID is invalid")
        root = Path(root)
        if not root.is_absolute():
            raise ValueError("Harbor scratch root must be absolute")
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        root_stat = root.lstat()
        if not stat.S_ISDIR(root_stat.st_mode):
            raise OSError("Harbor scratch root is not a directory")
        root.chmod(0o700)
        run_dir = root / run_id
        run_dir.mkdir(mode=0o700)
        run_dir.chmod(0o700)
        return cls(run_id=run_id, run_dir=run_dir)

    def _record_error(self, error: Exception) -> None:
        self._errors[type(error).__name__] += 1

    def _prepare_parent(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        current = destination.parent
        while current != self.run_dir:
            current.chmod(0o700)
            current = current.parent
        self.run_dir.chmod(0o700)

    def _append(self, relative: Path, payload: bytes) -> bool:
        try:
            relative = _safe_relative(relative)
            destination = self.run_dir / relative
            self._prepare_parent(destination)
            record = self._records.setdefault(
                relative.as_posix(),
                {"path": relative.as_posix(), "bytes": 0, "truncated": False},
            )
            current_bytes = int(record["bytes"])
            allowance = min(
                max(0, SCRATCH_MAX_FILE_BYTES - current_bytes),
                max(0, SCRATCH_BUDGET_BYTES - self.total_bytes),
            )
            retained = payload[:allowance]
            flags = (
                os.O_APPEND
                | os.O_CREAT
                | os.O_WRONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(destination, flags, 0o600)
            try:
                opened = os.fstat(descriptor)
                if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                    raise OSError("Harbor scratch destination is not a private regular file")
                os.fchmod(descriptor, 0o600)
                view = memoryview(retained)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise OSError("Harbor scratch write made no progress")
                    view = view[written:]
            finally:
                os.close(descriptor)
            record["bytes"] = current_bytes + len(retained)
            self.total_bytes += len(retained)
            if len(retained) != len(payload):
                record["truncated"] = True
            return len(retained) == len(payload)
        except Exception as error:
            self._record_error(error)
            return False

    def append_output(self, payload: bytes) -> bool:
        """Append raw combined child stdout/stderr to this run's private stream."""
        return self._append(Path("streams/stdout-stderr.raw"), payload)

    def mark_truncated(self, relative: Path) -> None:
        try:
            relative = _safe_relative(relative)
        except Exception as error:
            self._record_error(error)
            return
        record = self._records.get(relative.as_posix())
        if record is not None:
            record["truncated"] = True

    def preserve_workspace_file(
        self,
        relative: Path,
        payload: bytes,
        *,
        source_truncated: bool = False,
    ) -> bool:
        """Retain one generated, non-sealed file excluded from public export."""
        try:
            relative = _safe_relative(Path(relative))
        except Exception as error:
            self._record_error(error)
            return False
        scratch_relative = Path("workspace") / relative
        complete = self._append(scratch_relative, payload)
        if source_truncated:
            record = self._records.get(scratch_relative.as_posix())
            if record is not None:
                record["truncated"] = True
        return complete and not source_truncated

    def finalize(self) -> None:
        """Write private scratch metadata without publishing or deleting the run."""
        metadata = {
            "schema_version": 1,
            "run_id": self.run_id,
            "lifetime": "task_container",
            "visibility": "private_ephemeral_scratch",
            "limits": {
                "per_file_bytes": SCRATCH_MAX_FILE_BYTES,
                "total_bytes": SCRATCH_BUDGET_BYTES,
            },
            "retained_bytes": self.total_bytes,
            "files": [self._records[path] for path in sorted(self._records)],
            "errors": [
                {"type": error_type, "count": count}
                for error_type, count in sorted(self._errors.items())
            ],
        }
        temporary = self.run_dir / f".scratch.json.tmp-{uuid4().hex}"
        destination = self.run_dir / "scratch.json"
        try:
            payload = (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode("utf-8")
            descriptor = os.open(
                temporary,
                os.O_CREAT
                | os.O_EXCL
                | os.O_WRONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                os.fchmod(descriptor, 0o600)
                view = memoryview(payload)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise OSError("Harbor scratch metadata write made no progress")
                    view = view[written:]
            finally:
                os.close(descriptor)
            os.replace(temporary, destination)
            destination.chmod(0o600)
        except Exception as error:
            self._record_error(error)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
