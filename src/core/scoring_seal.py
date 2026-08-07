"""
Shared helpers for sealing hidden scoring files.

Rule-maker/scoring mode keeps scoring/interface.md visible but moves evaluator
internals out of the workspace while an agent is modifying experiment artifacts.
"""

from pathlib import Path
from typing import Any, Optional
import hashlib
import json
import os
import shutil
import uuid

from core.hitl_util import sha256_file as _sha256_file

SEALED_PATHS: list[str] = [
    "scoring/eval.py",
    "scoring/targets.json",
    "scoring/rule_maker_log.md",
    # Written by the eval_verifier when the idea declares an evaluation
    # contract; quotes eval.py internals as evidence, so it must be hidden
    # from the runner alongside them. Absent files are skipped by the seal.
    "scoring/verification.json",
    "data/.test/",
]
SEALED_REQUIRED_PATHS = ("scoring/eval.py", "scoring/targets.json")
SEALED_MANIFEST_NAME = "evaluator_manifest.json"


def _manifest_entry(path: Path) -> dict[str, Any]:
    stats = path.lstat()
    if path.is_symlink():
        raise RuntimeError(f"Sealed evaluator payload cannot contain symlink: {path}")
    if path.is_file():
        return {"kind": "file", "sha256": _sha256_file(path), "size": stats.st_size}
    if path.is_dir():
        files: list[tuple[str, str]] = []
        for child in sorted(path.rglob("*")):
            if child.is_symlink():
                raise RuntimeError(f"Sealed evaluator payload cannot contain symlink: {child}")
            if child.is_file():
                files.append((child.relative_to(path).as_posix(), _sha256_file(child)))
        digest = hashlib.sha256(
            json.dumps(files, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        return {"kind": "directory", "sha256": digest, "files": len(files)}
    raise RuntimeError(f"Unsupported sealed evaluator payload entry: {path}")


def _write_manifest(sealed_dir: Path, moved: list[str]) -> None:
    entries = {
        relative.rstrip("/"): _manifest_entry(sealed_dir / relative.rstrip("/"))
        for relative in moved
    }
    payload = {"version": 1, "required": list(SEALED_REQUIRED_PATHS), "entries": entries}
    manifest_path = sealed_dir / SEALED_MANIFEST_NAME
    with manifest_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_manifest(sealed_dir: Path) -> tuple[bytes, dict[str, dict[str, Any]]]:
    manifest_path = Path(sealed_dir) / SEALED_MANIFEST_NAME
    try:
        raw = manifest_path.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Missing or unreadable sealed evaluator manifest.") from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise RuntimeError("Invalid sealed evaluator manifest version.")
    entries = payload.get("entries")
    required = payload.get("required")
    if not isinstance(entries, dict) or required != list(SEALED_REQUIRED_PATHS):
        raise RuntimeError("Invalid sealed evaluator manifest structure.")
    if any(
        not isinstance(relative, str) or not isinstance(entry, dict)
        for relative, entry in entries.items()
    ):
        raise RuntimeError("Invalid sealed evaluator manifest entry.")
    for relative in SEALED_REQUIRED_PATHS:
        if relative not in entries:
            raise RuntimeError(f"Sealed evaluator manifest is missing required {relative}.")
    return raw, entries


def _fsync_directory(path: Path) -> None:
    """Persist a directory entry where the current platform permits it."""
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _fsync_tree(path: Path) -> None:
    """Flush the staged evaluator payload before publishing its generation."""
    for item in path.rglob("*"):
        if not item.is_file() or item.is_symlink():
            continue
        try:
            with item.open("rb") as handle:
                os.fsync(handle.fileno())
        except OSError:
            # The subsequent manifest verification remains authoritative on
            # platforms that do not permit syncing this file type.
            continue


def verify_sealed_scoring_manifest(sealed_dir: Path) -> str:
    """Validate the complete immutable evaluator payload and return its digest."""
    sealed_dir = Path(sealed_dir)
    raw, entries = _read_manifest(sealed_dir)
    for relative, expected in entries.items():
        actual = _manifest_entry(sealed_dir / relative)
        if actual != expected:
            raise RuntimeError(f"Sealed evaluator payload changed: {relative}")
    return hashlib.sha256(raw).hexdigest()


def sealed_dir_for(work_dir: Path) -> Path:
    """
    Return the sibling directory where sealed scoring files live.

    For a workspace at <workspaces>/<name>/, the sealed directory is at
    <workspaces>/.scoring_sealed/<name>/.
    """
    work_dir = Path(work_dir)
    return work_dir.parent / ".scoring_sealed" / work_dir.name


def protocol_store_dir_for(work_dir: Path) -> Path:
    """
    Return the sibling directory holding the last VALIDATED scoring protocol.

    For a workspace at <workspaces>/<name>/, the store is at
    <workspaces>/.protocol_store/<name>/. Unlike .scoring_sealed (a transient
    relocation, removed by every unseal), this store persists across runs so a
    later regeneration can extend the prior protocol instead of starting
    fresh. It is written only by trusted runner code at validation time; like
    the sealed dir it is outside the workspace but on the same mount (the
    full isolation work is tracked separately).
    """
    work_dir = Path(work_dir)
    return work_dir.parent / ".protocol_store" / work_dir.name


def persist_validated_protocol(work_dir: Path) -> None:
    """Copy the workspace's validated scoring protocol into the durable store.

    Called when a (re)built protocol has passed its gates and the baseline is
    accepted, i.e. the workspace copy is trusted at this moment. Overwrites
    any previous store contents.
    """
    work_dir = Path(work_dir)
    store = protocol_store_dir_for(work_dir) / "scoring"
    store.mkdir(parents=True, exist_ok=True)
    for name in ("eval.py", "targets.json", "interface.md"):
        src = work_dir / "scoring" / name
        if not src.is_file():
            continue
        tmp = store / (name + ".tmp")
        shutil.copy2(src, tmp)
        os.replace(tmp, store / name)


def _public_sealed_paths(work_dir: Path) -> list[str]:
    """Return evaluator paths that must never reappear in a worker workspace."""
    return [
        relative.rstrip("/")
        for relative in SEALED_PATHS
        if (Path(work_dir) / relative.rstrip("/")).exists()
    ]


def remove_public_sealed_paths(work_dir: Path) -> None:
    """Remove evaluator internals that leaked into a public worker workspace."""
    for relative in _public_sealed_paths(work_dir):
        path = Path(work_dir) / relative
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def _public_payload_matches_sealed_manifest(work_dir: Path, sealed_dir: Path) -> bool:
    """Return whether public evaluator remnants exactly match the sealed payload.

    A matching public payload can only arise when runtime was interrupted after
    publishing the sealed generation but before deleting the originals.  It is
    safe to remove those remnants; any mismatch remains an integrity violation.
    """
    try:
        manifest = json.loads((sealed_dir / SEALED_MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    entries = manifest.get("entries") if isinstance(manifest, dict) else None
    if not isinstance(entries, dict):
        return False
    public_paths = _public_sealed_paths(work_dir)
    if not public_paths:
        return False
    return all(
        relative in entries and _manifest_entry(Path(work_dir) / relative) == entries[relative]
        for relative in public_paths
    )


def seal_scoring_files(work_dir: Path, *, immutable: bool = False) -> Optional[Path]:
    """
    Move hidden scoring files out of the workspace.

    Returns the sealed directory path when files were moved, otherwise None.

    ``immutable=True`` is the HITL AutoResearch handoff.  After rule maker
    has produced and sealed an evaluator, later experiment workers must never
    be able to replace it through a subsequent seal operation.  In that mode a
    valid existing manifest is reused only when every evaluator path remains
    absent from the public workspace.
    """
    work_dir = Path(work_dir)
    sealed_dir = sealed_dir_for(work_dir)
    sealed_parent = sealed_dir.parent
    sealed_parent.mkdir(parents=True, exist_ok=True)

    # A process can die before a staged generation becomes active.  Staging is
    # never authoritative, so it is always safe to discard on the next call.
    for staging in sealed_parent.glob(f".{sealed_dir.name}.staging-*"):
        if staging.is_dir():
            shutil.rmtree(staging, ignore_errors=True)

    manifest_path = sealed_dir / SEALED_MANIFEST_NAME
    if immutable and sealed_dir.exists():
        if not manifest_path.is_file():
            raise RuntimeError(
                "HITL evaluator integrity violation: runtime found an incomplete sealed evaluator "
                "store. Restore or rerun rule maker instead of resealing public workspace files."
            )
        verify_sealed_scoring_manifest(sealed_dir)
        leaked = _public_sealed_paths(work_dir)
        if leaked:
            if _public_payload_matches_sealed_manifest(work_dir, sealed_dir):
                remove_public_sealed_paths(work_dir)
                return sealed_dir
            raise RuntimeError(
                "HITL evaluator integrity violation: public worker workspace contains "
                "sealed evaluator path(s): " + ", ".join(leaked)
            )
        return sealed_dir

    staging_dir = sealed_parent / f".{sealed_dir.name}.staging-{uuid.uuid4().hex}"
    staging_dir.mkdir(parents=True, exist_ok=False)
    copied: list[str] = []
    public_copied: list[str] = []

    # A best-effort unseal can restore only part of a generation. Reconcile
    # verified leftovers into staging before overlaying the public files so an
    # optional artifact cannot be deleted by the next non-immutable reseal.
    if sealed_dir.exists():
        _, existing_entries = _read_manifest(sealed_dir)
        supported_paths = {relative.rstrip("/") for relative in SEALED_PATHS}
        unsupported = sorted(set(existing_entries) - supported_paths)
        if unsupported:
            raise RuntimeError(
                "Sealed evaluator manifest contains unsupported path(s): " + ", ".join(unsupported)
            )
        for relative, expected in existing_entries.items():
            sealed_source = sealed_dir / relative
            public_source = work_dir / relative
            if sealed_source.exists():
                if _manifest_entry(sealed_source) != expected:
                    raise RuntimeError(f"Sealed evaluator payload changed: {relative}")
                destination = staging_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if sealed_source.is_dir() and not sealed_source.is_symlink():
                    shutil.copytree(sealed_source, destination, symlinks=True)
                else:
                    shutil.copy2(sealed_source, destination, follow_symlinks=False)
                copied.append(relative)
            elif not public_source.exists():
                raise RuntimeError(f"Cannot reconcile sealed evaluator payload missing {relative}.")

    for rel in SEALED_PATHS:
        normalized_rel = rel.rstrip("/")
        src = work_dir / normalized_rel
        if not src.exists():
            continue
        dst = staging_dir / normalized_rel
        if dst.exists():
            if dst.is_dir() and not dst.is_symlink():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir() and not src.is_symlink():
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst, follow_symlinks=False)
        if normalized_rel not in copied:
            copied.append(normalized_rel)
        public_copied.append(normalized_rel)

    if not copied:
        try:
            staging_dir.rmdir()
        except OSError:
            pass
        print("🔒 Nothing to seal (rule_maker outputs not found).")
        return None

    _fsync_tree(staging_dir)
    _write_manifest(staging_dir, copied)
    verify_sealed_scoring_manifest(staging_dir)
    _fsync_directory(staging_dir)

    if sealed_dir.exists():
        # Non-HITL callers retain the historic reseal behavior. HITL immutable
        # callers returned above after validating the active generation.
        shutil.rmtree(sealed_dir)
    os.replace(staging_dir, sealed_dir)
    _fsync_directory(sealed_parent)

    # The active generation is durable before public evaluator inputs vanish.
    for rel in public_copied:
        source = work_dir / rel.rstrip("/")
        if source.is_dir() and not source.is_symlink():
            shutil.rmtree(source)
        else:
            source.unlink()

    print(f"🔒 Sealed {len(copied)} scoring files to {sealed_dir}:")
    for rel in copied:
        print(f"     - {rel}")
    print(
        f"   (manual recovery if orchestrator crashes: "
        f"move files from {sealed_dir} back into {work_dir})"
    )
    return sealed_dir


def unseal_scoring_files(
    work_dir: Path,
    sealed_dir: Optional[Path],
) -> None:
    """Move hidden scoring files back without masking an earlier worker failure."""
    if sealed_dir is None:
        return

    work_dir = Path(work_dir)
    sealed_dir = Path(sealed_dir)

    if not sealed_dir.exists():
        message = f"Sealed dir disappeared: {sealed_dir}"
        print(f"⚠️  {message}")
        return

    restored = []
    errors = []
    for rel in SEALED_PATHS:
        normalized_rel = rel.rstrip("/")
        src = sealed_dir / normalized_rel
        if not src.exists():
            continue
        dst = work_dir / normalized_rel
        try:
            if dst.exists():
                if dst.is_dir():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            restored.append(rel)
        except OSError as e:
            errors.append(f"{rel}: {e}")

    if restored:
        print(f"🔓 Restored {len(restored)} scoring files from {sealed_dir}")

    if errors:
        print(f"⚠️  Unseal errors -- sealed dir kept at {sealed_dir} for manual recovery:")
        for error in errors:
            print(f"     - {error}")
        return

    try:
        (sealed_dir / SEALED_MANIFEST_NAME).unlink(missing_ok=True)
        has_files = (
            any(path.is_file() for path in sealed_dir.rglob("*")) if sealed_dir.exists() else False
        )
        if sealed_dir.exists() and not has_files:
            shutil.rmtree(sealed_dir)
            parent = sealed_dir.parent
            try:
                parent.rmdir()
            except OSError:
                pass
        elif has_files:
            print(
                f"ℹ️  Unexpected files remain in {sealed_dir}; leaving the directory for inspection."
            )
    except OSError as e:
        print(f"⚠️  Could not clean up {sealed_dir}: {e}")
