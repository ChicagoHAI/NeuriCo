"""
Shared helpers for sealing hidden scoring files.

Rule-maker/scoring mode keeps scoring/interface.md visible but moves evaluator
internals out of the workspace while an agent is modifying experiment artifacts.
"""

from pathlib import Path
from typing import Any, Optional
import hashlib
import json
import shutil


SEALED_PATHS: list[str] = [
    "scoring/eval.py",
    "scoring/targets.json",
    "scoring/rule_maker_log.md",
    "data/.test/",
]
SEALED_REQUIRED_PATHS = ("scoring/eval.py", "scoring/targets.json")
SEALED_MANIFEST_NAME = "evaluator_manifest.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    (sealed_dir / SEALED_MANIFEST_NAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def verify_sealed_scoring_manifest(sealed_dir: Path) -> str:
    """Validate the complete immutable evaluator payload and return its digest."""
    sealed_dir = Path(sealed_dir)
    manifest_path = sealed_dir / SEALED_MANIFEST_NAME
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
    for relative in SEALED_REQUIRED_PATHS:
        if relative not in entries:
            raise RuntimeError(f"Sealed evaluator manifest is missing required {relative}.")
    for relative, expected in entries.items():
        if not isinstance(relative, str) or not isinstance(expected, dict):
            raise RuntimeError("Invalid sealed evaluator manifest entry.")
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


def seal_scoring_files(work_dir: Path) -> Optional[Path]:
    """
    Move hidden scoring files out of the workspace.

    Returns the sealed directory path when files were moved, otherwise None.
    """
    work_dir = Path(work_dir)
    sealed_dir = sealed_dir_for(work_dir)
    sealed_dir.mkdir(parents=True, exist_ok=True)

    moved = []
    for rel in SEALED_PATHS:
        normalized_rel = rel.rstrip("/")
        src = work_dir / normalized_rel
        if not src.exists():
            continue
        dst = sealed_dir / normalized_rel
        if dst.exists():
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moved.append(rel)

    if not moved:
        try:
            sealed_dir.rmdir()
            sealed_dir.parent.rmdir()
        except OSError:
            pass
        print("🔒 Nothing to seal (rule_maker outputs not found).")
        return None

    _write_manifest(sealed_dir, moved)

    print(f"🔒 Sealed {len(moved)} scoring files to {sealed_dir}:")
    for rel in moved:
        print(f"     - {rel}")
    print(
        f"   (manual recovery if orchestrator crashes: "
        f"move files from {sealed_dir} back into {work_dir})"
    )
    return sealed_dir


def unseal_scoring_files(
    work_dir: Path,
    sealed_dir: Optional[Path],
    *,
    strict: bool = False,
) -> None:
    """
    Move hidden scoring files back to the workspace.

    The normal pipeline cleanup path remains best-effort so it does not mask an
    earlier worker failure. Runtime-owned scoring handoffs pass ``strict=True``
    and fail closed rather than scoring against partially restored inputs.
    """
    if sealed_dir is None:
        return

    work_dir = Path(work_dir)
    sealed_dir = Path(sealed_dir)

    if not sealed_dir.exists():
        message = f"Sealed dir disappeared: {sealed_dir}"
        if strict:
            raise RuntimeError(message)
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
        if strict:
            raise RuntimeError("Could not fully unseal scoring files: " + "; ".join(errors))
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
