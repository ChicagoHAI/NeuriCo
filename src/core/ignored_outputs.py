"""
Snapshot and restore git-ignored experiment outputs around AutoResearch attempts.

AutoResearch rolls a rejected attempt back with `git reset --hard`, which only
restores tracked files. Experiment outputs that the workspace .gitignore
excludes (model checkpoints such as ``*.pt`` / ``*.safetensors``, saved
predictions, ...) are left exactly as the rejected attempt wrote them. When the
sealed scorer reads those files, the next attempt can be scored on the rejected
attempt's outputs instead of the current best's.

Before each attempt we copy the current best's ignored outputs into
``.neurico/ignored_outputs_snapshot/`` (keyed by the parent checkpoint SHA, so
repeated attempts from the same parent reuse one snapshot). After a rejected or
interrupted attempt, every snapshotted file that was modified or deleted is
copied back. Files the attempt newly created are left alone: the parent's
tracked code and manifests never reference them.

Large shared resources (virtualenvs, base models, datasets, caches) and
AutoResearch's own private paths are never snapshotted, and the total snapshot
size is capped (``NEURICO_IGNORED_OUTPUT_SNAPSHOT_MAX_GB``, default 20 GB).
Over the cap the snapshot is skipped with a warning rather than filling the disk.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, Optional

SNAPSHOT_RELATIVE_DIR = Path(".neurico") / "ignored_outputs_snapshot"
SNAPSHOT_PATTERN = f"{SNAPSHOT_RELATIVE_DIR.as_posix()}/"
MANIFEST_NAME = "manifest.json"
FILES_DIRNAME = "files"
DEFAULT_MAX_BYTES = 20 * 1024**3

# Ignored directories that hold tool state at any depth.
SKIP_DIR_NAMES = frozenset({
    ".git", ".venv", "venv", "env", "ENV", "node_modules", "__pycache__",
    ".cache", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".ipynb_checkpoints",
    "wandb", "mlruns", "lightning_logs", "hf_cache", ".hf_cache", "huggingface",
    ".huggingface", "torch_cache", ".torch", ".triton", ".nv",
})
# Top-level workspace directories that hold shared resources or NeuriCo state,
# not attempt outputs (base models, datasets, agent/tool state, logs, papers).
SKIP_TOP_LEVEL = frozenset({
    "models", "datasets", "data", ".claude", ".gemini", ".codex",
    ".neurico", ".scoring_sealed", "logs", "paper", "paper_draft", "paper_examples",
    "dsi-slurm-artifacts",
})
SKIP_FILE_PATTERNS = ("*.pyc", "*.pyo", "*.log", "*.swp", "*.swo", "*~", ".DS_Store")


def _max_bytes() -> int:
    raw = os.environ.get("NEURICO_IGNORED_OUTPUT_SNAPSHOT_MAX_GB")
    if not raw:
        return DEFAULT_MAX_BYTES
    try:
        return int(float(raw) * 1024**3)
    except ValueError:
        return DEFAULT_MAX_BYTES


def _skipped(rel: str, extra_patterns: Iterable[str]) -> bool:
    parts = rel.rstrip("/").split("/")
    if parts[0] in SKIP_TOP_LEVEL and (len(parts) > 1 or rel.endswith("/")):
        return True
    dir_parts = parts if rel.endswith("/") else parts[:-1]
    if any(part in SKIP_DIR_NAMES for part in dir_parts):
        return True
    name = parts[-1]
    if any(fnmatch.fnmatch(name, pattern) for pattern in SKIP_FILE_PATTERNS):
        return True
    for pattern in extra_patterns:
        if pattern.endswith("/"):
            if rel == pattern or rel.startswith(pattern):
                return True
        elif fnmatch.fnmatch(rel, pattern):
            return True
    return False


def list_ignored_outputs(work_dir: Path, extra_skip_patterns: Iterable[str] = ()) -> list[str]:
    """Return workspace-relative paths of git-ignored output files worth snapshotting."""
    work_dir = Path(work_dir)
    extra = tuple(extra_skip_patterns) + (SNAPSHOT_PATTERN,)
    try:
        out = subprocess.run(
            ["git", "ls-files", "--others", "--ignored", "--exclude-standard",
             "--directory", "-z"],
            cwd=work_dir, check=True, capture_output=True, text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []

    files: set[str] = set()
    for entry in filter(None, out.split("\0")):
        if _skipped(entry, extra):
            continue
        path = work_dir / entry
        if entry.endswith("/") or path.is_dir():
            for root, dirs, names in os.walk(path):
                dirs[:] = [d for d in dirs if d not in SKIP_DIR_NAMES]
                for name in names:
                    rel = (Path(root) / name).relative_to(work_dir).as_posix()
                    if not _skipped(rel, extra) and (Path(root) / name).is_file():
                        files.add(rel)
        elif path.is_file() and not path.is_symlink():
            files.add(entry)
    return sorted(files)


def _signature(path: Path) -> list[int]:
    st = path.stat()
    return [st.st_size, st.st_mtime_ns]


def _snapshot_dir(work_dir: Path) -> Path:
    return Path(work_dir) / SNAPSHOT_RELATIVE_DIR


def _read_manifest(work_dir: Path) -> Optional[dict]:
    manifest_path = _snapshot_dir(work_dir) / MANIFEST_NAME
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def ensure_ignored_outputs_snapshot(
    work_dir: Path, parent_sha: str, extra_skip_patterns: Iterable[str] = ()
) -> Optional[dict]:
    """Snapshot the parent checkpoint's ignored outputs unless already snapshotted.

    Returns the manifest, or None when there is nothing to snapshot or the
    snapshot was skipped (over the size cap or an I/O error). Never raises.
    """
    work_dir = Path(work_dir)
    existing = _read_manifest(work_dir)
    if existing and existing.get("parent_sha") == parent_sha and existing.get("complete"):
        return existing

    snap = _snapshot_dir(work_dir)
    shutil.rmtree(snap, ignore_errors=True)
    try:
        rels = list_ignored_outputs(work_dir, extra_skip_patterns)
        if not rels:
            return None
        total = sum((work_dir / rel).stat().st_size for rel in rels)
        limit = _max_bytes()
        if total > limit:
            print(
                f"⚠️  Not snapshotting {len(rels)} git-ignored output files "
                f"({total / 1024**3:.1f} GB > {limit / 1024**3:.1f} GB cap). A rejected "
                "attempt may leave its ignored outputs (e.g. checkpoints) on disk. "
                "Raise NEURICO_IGNORED_OUTPUT_SNAPSHOT_MAX_GB to enable restoring them."
            )
            return None
        files_root = snap / FILES_DIRNAME
        entries = {}
        for rel in rels:
            source = work_dir / rel
            target = files_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            entries[rel] = _signature(source)
        manifest = {
            "parent_sha": parent_sha,
            "complete": True,
            "total_bytes": total,
            "files": entries,
        }
        (snap / MANIFEST_NAME).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        print(
            f"📦 Snapshotted {len(entries)} git-ignored output files "
            f"({total / 1024**2:.0f} MB) for checkpoint {parent_sha[:12]}"
        )
        return manifest
    except OSError as exc:
        shutil.rmtree(snap, ignore_errors=True)
        print(f"⚠️  Could not snapshot git-ignored outputs: {exc}")
        return None


def restore_ignored_outputs_snapshot(work_dir: Path, parent_sha: str) -> list[str]:
    """Copy back snapshotted outputs that were modified or deleted since the snapshot.

    Only acts when the snapshot belongs to `parent_sha`. Returns the restored
    paths. Never raises.
    """
    work_dir = Path(work_dir)
    manifest = _read_manifest(work_dir)
    if not manifest or manifest.get("parent_sha") != parent_sha or not manifest.get("complete"):
        return []
    files_root = _snapshot_dir(work_dir) / FILES_DIRNAME
    restored = []
    for rel, signature in manifest.get("files", {}).items():
        target = work_dir / rel
        try:
            if target.is_file() and _signature(target) == list(signature):
                continue
            source = files_root / rel
            if not source.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink() or target.exists():
                target.unlink()
            shutil.copy2(source, target)
            restored.append(rel)
        except OSError as exc:
            print(f"⚠️  Could not restore git-ignored output {rel}: {exc}")
    if restored:
        print(
            f"♻️  Restored {len(restored)} git-ignored output files to checkpoint "
            f"{parent_sha[:12]} (e.g. {restored[0]})"
        )
    return restored
