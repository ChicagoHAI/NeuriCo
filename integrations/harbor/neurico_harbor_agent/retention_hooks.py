"""Save only records missing from native logs or lost at destructive boundaries."""

from __future__ import annotations

import io
from contextlib import nullcontext
import json
import os
from pathlib import Path
import tarfile
import tempfile
import time
from typing import Any
from uuid import uuid4
from datetime import datetime, timezone

from core.hitl_git import run_git
from core.hitl_manager_history import HitlManagerHistory
from core.trace_retention import set_trace_recorder

from .artifacts import _is_credential_path
from .internal_traces import InternalTraceArchive, _RESEARCH_ROOTS, private_trace_redactor


TRACE_DIRECTORY_ENV = "NEURICO_RESEARCH_TRACE_DIR"


class HarborRetentionHooks:
    """Adapter-owned file retention; the core only reports existing boundaries."""

    def __init__(self, archive: InternalTraceArchive):
        self.archive = archive
        self.started: dict[str, float] = {}

    def _record(self, relative: Path, value: Any) -> None:
        from .artifacts import _safe_text_payload

        raw = (json.dumps(value, ensure_ascii=False, default=str, indent=2) + "\n").encode()
        safe = _safe_text_payload(raw, ".json", self.archive.redactor)
        if safe is None:
            raise ValueError("retention record could not be sanitized")
        self.archive._publish(relative, safe[0], "retention", sanitized=safe[1])

    def __call__(self, event: str, fields: dict[str, Any]) -> str | None:
        identity = fields.get("invocation_id")
        if event == "invocation_start":
            identity = f"{fields['kind']}-{uuid4().hex}"
            self.started[identity] = time.monotonic()
            self._record(Path("invocations") / identity / "input.json", {
                **fields, "recorded_at": datetime.now(timezone.utc).isoformat(),
            })
            if fields.get("work_dir"):
                # Existing runtime state supplies stage and worker-request identity.
                self.archive.tree(Path(fields["work_dir"]) / ".neurico/hitl/runtime.json",
                                  Path("invocations") / identity / "runtime.json", "runtime")
        elif event == "invocation_finish" and identity:
            for key in ("log_file", "transcript_file"):
                if fields.get(key):
                    source = Path(fields[key])
                    self.archive.tree(source, Path("invocations") / identity / source.name, "worker")
            self._record(Path("invocations") / identity / "outcome.json", {
                **fields, "elapsed_seconds": time.monotonic() - self.started.pop(identity),
            })
        elif event in {"provider_input", "provider_output"} and identity:
            self._record(Path("invocations") / identity / f"{event}.json", fields)
        elif event == "rollback_request":
            boundary = fields["boundary"]
            prefix = Path("snapshots") / f"rollback-{boundary['hitl_snapshot_commit']}"
            # The request mutation happens before restoration; keep its prior
            # control record without changing worker cancellation ordering.
            self._record(prefix / "request.json", fields)
            self.archive.tree(Path(fields["work_dir"]) / ".neurico/hitl/runtime.json",
                              prefix / "runtime-before-request.json", "runtime")
        elif event == "before_restore":
            self._before_restore(Path(fields["work_dir"]), fields["record"])
        elif event == "state_checkpoint":
            self._checkpoint(Path(fields["work_dir"]), fields)
        if self.archive.gaps:
            self._record(Path("retention-gaps.json"), self.archive.gaps)
        return identity

    def _before_restore(self, workspace: Path, record: dict[str, Any]) -> None:
        boundary = record["boundary"]
        prefix = Path("snapshots") / f"rollback-{boundary['hitl_snapshot_commit']}"
        if (self.archive.directory / prefix / "captured.json").is_file():
            return  # A replay must not replace evidence with already-restored state.
        manager = workspace / ".neurico/hitl/manager"
        lock = (HitlManagerHistory.snapshot_lock(manager)
                if (manager / "history.sqlite").is_file() else nullcontext())
        with lock:
            for name in sorted(_RESEARCH_ROOTS):
                self.archive.tree(workspace / name, prefix / name, "rollback")
        # Retain changed solution files, reusing the checkpoint's own comparison.
        changed = run_git(workspace, "diff", "--name-only", "-z",
                          boundary["checkpoint_sha"], text=False).stdout
        untracked = run_git(workspace, "ls-files", "--others", "--exclude-standard", "-z",
                            text=False).stdout
        for name in sorted(set((changed + untracked).split(b"\0")) - {b""}):
            relative = Path(os.fsdecode(name))
            if relative.parts[0] in _RESEARCH_ROOTS or _is_credential_path(relative, self.archive.redactor):
                continue
            source = workspace / relative
            if source.is_file():
                self.archive.copy_file(source, prefix / relative, "rollback")
        self._record(prefix / "captured.json", record)

    def _checkpoint(self, workspace: Path, record: dict[str, Any]) -> None:
        prefix = Path("snapshots") / f"state-{record['commit_sha']}"
        if (self.archive.directory / prefix / "checkpoint.json").is_file():
            return
        # Export the existing private state checkpoint, not the repository's
        # object database. Do not create a checkpoint or move a research ref.
        payload = run_git(workspace, "archive", "--format=tar", record["commit_sha"],
                          text=False).stdout
        with tempfile.TemporaryDirectory(prefix="neurico-retained-state-") as temp:
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
                for member in archive:
                    relative = Path(member.name)
                    if not member.isfile() or relative.is_absolute() or ".." in relative.parts:
                        continue
                    if _is_credential_path(relative, self.archive.redactor):
                        continue
                    handle = archive.extractfile(member)
                    if handle is None:
                        continue
                    source = Path(temp) / relative
                    source.parent.mkdir(parents=True, exist_ok=True)
                    with handle:
                        source.write_bytes(handle.read())
                    self.archive.copy_file(source, prefix / relative, "checkpoint")
        self._record(prefix / "checkpoint.json", record)


def install_retention_hooks() -> None:
    destination = os.environ.get(TRACE_DIRECTORY_ENV)
    if not destination:
        return
    directory = Path(destination)
    if not directory.is_absolute() or not directory.is_dir():
        raise ValueError("The parent must create the private trace directory before launch")
    credential = Path(os.environ["CODEX_HOME"]) / "auth.json"
    redactor = private_trace_redactor(os.environ,
        credential_file=credential if credential.is_file() else None)
    set_trace_recorder(HarborRetentionHooks(InternalTraceArchive(directory, redactor)))
