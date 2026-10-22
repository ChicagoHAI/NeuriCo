"""Private snapshots for evaluator-declared artifacts excluded from Git.

HITL AutoResearch checkpoints own tracked workspace state through Git.  This
store complements those checkpoints with only the ignored files below the
runtime-frozen artifact contract, so a frontier node can restore model weights
without capturing unrelated datasets, environments, or caches.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from core.hitl_git import (
    CheckpointGitlink,
    HitlGitlinkError,
    checkpoint_gitlinks,
    create_git_commit_bundle,
    fetch_git_commit,
    git_failure_detail,
    prepare_git_commit_bundle_repository,
    resolve_checkpoint_gitlinks,
    run_git,
    verify_git_commit_bundle,
)
from core.hitl_paths import hitl_artifact_snapshots_dir
from core.hitl_util import atomic_write_json, fsync_directory, sha256_file


_SNAPSHOT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MANIFEST_NAME = "manifest.json"
_FILES_DIR = "files"
_GITLINKS_DIR = "gitlinks"
_OBJECT_ID = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COPY_CHUNK_SIZE = 1024 * 1024
_STAGING_NAME = re.compile(
    r"^\.(?P<snapshot_id>[A-Za-z0-9][A-Za-z0-9._-]{0,127})\."
    r"[0-9]+\.[0-9a-f]{32}\.tmp$"
)
_MATERIALIZATION_STAGING_NAME = re.compile(r"^\.materialize\.[0-9]+\.[0-9a-f]{32}\.tmp$")


class HitlArtifactSnapshotError(RuntimeError):
    """Raised when a private artifact snapshot cannot be captured or restored."""


def _safe_snapshot_id(value: str) -> str:
    snapshot_id = str(value).strip()
    if not _SNAPSHOT_ID.fullmatch(snapshot_id):
        raise HitlArtifactSnapshotError(f"Invalid HITL artifact snapshot id: {value!r}")
    return snapshot_id


def _safe_relative_path(value: str, *, label: str) -> Path:
    raw = str(value)
    posix = PurePosixPath(raw)
    if posix.is_absolute() or not posix.parts or any(
        part in {"", ".", ".."} for part in posix.parts
    ):
        raise HitlArtifactSnapshotError(f"Unsafe {label}: {value!r}")
    return Path(*posix.parts)


def _artifact_roots(work_dir: Path) -> list[str]:
    from core.hitl import load_hitl_required_artifact_contract

    roots = [
        artifact.path.rstrip("/")
        for artifact in load_hitl_required_artifact_contract(work_dir)
    ]
    for root in roots:
        if root in {".git", ".neurico"} or root.startswith((".git/", ".neurico/")):
            raise HitlArtifactSnapshotError(
                f"Evaluator-declared artifacts cannot use runtime-private path: {root}"
            )
    return roots


def _snapshot_dir(work_dir: Path, snapshot_id: str) -> Path:
    return hitl_artifact_snapshots_dir(work_dir) / _safe_snapshot_id(snapshot_id)


def _discard_incomplete_snapshot_generations(
    store: Path,
    *,
    snapshot_id: str | None = None,
) -> None:
    """Remove non-authoritative capture generations left by process loss."""
    normalized = _safe_snapshot_id(snapshot_id) if snapshot_id is not None else None
    if not store.is_dir():
        return
    for entry in store.iterdir():
        match = _STAGING_NAME.fullmatch(entry.name)
        if match is None or (
            normalized is not None and match.group("snapshot_id") != normalized
        ):
            continue
        if entry.is_symlink() or not entry.is_dir():
            entry.unlink()
        else:
            shutil.rmtree(entry)


def _discard_incomplete_materializations(store: Path) -> None:
    """Remove unpublished verified copies left by process loss."""
    if not store.is_dir():
        return
    for entry in store.iterdir():
        if _MATERIALIZATION_STAGING_NAME.fullmatch(entry.name) is None:
            continue
        if entry.is_symlink() or not entry.is_dir():
            entry.unlink()
        else:
            shutil.rmtree(entry)


def _path_without_symlink_ancestors(root: Path, relative: Path, *, label: str) -> Path:
    current = Path(root).resolve()
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise HitlArtifactSnapshotError(
                f"{label} crosses a symlinked directory: {relative.as_posix()}"
            )
    target = Path(root).resolve() / relative
    try:
        target.parent.resolve().relative_to(Path(root).resolve())
    except ValueError as exc:
        raise HitlArtifactSnapshotError(
            f"{label} escapes its workspace: {relative.as_posix()}"
        ) from exc
    return target


def _copy_regular_file_with_integrity(
    source: Path,
    destination: Path,
    *,
    expected: dict[str, Any] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Copy one regular file while recording or verifying its bytes."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        raise HitlArtifactSnapshotError(
            f"Evaluator-declared ignored artifact cannot be a symlink: {source}"
        )
    mode = source.lstat().st_mode
    if not stat.S_ISREG(mode):
        raise HitlArtifactSnapshotError(
            f"Evaluator-declared ignored artifact is not a regular file: {source}"
        )

    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as source_handle, destination.open("wb") as destination_handle:
        for chunk in iter(lambda: source_handle.read(_COPY_CHUNK_SIZE), b""):
            destination_handle.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    shutil.copystat(source, destination, follow_symlinks=False)
    actual = {"size": size, "sha256": digest.hexdigest()}
    if expected is not None and actual != expected:
        artifact = label or str(source)
        raise HitlArtifactSnapshotError(
            f"HITL artifact snapshot content does not match its manifest: {artifact}."
        )
    return actual


def _artifact_scopes_in_gitlink(
    artifact_roots: list[str],
    gitlink: CheckpointGitlink,
) -> list[Path]:
    """Return portions of the artifact contract owned by one Gitlink."""
    scopes: list[Path] = []
    seen: set[str] = set()
    nested_root = gitlink.relative_path
    for raw_root in artifact_roots:
        root = _safe_relative_path(raw_root, label="artifact root")
        if root == nested_root or nested_root in root.parents:
            scope = root.relative_to(nested_root)
        elif root in nested_root.parents:
            scope = Path(".")
        else:
            continue
        key = scope.as_posix()
        if key not in seen:
            seen.add(key)
            scopes.append(scope)
    return scopes


def _validate_gitlink_artifact_ownership(
    resolved_gitlinks: list[tuple[CheckpointGitlink, Path]],
    *,
    artifact_roots: list[str],
) -> None:
    """Require nested artifact state to be fully owned by its Git checkpoint."""
    for gitlink, repository in resolved_gitlinks:
        scopes = _artifact_scopes_in_gitlink(artifact_roots, gitlink)
        if not scopes:
            continue
        relative_text = gitlink.relative_path.as_posix()
        head = run_git(repository, "rev-parse", "HEAD", check=False)
        if head.returncode != 0:
            raise HitlArtifactSnapshotError(
                "Runtime could not inspect checkpointed nested repository "
                f"`{relative_text}`: {git_failure_detail(head)}"
            )
        if str(head.stdout).strip() != gitlink.commit_sha:
            raise HitlArtifactSnapshotError(
                "Evaluator-declared artifacts in checkpointed nested repository "
                f"`{relative_text}` are not at the recorded commit."
            )

        status = run_git(
            repository,
            "--literal-pathspecs",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignored=matching",
            "--",
            *[scope.as_posix() for scope in scopes],
            text=False,
            check=False,
        )
        if status.returncode != 0:
            raise HitlArtifactSnapshotError(
                "Runtime could not inspect evaluator-declared artifacts in checkpointed "
                f"nested repository `{relative_text}`: {git_failure_detail(status)}"
            )
        if bytes(status.stdout or b""):
            raise HitlArtifactSnapshotError(
                "Evaluator-declared artifacts in checkpointed nested repository "
                f"`{relative_text}` must be clean committed content or absent."
            )


def _path_is_owned_by_gitlink(
    relative: Path,
    resolved_gitlinks: list[tuple[CheckpointGitlink, Path]],
) -> bool:
    return any(
        relative == gitlink.relative_path or gitlink.relative_path in relative.parents
        for gitlink, _repository in resolved_gitlinks
    )


def _manifest_gitlinks(
    manifest: dict[str, Any],
) -> list[tuple[CheckpointGitlink, str, tuple[str, ...]]]:
    """Return validated Gitlink identities, bundles, and shallow boundaries."""
    if manifest.get("version") == 1:
        return []
    entries = manifest.get("gitlinks")
    if not isinstance(entries, list):
        raise HitlArtifactSnapshotError("HITL artifact snapshot has no Gitlink list.")

    parsed: list[tuple[CheckpointGitlink, str, tuple[str, ...]]] = []
    seen_paths: set[str] = set()
    seen_bundles: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise HitlArtifactSnapshotError("HITL artifact snapshot has an invalid Gitlink entry.")
        relative = _safe_relative_path(
            str(entry.get("path", "")),
            label="Gitlink path",
        )
        commit_sha = str(entry.get("commit_sha", "")).strip()
        if not _OBJECT_ID.fullmatch(commit_sha):
            raise HitlArtifactSnapshotError(
                f"HITL artifact snapshot has an invalid Gitlink commit: {commit_sha!r}"
            )
        bundle = _safe_relative_path(
            str(entry.get("bundle", "")),
            label="Gitlink bundle path",
        ).as_posix()
        if not bundle.startswith(f"{_GITLINKS_DIR}/") or not bundle.endswith(".bundle"):
            raise HitlArtifactSnapshotError(
                f"HITL artifact snapshot has an invalid Gitlink bundle path: {bundle}"
            )
        raw_boundaries = entry.get("shallow_boundaries", [])
        if not isinstance(raw_boundaries, list):
            raise HitlArtifactSnapshotError(
                "HITL artifact snapshot has invalid Gitlink shallow boundaries."
            )
        boundaries: list[str] = []
        for raw_boundary in raw_boundaries:
            if not isinstance(raw_boundary, str):
                raise HitlArtifactSnapshotError(
                    "HITL artifact snapshot has an invalid Gitlink shallow boundary."
                )
            boundary = raw_boundary.strip()
            if not _OBJECT_ID.fullmatch(boundary):
                raise HitlArtifactSnapshotError(
                    "HITL artifact snapshot has an invalid Gitlink shallow boundary."
                )
            boundaries.append(boundary)
        if len(set(boundaries)) != len(boundaries):
            raise HitlArtifactSnapshotError(
                "HITL artifact snapshot has duplicate Gitlink shallow boundaries."
            )
        path_key = relative.as_posix()
        if path_key in seen_paths or bundle in seen_bundles:
            raise HitlArtifactSnapshotError(
                "HITL artifact snapshot contains duplicate Gitlink state."
            )
        seen_paths.add(path_key)
        seen_bundles.add(bundle)
        parsed.append(
            (CheckpointGitlink(relative, commit_sha), bundle, tuple(sorted(boundaries)))
        )
    return parsed


def _gitlink_identity_map(gitlinks: list[CheckpointGitlink]) -> dict[str, str]:
    return {gitlink.relative_path.as_posix(): gitlink.commit_sha for gitlink in gitlinks}


def _read_manifest(work_dir: Path, snapshot_id: str) -> dict[str, Any]:
    normalized = _safe_snapshot_id(snapshot_id)
    path = _snapshot_dir(work_dir, normalized) / _MANIFEST_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HitlArtifactSnapshotError(
            f"HITL artifact snapshot {normalized} is missing or unreadable."
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("version") not in {1, 2, 3}
        or payload.get("artifact_snapshot_id") != normalized
        or not isinstance(payload.get("source_checkpoint_sha"), str)
        or not isinstance(payload.get("artifact_roots"), list)
        or not isinstance(payload.get("captured_paths"), list)
    ):
        raise HitlArtifactSnapshotError(
            f"HITL artifact snapshot {normalized} has an invalid manifest."
        )
    artifact_roots = [
        _safe_relative_path(str(root), label="artifact root")
        for root in payload["artifact_roots"]
    ]
    captured_paths = payload["captured_paths"]
    if any(not isinstance(relative, str) for relative in captured_paths):
        raise HitlArtifactSnapshotError(
            f"HITL artifact snapshot {normalized} has invalid captured paths."
        )
    for relative in captured_paths:
        captured = _safe_relative_path(str(relative), label="captured artifact path")
        if not any(captured == root or root in captured.parents for root in artifact_roots):
            raise HitlArtifactSnapshotError(
                f"HITL artifact snapshot {normalized} contains an undeclared path."
            )
    if payload["version"] == 3:
        captured_files = payload.get("captured_files")
        if (
            not isinstance(captured_files, dict)
            or len(set(captured_paths)) != len(captured_paths)
            or set(captured_files) != set(captured_paths)
        ):
            raise HitlArtifactSnapshotError(
                f"HITL artifact snapshot {normalized} has invalid file integrity metadata."
            )
        for relative_text, integrity in captured_files.items():
            if (
                not isinstance(integrity, dict)
                or set(integrity) != {"size", "sha256"}
                or not isinstance(integrity["size"], int)
                or isinstance(integrity["size"], bool)
                or integrity["size"] < 0
                or not isinstance(integrity["sha256"], str)
                or not _SHA256.fullmatch(integrity["sha256"])
            ):
                raise HitlArtifactSnapshotError(
                    f"HITL artifact snapshot {normalized} has invalid integrity metadata "
                    f"for {relative_text}."
                )
    _manifest_gitlinks(payload)
    return payload


def inspect_hitl_artifact_snapshot(
    work_dir: Path,
    snapshot_id: str,
    *,
    source_checkpoint_sha: str | None = None,
) -> dict[str, Any]:
    """Validate snapshot structure without reading every stored artifact byte."""
    workspace = Path(work_dir).resolve()
    manifest = _read_manifest(workspace, snapshot_id)
    expected = str(source_checkpoint_sha or "").strip()
    if expected and manifest["source_checkpoint_sha"] != expected:
        raise HitlArtifactSnapshotError(
            f"HITL artifact snapshot {snapshot_id} belongs to a different checkpoint."
        )
    captured_files = manifest.get("captured_files", {})
    files_root = _snapshot_dir(workspace, snapshot_id) / _FILES_DIR
    for relative_text in manifest["captured_paths"]:
        relative = _safe_relative_path(
            relative_text,
            label="captured artifact path",
        )
        source = _path_without_symlink_ancestors(
            files_root,
            relative,
            label="Stored evaluator artifact",
        )
        try:
            file_stat = source.lstat()
        except OSError as exc:
            raise HitlArtifactSnapshotError(
                f"HITL artifact snapshot {snapshot_id} is missing {relative_text}."
            ) from exc
        if not stat.S_ISREG(file_stat.st_mode):
            raise HitlArtifactSnapshotError(
                f"HITL artifact snapshot {snapshot_id} has an invalid stored file: "
                f"{relative_text}."
            )
        integrity = captured_files.get(relative_text)
        if integrity is not None and file_stat.st_size != integrity["size"]:
            raise HitlArtifactSnapshotError(
                f"HITL artifact snapshot content does not match its manifest: "
                f"{relative_text}."
            )
    snapshot_root = _snapshot_dir(workspace, snapshot_id)
    for gitlink, bundle_text, _boundaries in _manifest_gitlinks(manifest):
        bundle = _path_without_symlink_ancestors(
            snapshot_root,
            _safe_relative_path(bundle_text, label="Gitlink bundle path"),
            label="Stored Gitlink bundle",
        )
        try:
            verify_git_commit_bundle(workspace, bundle, gitlink.commit_sha)
        except HitlGitlinkError as exc:
            raise HitlArtifactSnapshotError(
                f"HITL artifact snapshot {snapshot_id} has an invalid bundle for "
                f"`{gitlink.relative_path.as_posix()}`: {exc}"
            ) from exc
    return manifest


def validate_hitl_artifact_snapshot(
    work_dir: Path,
    snapshot_id: str,
    *,
    source_checkpoint_sha: str | None = None,
) -> dict[str, Any]:
    """Validate one stored snapshot, including v3 artifact contents."""
    workspace = Path(work_dir).resolve()
    manifest = inspect_hitl_artifact_snapshot(
        workspace,
        snapshot_id,
        source_checkpoint_sha=source_checkpoint_sha,
    )
    captured_files = manifest.get("captured_files", {})
    files_root = _snapshot_dir(workspace, snapshot_id) / _FILES_DIR
    for relative_text in manifest["captured_paths"]:
        integrity = captured_files.get(relative_text)
        if integrity is None:
            continue
        relative = _safe_relative_path(
            relative_text,
            label="captured artifact path",
        )
        source = _path_without_symlink_ancestors(
            files_root,
            relative,
            label="Stored evaluator artifact",
        )
        try:
            digest = sha256_file(source)
        except OSError as exc:
            raise HitlArtifactSnapshotError(
                f"HITL artifact snapshot {snapshot_id} could not read {relative_text}."
            ) from exc
        if digest != integrity["sha256"]:
            raise HitlArtifactSnapshotError(
                f"HITL artifact snapshot content does not match its manifest: "
                f"{relative_text}."
            )
    return manifest


def capture_hitl_artifact_snapshot(
    work_dir: Path,
    *,
    snapshot_id: str,
    source_checkpoint_sha: str,
) -> str:
    """Atomically capture ignored files beneath the frozen artifact contract."""
    workspace = Path(work_dir).resolve()
    normalized = _safe_snapshot_id(snapshot_id)
    source_sha = str(source_checkpoint_sha).strip()
    if not source_sha:
        raise HitlArtifactSnapshotError("Artifact snapshot requires a source checkpoint SHA.")
    roots = _artifact_roots(workspace)
    if not roots:
        raise HitlArtifactSnapshotError("Artifact snapshot requires a non-empty frozen contract.")
    try:
        resolved_gitlinks = resolve_checkpoint_gitlinks(workspace, source_sha)
    except HitlGitlinkError as exc:
        raise HitlArtifactSnapshotError(str(exc)) from exc
    _validate_gitlink_artifact_ownership(
        resolved_gitlinks,
        artifact_roots=roots,
    )
    gitlinks = [gitlink for gitlink, _repository in resolved_gitlinks]

    store = hitl_artifact_snapshots_dir(workspace)
    store.mkdir(parents=True, exist_ok=True)
    _discard_incomplete_snapshot_generations(store)
    _discard_incomplete_materializations(store)
    final = store / normalized
    if final.exists():
        # Reopening a published snapshot needs structural and identity checks;
        # materialization verifies its contents while copying them for use.
        manifest = inspect_hitl_artifact_snapshot(workspace, normalized)
        stored_gitlinks = [
            gitlink for gitlink, _bundle, _boundaries in _manifest_gitlinks(manifest)
        ]
        if (
            manifest["source_checkpoint_sha"] != source_sha
            or manifest["artifact_roots"] != roots
            or (manifest["version"] == 1 and bool(gitlinks))
            or (
                manifest["version"] >= 2
                and _gitlink_identity_map(stored_gitlinks) != _gitlink_identity_map(gitlinks)
            )
        ):
            raise HitlArtifactSnapshotError(
                f"HITL artifact snapshot id {normalized} already names a different boundary."
            )
        return normalized

    listed = run_git(
        workspace,
        "--literal-pathspecs",
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
        "--",
        *roots,
        text=False,
        check=False,
    )
    if listed.returncode != 0:
        detail = bytes(listed.stderr or listed.stdout or b"unknown Git error").decode(
            "utf-8", errors="replace"
        ).strip()
        raise HitlArtifactSnapshotError(
            f"Runtime could not enumerate ignored evaluator artifacts: {detail}"
        )

    captured: list[str] = []
    seen: set[str] = set()
    for raw in bytes(listed.stdout or b"").split(b"\0"):
        if not raw:
            continue
        relative_text = os.fsdecode(raw)
        relative = _safe_relative_path(relative_text, label="ignored artifact path")
        if _path_is_owned_by_gitlink(relative, resolved_gitlinks):
            continue
        normalized_relative = relative.as_posix()
        if normalized_relative not in seen:
            seen.add(normalized_relative)
            captured.append(normalized_relative)
    captured.sort()

    staging = store / f".{normalized}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        files_root = staging / _FILES_DIR
        files_root.mkdir(parents=True)
        captured_files: dict[str, dict[str, Any]] = {}
        for relative_text in captured:
            relative = _safe_relative_path(relative_text, label="ignored artifact path")
            source = _path_without_symlink_ancestors(
                workspace,
                relative,
                label="Ignored evaluator artifact",
            )
            if not source.exists() and not source.is_symlink():
                raise HitlArtifactSnapshotError(
                    f"Ignored evaluator artifact disappeared during capture: {relative_text}"
                )
            captured_files[relative_text] = _copy_regular_file_with_integrity(
                source,
                files_root / relative,
                label=relative_text,
            )
        bundled_gitlinks: list[dict[str, Any]] = []
        for index, (gitlink, repository) in enumerate(resolved_gitlinks):
            bundle_relative = f"{_GITLINKS_DIR}/{index:04d}.bundle"
            try:
                shallow_boundaries = create_git_commit_bundle(
                    repository,
                    commit_sha=gitlink.commit_sha,
                    destination=staging / bundle_relative,
                )
            except HitlGitlinkError as exc:
                raise HitlArtifactSnapshotError(
                    "Runtime could not preserve checkpointed nested repository "
                    f"`{gitlink.relative_path.as_posix()}`: {exc}"
                ) from exc
            bundled_gitlinks.append(
                {
                    "path": gitlink.relative_path.as_posix(),
                    "commit_sha": gitlink.commit_sha,
                    "bundle": bundle_relative,
                    "shallow_boundaries": list(shallow_boundaries),
                }
            )
        atomic_write_json(
            staging / _MANIFEST_NAME,
            {
                "version": 3,
                "artifact_snapshot_id": normalized,
                "source_checkpoint_sha": source_sha,
                "artifact_roots": roots,
                "captured_paths": captured,
                "captured_files": captured_files,
                "gitlinks": bundled_gitlinks,
            },
            fsync_parent=False,
        )
        os.replace(staging, final)
        fsync_directory(store)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return normalized


def _prepare_hitl_artifact_materialization(
    work_dir: Path,
    *,
    snapshot_id: str,
    manifest: dict[str, Any],
) -> Path:
    """Copy and verify every artifact before its destination is changed."""
    workspace = Path(work_dir).resolve()
    files_root = _snapshot_dir(workspace, snapshot_id) / _FILES_DIR
    captured_files = manifest.get("captured_files", {})
    store = hitl_artifact_snapshots_dir(workspace)
    _discard_incomplete_materializations(store)
    staging = store / f".materialize.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        staging.mkdir()
        for relative_text in manifest["captured_paths"]:
            relative = _safe_relative_path(relative_text, label="captured artifact path")
            source = _path_without_symlink_ancestors(
                files_root,
                relative,
                label="Stored evaluator artifact",
            )
            if not source.exists() and not source.is_symlink():
                raise HitlArtifactSnapshotError(
                    f"HITL artifact snapshot {snapshot_id} is missing {relative_text}."
                )
            staged = _path_without_symlink_ancestors(
                staging / _FILES_DIR,
                relative,
                label="Staged evaluator artifact",
            )
            _copy_regular_file_with_integrity(
                source,
                staged,
                expected=captured_files.get(relative_text),
                label=relative_text,
            )
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
    return staging


def _publish_hitl_artifact_materialization(
    *,
    manifest: dict[str, Any],
    staging: Path,
    destination: Path,
) -> None:
    """Publish artifact files that were already copied and verified."""
    target_root = Path(destination).resolve()
    for relative_text in manifest["captured_paths"]:
        relative = _safe_relative_path(relative_text, label="captured artifact path")
        staged = _path_without_symlink_ancestors(
            staging / _FILES_DIR,
            relative,
            label="Staged evaluator artifact",
        )
        target = _path_without_symlink_ancestors(
            target_root,
            relative,
            label="Restored evaluator artifact",
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        os.replace(staged, target)


def materialize_hitl_artifact_snapshot(
    work_dir: Path,
    *,
    snapshot_id: str,
    destination: Path,
) -> None:
    """Copy one private snapshot into a workspace without following symlinks."""
    workspace = Path(work_dir).resolve()
    manifest = _read_manifest(workspace, snapshot_id)
    staging = _prepare_hitl_artifact_materialization(
        workspace,
        snapshot_id=snapshot_id,
        manifest=manifest,
    )
    try:
        _publish_hitl_artifact_materialization(
            manifest=manifest,
            staging=staging,
            destination=destination,
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _remove_workspace_entry(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _snapshot_bundle_path(
    work_dir: Path,
    snapshot_id: str,
    bundle_text: str,
) -> Path:
    return _path_without_symlink_ancestors(
        _snapshot_dir(work_dir, snapshot_id),
        _safe_relative_path(bundle_text, label="Gitlink bundle path"),
        label="Stored Gitlink bundle",
    )


def _require_manifest_gitlinks_match_checkpoint(
    manifest: dict[str, Any],
    checkpoint_links: list[CheckpointGitlink],
) -> list[tuple[CheckpointGitlink, str, tuple[str, ...]]]:
    entries = _manifest_gitlinks(manifest)
    if manifest["version"] >= 2 and _gitlink_identity_map(
        [gitlink for gitlink, _bundle, _boundaries in entries]
    ) != _gitlink_identity_map(checkpoint_links):
        raise HitlArtifactSnapshotError(
            "HITL artifact snapshot Gitlinks do not match the workspace checkpoint."
        )
    return entries


def resolve_hitl_snapshot_gitlink_bundles(
    work_dir: Path,
    *,
    snapshot_id: str,
    checkpoint_sha: str,
) -> list[tuple[CheckpointGitlink, Path, tuple[str, ...]]] | None:
    """Return validated Gitlink bundles for isolated scoring.

    Version-1 snapshots predate bundled Gitlinks and return ``None`` so the
    scorer can retain its existing live-repository fallback.
    """
    workspace = Path(work_dir).resolve()
    manifest = inspect_hitl_artifact_snapshot(
        workspace,
        snapshot_id,
        source_checkpoint_sha=checkpoint_sha,
    )
    if manifest["version"] == 1:
        return None
    try:
        checkpoint_links = checkpoint_gitlinks(workspace, checkpoint_sha)
    except HitlGitlinkError as exc:
        raise HitlArtifactSnapshotError(str(exc)) from exc
    entries = _require_manifest_gitlinks_match_checkpoint(manifest, checkpoint_links)
    return [
        (
            gitlink,
            _snapshot_bundle_path(workspace, snapshot_id, bundle_text),
            shallow_boundaries,
        )
        for gitlink, bundle_text, shallow_boundaries in entries
    ]


def discard_hitl_artifact_snapshot(work_dir: Path, snapshot_id: str) -> None:
    """Delete one runtime-owned transient snapshot."""
    workspace = Path(work_dir).resolve()
    normalized = _safe_snapshot_id(snapshot_id)
    store = hitl_artifact_snapshots_dir(workspace)
    _discard_incomplete_snapshot_generations(store, snapshot_id=normalized)
    _discard_incomplete_materializations(store)
    target = store / normalized
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)


def _finalize_restored_gitlink(
    repository: Path,
    gitlink: CheckpointGitlink,
    *,
    artifact_roots: list[str],
) -> None:
    """Clean and verify one restored nested repository."""
    relative_text = gitlink.relative_path.as_posix()
    cleaned_public = run_git(repository, "clean", "-ffd", check=False)
    if cleaned_public.returncode != 0:
        raise HitlArtifactSnapshotError(
            "Runtime could not clear untracked files from checkpointed nested "
            f"repository `{relative_text}`: {git_failure_detail(cleaned_public)}"
        )

    scopes = _artifact_scopes_in_gitlink(artifact_roots, gitlink)
    if scopes:
        cleaned_ignored = run_git(
            repository,
            "--literal-pathspecs",
            "clean",
            "-ffdX",
            "--",
            *[scope.as_posix() for scope in scopes],
            check=False,
        )
        if cleaned_ignored.returncode != 0:
            raise HitlArtifactSnapshotError(
                "Runtime could not clear stale ignored evaluator artifacts from "
                f"checkpointed nested repository `{relative_text}`: "
                f"{git_failure_detail(cleaned_ignored)}"
            )

    head = run_git(repository, "rev-parse", "HEAD", check=False)
    if head.returncode != 0 or str(head.stdout).strip() != gitlink.commit_sha:
        raise HitlArtifactSnapshotError(
            "Runtime could not verify restored checkpointed nested repository "
            f"`{relative_text}`."
        )


def _restore_checkpoint_gitlinks(
    resolved_gitlinks: list[tuple[CheckpointGitlink, Path]],
    *,
    artifact_roots: list[str],
) -> None:
    """Restore nested checkouts and clean only runtime-owned artifact state."""
    for gitlink, repository in resolved_gitlinks:
        relative_text = gitlink.relative_path.as_posix()
        reset = run_git(
            repository,
            "reset",
            "--hard",
            gitlink.commit_sha,
            check=False,
        )
        if reset.returncode != 0:
            raise HitlArtifactSnapshotError(
                "Runtime could not restore checkpointed nested repository "
                f"`{relative_text}`: {git_failure_detail(reset)}"
            )
        _finalize_restored_gitlink(
            repository,
            gitlink,
            artifact_roots=artifact_roots,
        )


def _prepare_bundled_checkpoint_gitlinks(
    work_dir: Path,
    *,
    snapshot_id: str,
    manifest: dict[str, Any],
    staging: Path,
) -> list[tuple[CheckpointGitlink, Path, tuple[str, ...]]]:
    """Import every bundle in private storage before any live restoration."""
    prepared = []
    for index, (gitlink, bundle_text, shallow_boundaries) in enumerate(
        _manifest_gitlinks(manifest)
    ):
        repository = staging / _GITLINKS_DIR / f"{index:04d}.git"
        try:
            prepare_git_commit_bundle_repository(
                repository,
                bundle_path=_snapshot_bundle_path(work_dir, snapshot_id, bundle_text),
                commit_sha=gitlink.commit_sha,
                shallow_boundaries=shallow_boundaries,
            )
        except HitlGitlinkError as exc:
            raise HitlArtifactSnapshotError(
                "Runtime could not prepare checkpointed nested repository "
                f"`{gitlink.relative_path.as_posix()}`: {exc}"
            ) from exc
        prepared.append((gitlink, repository, shallow_boundaries))
    return prepared


def _restore_bundled_checkpoint_gitlinks(
    work_dir: Path,
    *,
    prepared_gitlinks: list[tuple[CheckpointGitlink, Path, tuple[str, ...]]],
    artifact_roots: list[str],
) -> None:
    workspace = Path(work_dir).resolve()
    for gitlink, prepared_repository, shallow_boundaries in prepared_gitlinks:
        repository = _path_without_symlink_ancestors(
            workspace,
            gitlink.relative_path,
            label="Restored Gitlink",
        )
        repository_root = (
            run_git(repository, "rev-parse", "--show-toplevel", check=False)
            if repository.is_dir()
            else None
        )
        if (
            repository_root is None
            or repository_root.returncode != 0
            or Path(str(repository_root.stdout).strip()).resolve() != repository
        ):
            _remove_workspace_entry(repository)
            repository.mkdir(parents=True)
            initialized = run_git(repository, "init", "--quiet", check=False)
            if initialized.returncode != 0:
                raise HitlArtifactSnapshotError(
                    "Runtime could not reconstruct checkpointed nested repository "
                    f"`{gitlink.relative_path.as_posix()}`: "
                    f"{git_failure_detail(initialized)}"
                )
        try:
            fetch_git_commit(
                repository,
                source=prepared_repository,
                commit_sha=gitlink.commit_sha,
                shallow_boundaries=shallow_boundaries,
            )
        except HitlGitlinkError as exc:
            raise HitlArtifactSnapshotError(str(exc)) from exc
        checked_out = run_git(
            repository,
            "checkout",
            "--detach",
            "--force",
            gitlink.commit_sha,
            check=False,
        )
        if checked_out.returncode != 0:
            raise HitlArtifactSnapshotError(
                "Runtime could not restore checkpointed nested repository "
                f"`{gitlink.relative_path.as_posix()}`: "
                f"{git_failure_detail(checked_out)}"
            )
        _finalize_restored_gitlink(
            repository,
            gitlink,
            artifact_roots=artifact_roots,
        )


def restore_hitl_checkpoint_with_artifacts(
    work_dir: Path,
    *,
    checkpoint_sha: str,
    artifact_snapshot_id: str | None,
    artifact_source_checkpoint_sha: str | None = None,
) -> str:
    """Restore one composite HITL checkpoint and verify its Git component."""
    from core.autoresearch import CheckpointManager

    workspace = Path(work_dir).resolve()
    checkpoints = CheckpointManager(workspace)
    sha = str(checkpoint_sha).strip()
    if not checkpoints.checkpoint_exists(sha):
        raise HitlArtifactSnapshotError("The HITL node is not a workspace checkpoint.")
    snapshot_id = str(artifact_snapshot_id or "").strip()
    manifest = (
        # A retained node pairs its scored public checkpoint with the artifact
        # snapshot captured from the pre-scoring source checkpoint.  The
        # persisted pair is the composite restoration identity; exact source
        # matching remains enforced by scoring and stage-rollback callers.
        inspect_hitl_artifact_snapshot(
            workspace,
            snapshot_id,
            source_checkpoint_sha=artifact_source_checkpoint_sha,
        )
        if snapshot_id
        else None
    )
    artifact_roots = list(manifest["artifact_roots"]) if manifest is not None else []
    try:
        target_gitlinks = checkpoint_gitlinks(workspace, sha)
        current_sha = checkpoints.current_sha()
        current_gitlinks = checkpoint_gitlinks(workspace, current_sha) if current_sha else []
    except HitlGitlinkError as exc:
        raise HitlArtifactSnapshotError(str(exc)) from exc

    bundled_gitlinks = manifest is not None and manifest["version"] >= 2
    resolved_gitlinks: list[tuple[CheckpointGitlink, Path]] | None = None
    if bundled_gitlinks:
        assert manifest is not None
        _require_manifest_gitlinks_match_checkpoint(manifest, target_gitlinks)
    else:
        # Version-1 snapshots and legacy nodes depend on their existing live
        # nested checkouts. Resolve every target before changing the workspace.
        try:
            resolved_gitlinks = resolve_checkpoint_gitlinks(workspace, sha)
        except HitlGitlinkError as exc:
            raise HitlArtifactSnapshotError(str(exc)) from exc

    staging = (
        _prepare_hitl_artifact_materialization(
            workspace,
            snapshot_id=snapshot_id,
            manifest=manifest,
        )
        if manifest is not None
        else None
    )
    try:
        if bundled_gitlinks:
            assert manifest is not None
            assert staging is not None
            prepared_gitlinks = _prepare_bundled_checkpoint_gitlinks(
                workspace,
                snapshot_id=snapshot_id,
                manifest=manifest,
                staging=staging,
            )
            current_paths = {
                gitlink.relative_path.as_posix(): gitlink.relative_path
                for gitlink in current_gitlinks
            }
            target_paths = {gitlink.relative_path.as_posix() for gitlink in target_gitlinks}
            for relative_text, relative in current_paths.items():
                if relative_text in target_paths:
                    continue
                obsolete = _path_without_symlink_ancestors(
                    workspace,
                    relative,
                    label="Obsolete Gitlink",
                )
                _remove_workspace_entry(obsolete)

            checkpoints.restore_checkpoint(sha, clean_untracked_public=True)
            if artifact_roots:
                cleaned = run_git(
                    workspace,
                    "--literal-pathspecs",
                    "clean",
                    "-ffdx",
                    "--",
                    *artifact_roots,
                    check=False,
                )
                if cleaned.returncode != 0:
                    detail = str(
                        cleaned.stderr or cleaned.stdout or "unknown Git error"
                    ).strip()
                    raise HitlArtifactSnapshotError(
                        f"Runtime could not clear stale evaluator artifacts: {detail}"
                    )
            _restore_bundled_checkpoint_gitlinks(
                workspace,
                prepared_gitlinks=prepared_gitlinks,
                artifact_roots=artifact_roots,
            )
            _publish_hitl_artifact_materialization(
                manifest=manifest,
                staging=staging,
                destination=workspace,
            )
        else:
            assert resolved_gitlinks is not None
            checkpoints.restore_checkpoint(sha, clean_untracked_public=True)
            _restore_checkpoint_gitlinks(
                resolved_gitlinks,
                artifact_roots=artifact_roots,
            )
            if manifest is not None:
                assert staging is not None
                cleaned = run_git(
                    workspace,
                    "--literal-pathspecs",
                    "clean",
                    "-fdX",
                    "--",
                    *artifact_roots,
                    check=False,
                )
                if cleaned.returncode != 0:
                    detail = str(
                        cleaned.stderr or cleaned.stdout or "unknown Git error"
                    ).strip()
                    raise HitlArtifactSnapshotError(
                        "Runtime could not clear stale ignored evaluator artifacts: "
                        f"{detail}"
                    )
                _publish_hitl_artifact_materialization(
                    manifest=manifest,
                    staging=staging,
                    destination=workspace,
                )
        if checkpoints.current_sha() != sha:
            raise HitlArtifactSnapshotError("Runtime could not restore the HITL node checkpoint.")
        return sha
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def restore_hitl_frontier_node(work_dir: Path, node_sha: str) -> str:
    """Restore a retained frontier node, including its optional legacy snapshot."""
    from core.hitl_frontier import HitlFrontierStore

    frontier = HitlFrontierStore(work_dir)
    return restore_hitl_checkpoint_with_artifacts(
        work_dir,
        checkpoint_sha=node_sha,
        artifact_snapshot_id=frontier.artifact_snapshot_id(node_sha),
    )
