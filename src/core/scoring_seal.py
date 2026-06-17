"""
Shared helpers for sealing hidden scoring files.

Rule-maker/scoring mode keeps scoring/interface.md visible but moves evaluator
internals out of the workspace while an agent is modifying experiment artifacts.
"""

from pathlib import Path
from typing import Optional
import shutil


SEALED_PATHS: list[str] = [
    "scoring/eval.py",
    "scoring/targets.json",
    "scoring/rule_maker_log.md",
    "data/.test/",
]


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

    print(f"🔒 Sealed {len(moved)} scoring files to {sealed_dir}:")
    for rel in moved:
        print(f"     - {rel}")
    print(
        f"   (manual recovery if orchestrator crashes: "
        f"move files from {sealed_dir} back into {work_dir})"
    )
    return sealed_dir


def unseal_scoring_files(work_dir: Path, sealed_dir: Optional[Path]) -> None:
    """
    Move hidden scoring files back to the workspace.

    Best-effort: logs failures but does not raise, so unseal problems do not
    mask the original agent failure.
    """
    if sealed_dir is None:
        return

    work_dir = Path(work_dir)
    sealed_dir = Path(sealed_dir)

    if not sealed_dir.exists():
        print(f"⚠️  Sealed dir disappeared: {sealed_dir}")
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
