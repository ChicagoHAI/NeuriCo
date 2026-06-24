"""
Lifecycle helpers for the modal-training skill.

Three primitives the generated templates use:

    register(exp_id, volumes=[...], apps=[...], required_secrets={...},
             pull_manifest=[...])
        Create the per-experiment Modal environment if missing, mint any
        per-env secrets from local env vars, claim the volume names, and
        persist the run's pull manifest into .neurico/modal_resources.json.

    pull_all(exp_id)
        Walk the persisted manifest and copy each entry off the Modal
        volumes into the workspace. Records `pull_complete=False` in the
        sentinel and raises if any entry marked `required: True` failed or
        could not be found.

    teardown(exp_id, force=False)
        Delete the env (which cascades to volumes, apps, and secrets).
        Refuses to run unless pull_complete=True in the sentinel; pass
        force=True to override (used only by the orchestrator sweep when
        no pull is expected — e.g. the script crashed before register()
        finished its work).

CLI:
    python lifecycle.py status   --exp-id <id>
    python lifecycle.py pull     --exp-id <id>
    python lifecycle.py teardown --exp-id <id> [--force]
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

SENTINEL_REL = Path(".neurico") / "modal_resources.json"
SENTINEL_LOCK_REL = Path(".neurico") / "modal_resources.lock"

# Large multi-GB artifact pulls (e.g. a full SFT checkpoint dir) can exceed
# the 600s default. Override via env var when you know the artifact is big.
_PULL_TIMEOUT = int(os.environ.get("NEURICO_MODAL_PULL_TIMEOUT", "600"))

# Manifest entries declared by each template's register() call. Lifecycle has
# no knowledge of what artifacts a run produces — that's the template's
# domain. Each entry is a dict with these keys:
#   from_volume : str    — volume name (must be in `volumes` list)
#   from        : str    — remote path inside the volume (absolute)
#   to          : str    — destination in workspace, relative to workspace root
#   is_dir      : bool   — whether `from` is a directory (default False)
#   required    : bool   — if True, missing = pull_incomplete = no teardown
#                          (default False — best-effort pull)
# Example for a LoRA SFT template:
#   pull_manifest=[
#     {"from_volume": ckpt, "from": "/run_config.json",
#      "to": "artifacts/run_config.json", "required": True},
#     {"from_volume": ckpt, "from": "/final",
#      "to": "artifacts/final", "is_dir": True, "required": True},
#   ]
ManifestEntry = Dict[str, Any]


# Sentinel I/O

def workspace_root(start: Optional[Path] = None) -> Path:
    """
    Walk upward from `start` (or cwd) looking for a directory containing
    `.neurico/`. Falls back to the starting directory if no marker is found.
    """
    p = (start or Path.cwd()).resolve()
    for candidate in [p, *p.parents]:
        if (candidate / ".neurico").exists():
            return candidate
    return p


def sentinel_path(workspace: Optional[Path] = None) -> Path:
    """Return the absolute path to the workspace's sentinel JSON."""
    return workspace_root(workspace) / SENTINEL_REL


def load_sentinel(workspace: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Return the parsed sentinel, or None if the workspace never used Modal."""
    path = sentinel_path(workspace)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _lock_path(workspace: Optional[Path] = None) -> Path:
    return workspace_root(workspace) / SENTINEL_LOCK_REL


@contextlib.contextmanager
def _sentinel_lock(workspace: Optional[Path] = None) -> Iterator[None]:
    """
    Cross-process exclusive lock around sentinel read-modify-write blocks.

    Two concurrent template runs under the same EXP_ID (e.g. prep + train
    started in parallel) could otherwise interleave load → mutate → write
    and lose one stage's pull_complete=False, leading to a false-clean
    teardown. The lock serializes those critical sections.
    """
    lock_path = _lock_path(workspace)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w", encoding="utf-8") as lock_f:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)


def _save_atomic(path: Path, data: Dict[str, Any]) -> None:
    """Write JSON via tmp-file + os.replace so readers never see a torn file."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def save_sentinel(data: Dict[str, Any], workspace: Optional[Path] = None) -> None:
    """Write the sentinel JSON, creating .neurico/ if needed. Atomic + locked."""
    path = sentinel_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _sentinel_lock(workspace):
        _save_atomic(path, data)


def update_sentinel(
    workspace: Optional[Path],
    mutate: Callable[[Dict[str, Any]], Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Load, mutate, save the sentinel under a single lock.

    Use this for any read-modify-write block that another process or thread
    could race against — register() and pull_all() both need it because they
    merge with prior state.
    """
    path = sentinel_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _sentinel_lock(workspace):
        existing = {}
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
        new = mutate(existing)
        _save_atomic(path, new)
    return new


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string with second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Modal CLI wrappers

def _run(cmd: List[str], timeout: int = 120,
         check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, check=check)


def env_name_for(exp_id: str) -> str:
    """Standard Modal environment name for a NeuriCo experiment id."""
    return f"neurico-{exp_id}"


def env_exists(env_name: str) -> bool:
    """
    Probe for an environment by trying to list its apps.

    `modal environment list` truncates names with `…` in its table output, so
    substring matching is unreliable. `modal app list --env=NAME` cleanly
    returns 0 if the env exists, non-zero otherwise — no parsing needed.
    """
    r = _run(["modal", "app", "list", f"--env={env_name}"])
    return r.returncode == 0


def ensure_environment(env_name: str) -> None:
    """
    Create the environment if it does not already exist.

    Idempotent: tolerates an "already exists" error from Modal (which can
    race against another local process, or our own env_exists probe being
    momentarily out of date).
    """
    if env_exists(env_name):
        return
    r = _run(["modal", "environment", "create", env_name])
    if r.returncode == 0:
        return
    msg = (r.stderr or r.stdout).lower()
    if "same name" in msg or "already" in msg:
        return
    raise RuntimeError(
        f"failed to create environment {env_name!r}: "
        f"{r.stderr.strip() or r.stdout.strip()}"
    )


def delete_environment(env_name: str) -> None:
    """
    Delete the per-experiment environment and cascade to all volumes, apps,
    and secrets it owns. Raises RuntimeError on failure so teardown() can
    record the error in the sentinel before re-raising.
    """
    r = _run(["modal", "environment", "delete", env_name, "-y"], timeout=180)
    if r.returncode != 0:
        raise RuntimeError(
            f"failed to delete environment {env_name!r}: "
            f"{r.stderr.strip() or r.stdout.strip()}"
        )


def volume_get(env_name: str, volume: str, remote: str,
               dest: Path, is_dir: bool = False) -> subprocess.CompletedProcess:
    """
    Run `modal volume get --force <vol> <remote> <dest>` scoped to an env.

    File pulls: `dest` is the destination file path; its parent is created.

    Directory pulls (`is_dir=True`): Modal CLI requires the destination to
    exist as a directory and the argument to end with a trailing slash; the
    pulled directory lands as a child of the destination, named after the
    remote leaf. So the template/manifest must use a destination whose leaf
    name MATCHES the remote leaf (e.g. remote `/final` → dest
    `artifacts/final`). The lifecycle pulls to `dest.parent/` and lets Modal
    place the new directory at `dest` directly.

    --force is required because re-running a pull onto an existing workspace
    (the expected recovery path after a failed teardown) would otherwise hit
    "Output path already exists" from the Modal CLI.
    """
    if is_dir:
        if dest.name != remote.rstrip("/").rsplit("/", 1)[-1]:
            return subprocess.CompletedProcess(
                args=[], returncode=2, stdout="",
                stderr=(
                    f"manifest entry mismatch: directory pull requires "
                    f"dest leaf name to match remote leaf. "
                    f"remote={remote!r} dest={str(dest)!r}"
                ),
            )
        parent = dest.parent
        parent.mkdir(parents=True, exist_ok=True)
        # Modal won't overwrite an existing target directory even with --force.
        # Stage the prior copy to <dest>.prev so a failed pull can restore it
        # instead of leaving the user with an empty hole where their artifact
        # used to be.
        prev = dest.with_name(dest.name + ".prev")
        staged = False
        if dest.exists():
            if prev.exists():
                shutil.rmtree(prev)
            os.replace(dest, prev)
            staged = True
        r = _run([
            "modal", "volume", "get", f"--env={env_name}", "--force",
            volume, remote, str(parent) + "/",
        ], timeout=_PULL_TIMEOUT)
        if r.returncode == 0:
            if staged and prev.exists():
                shutil.rmtree(prev)
        else:
            if staged:
                if dest.exists():
                    shutil.rmtree(dest)
                os.replace(prev, dest)
        return r
    dest.parent.mkdir(parents=True, exist_ok=True)
    return _run([
        "modal", "volume", "get", f"--env={env_name}", "--force",
        volume, remote, str(dest),
    ], timeout=_PULL_TIMEOUT)


def volume_put(env_name: str, volume: str, src: Path,
               remote: str) -> subprocess.CompletedProcess:
    """
    Run `modal volume put --force <vol> <local> <remote>` scoped to an env.

    `src` is a workspace-side file path; `remote` is its destination inside
    the volume (absolute). --force lets a re-run overwrite a residual entry
    from a previous attempt (the same reasoning as volume_get).
    """
    return _run([
        "modal", "volume", "put", f"--env={env_name}", "--force",
        volume, str(src), remote,
    ], timeout=_PULL_TIMEOUT)


def app_stop(env_name: str, app_name: str) -> None:
    """
    Stop a deployed Modal app. Tolerates "not found" / "already stopped"
    because env delete cascades to apps and may race with explicit stops.
    """
    r = _run(["modal", "app", "stop", f"--env={env_name}", "-y", app_name],
             timeout=120)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip().lower()
        if "not found" in msg or "already" in msg:
            return
        raise RuntimeError(f"failed to stop app {app_name!r}: {msg}")


# register / pull / teardown

def _ensure_secret(env_name: str, secret_name: str,
                   env_var_names: List[str]) -> None:
    """
    Mint a Modal secret into a per-experiment env from local env vars.

    Modal secrets are env-scoped — a secret created in `main` is invisible
    to `neurico-<EXP_ID>`. We re-mint here from the user's local
    environment so the per-experiment env can use it; the secret dies with
    the env at teardown.

    `secret_name` is the Modal secret name (e.g. "huggingface-secret").
    `env_var_names` is a list of local env-var names whose values become
    the secret's keys (e.g. ["HF_TOKEN"]).

    Uses --force so re-running register() overwrites any prior value, and
    additionally tolerates the "already exists" error path for older Modal
    CLI versions that ignore --force on existing secrets.
    """
    missing_env_vars = [n for n in env_var_names if not os.environ.get(n)]
    if missing_env_vars:
        raise RuntimeError(
            f"cannot mint Modal secret {secret_name!r} into env {env_name!r}: "
            f"required local env var(s) not set: {missing_env_vars}. "
            f"Set them in your shell or in neurico/.env before invoking."
        )
    cmd = [
        "modal", "secret", "create",
        f"--env={env_name}", "--force",
        secret_name,
    ]
    for name in env_var_names:
        cmd.append(f"{name}={os.environ[name]}")
    r = _run(cmd, timeout=60)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).lower()
        if "already" in msg or "exists" in msg:
            return
        raise RuntimeError(
            f"failed to mint secret {secret_name!r} in {env_name!r}: "
            f"{(r.stderr or r.stdout).strip()}"
        )


def _merge_manifests(
    existing: List[ManifestEntry],
    new: List[ManifestEntry],
) -> List[ManifestEntry]:
    """
    Combine two pull manifests, deduping by (from_volume, from). Later
    entries override earlier ones so a re-register can correct an entry's
    destination or required flag.
    """
    by_key: Dict[tuple, ManifestEntry] = {}
    for entry in existing + new:
        by_key[(entry["from_volume"], entry["from"])] = entry
    return list(by_key.values())


def register(
    exp_id: str,
    volumes: Optional[List[str]] = None,
    apps: Optional[List[str]] = None,
    required_secrets: Optional[Dict[str, List[str]]] = None,
    pull_manifest: Optional[List[ManifestEntry]] = None,
    share_hf_cache: bool = False,
    workspace: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Create the per-experiment env, mint required secrets, persist the
    pull manifest, and write the sentinel.

    `required_secrets` is a dict mapping Modal secret names to lists of
    local env vars whose values become the secret's keys. Example:

        register(exp_id, required_secrets={"huggingface-secret": ["HF_TOKEN"]})

    On a public-model run, pass `required_secrets={}` (or omit) — no
    secrets minted, no local env vars required.

    `pull_manifest` is a list of dicts declaring which volume paths to
    pull where (see ManifestEntry docstring). The template owns this —
    lifecycle just persists and replays it at pull_all() time. Entries
    are merged across multiple register() calls so a data-prep step and a
    training step in the same workspace contribute their own entries.

    Idempotent: calling twice with the same args produces no extra side
    effects. The pull_complete and torn_down flags are reset on each call,
    since a re-register implies the start of a new run.

    Refuses to re-key to a new exp_id if the workspace already has an
    in-flight (non-torn-down) experiment recorded under a different exp_id.
    Overwriting that sentinel would orphan the prior env in Modal with no
    local record — teardown the old experiment first.
    """
    existing_pre = load_sentinel(workspace) or {}
    prior_exp = existing_pre.get("exp_id")
    if prior_exp and prior_exp != exp_id and not existing_pre.get("torn_down"):
        raise RuntimeError(
            f"workspace already has an in-flight experiment {prior_exp!r}; "
            f"refusing to re-key to {exp_id!r} (the previous Modal env "
            f"would be orphaned). Teardown first with: "
            f"python lifecycle.py teardown --exp-id {prior_exp}"
        )

    env = env_name_for(exp_id)
    ensure_environment(env)

    # Write the sentinel BEFORE minting secrets so a partial failure leaves a
    # local record of the env. Without this, a secret-mint failure on the 2nd
    # of N secrets would leave Modal-side state (env + first secret) that no
    # local file knows about — no way to recover via lifecycle.py teardown.
    def _base(existing: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "exp_id": exp_id,
            "environment": env,
            "volumes": sorted(set(existing.get("volumes", []) + (volumes or []))),
            "apps": sorted(set(existing.get("apps", []) + (apps or []))),
            "secrets": sorted(set(existing.get("secrets", []))),
            "pull_manifest": _merge_manifests(
                existing.get("pull_manifest", []), pull_manifest or [],
            ),
            "share_hf_cache": share_hf_cache,
            "first_registered_at":
                existing.get("first_registered_at") or now_iso(),
            "last_registered_at": now_iso(),
            "pull_complete": False,
            "torn_down": False,
        }
    sentinel = update_sentinel(workspace, _base)

    minted: List[str] = []
    try:
        for secret_name, env_var_names in (required_secrets or {}).items():
            _ensure_secret(env, secret_name, env_var_names)
            minted.append(secret_name)
    finally:
        def _merge_secrets(existing: Dict[str, Any]) -> Dict[str, Any]:
            existing["secrets"] = sorted(
                set(existing.get("secrets", [])) | set(minted)
            )
            return existing
        sentinel = update_sentinel(workspace, _merge_secrets)

    return sentinel


def pull_all(
    exp_id: str,
    workspace: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Execute the pull manifest persisted by register().

    Walks `sentinel["pull_manifest"]`, pulls each entry, records errors
    for failed pulls, and marks `pull_complete=False` if any
    `required: True` entry failed or could not be found. Raises in that
    case so teardown() refuses to run.

    The lifecycle has no opinion about WHAT is being pulled — templates
    declare their own manifests in the register() call. To customize what
    a run pulls, edit the template's register() call.
    """
    sentinel = load_sentinel(workspace)
    if sentinel is None:
        raise RuntimeError(
            "no sentinel found; was register() called?"
        )
    env = sentinel["environment"]
    workspace_dir = workspace_root(workspace)

    manifest: List[ManifestEntry] = sentinel.get("pull_manifest", [])
    pulled: List[Dict[str, str]] = []
    errors: List[str] = []
    missing_required: List[str] = []

    for entry in manifest:
        volume = entry["from_volume"]
        remote = entry["from"]
        dest = (workspace_dir / entry["to"]).resolve()
        is_dir = bool(entry.get("is_dir", False))
        required = bool(entry.get("required", False))

        if volume not in sentinel["volumes"]:
            # A manifest entry naming a volume that register() never claimed is
            # almost always a typo. Silently skipping let a 'required' entry
            # appear complete and triggered teardown with the artifact never
            # copied off. Surface the typo instead.
            if required:
                missing_required.append(f"{volume}{remote} (unregistered volume)")
            continue

        r = volume_get(env, volume, remote, dest, is_dir=is_dir)
        if r.returncode == 0:
            pulled.append({"volume": volume, "remote": remote,
                           "dest": str(dest)})
            continue

        msg = (r.stderr or r.stdout).strip()
        # Modal CLI uses several phrasings depending on whether the remote
        # path was a file or directory and which Modal version is installed.
        msg_lc = msg.lower()
        not_found = any(s in msg_lc for s in (
            "not found",
            "does not exist",
            "no such file or directory",
        ))
        if not_found and not required:
            continue
        if required and not_found:
            missing_required.append(f"{volume}{remote}")
            continue
        errors.append(f"{volume}{remote}: {msg[:160]}")

    pull_complete = not errors and not missing_required

    # Merge under the sentinel lock so a parallel stage's update isn't lost.
    def _record(existing: Dict[str, Any]) -> Dict[str, Any]:
        existing["pull_complete"] = pull_complete
        existing["pull_errors"] = errors
        existing["pull_missing"] = missing_required
        existing["last_pulled_at"] = now_iso()
        return existing
    update_sentinel(workspace, _record)

    if not pull_complete:
        raise RuntimeError(
            f"pull_all() incomplete: errors={errors!r} "
            f"missing_required={missing_required!r}; teardown WILL NOT run. "
            f"Recover with: python lifecycle.py pull --exp-id {exp_id}"
        )

    return {"pulled": pulled, "workspace": str(workspace_dir)}


def upload_to_volume(
    exp_id: str,
    volume: str,
    src_workspace_rel: str,
    dest_volume_path: str,
    workspace: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Push a workspace-side file into a per-experiment Modal volume.

    Used by multi-stage chains where an earlier stage (e.g. data prep) tore
    its env down, but a later stage (e.g. training) needs the artifact back
    on the volume. The workspace `data/` directory is the source of truth
    between stages — this helper re-materializes it on the volume the new
    env's Modal app expects to read from.

    `src_workspace_rel` is relative to the workspace root (e.g.
    "data/train.jsonl"); `dest_volume_path` is the absolute path inside
    `volume` from the volume root (e.g. "/train.jsonl"). Note this is the
    volume-root path, NOT the container mount path: if the remote function
    mounts the volume at /data and reads /data/train.jsonl, the upload
    destination is "/train.jsonl" — passing "/data/train.jsonl" would land
    the file at /data/data/train.jsonl inside the container. The volume
    must already be in the sentinel's `volumes` list — register() claims it.

    Returns a dict with src/dest for logging. Raises RuntimeError on
    missing source, unregistered volume, or a failed CLI call.
    """
    sentinel = load_sentinel(workspace)
    if sentinel is None:
        raise RuntimeError("no sentinel found; was register() called?")
    if sentinel.get("torn_down"):
        raise RuntimeError(
            f"environment {sentinel['environment']!r} already torn down; "
            f"re-register before uploading. "
            f"Run: python lifecycle.py status to inspect, or rerun the "
            f"template's register() call."
        )
    if volume not in sentinel["volumes"]:
        raise RuntimeError(
            f"cannot upload to unregistered volume {volume!r}; "
            f"sentinel volumes = {sentinel['volumes']!r}"
        )

    workspace_dir = workspace_root(workspace)
    src = (workspace_dir / src_workspace_rel).resolve()
    if not src.exists():
        raise RuntimeError(
            f"upload source missing: {src} (no chained stage produced it?)"
        )

    env = sentinel["environment"]
    r = volume_put(env, volume, src, dest_volume_path)
    if r.returncode != 0:
        raise RuntimeError(
            f"failed to upload {src} -> {volume}{dest_volume_path}: "
            f"{(r.stderr or r.stdout).strip()[:240]}"
        )
    return {"src": str(src), "volume": volume, "remote": dest_volume_path}


def teardown(
    exp_id: str,
    force: bool = False,
    workspace: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Delete the per-experiment environment.

    Refuses unless sentinel.pull_complete is True. Pass force=True to
    override — the orchestrator sweep uses this only when register() ran
    but the script crashed before any artifacts existed to pull, so
    refusing would just leak the env.

    Returns the teardown result dict, or a skip marker if the sentinel is
    missing or already records `torn_down: True`.
    """
    sentinel = load_sentinel(workspace)
    if sentinel is None:
        return {"skipped": True, "reason": "no sentinel"}
    if sentinel.get("torn_down"):
        return {"skipped": True, "reason": "already torn down"}
    if not force and not sentinel.get("pull_complete"):
        raise RuntimeError(
            f"pull_complete=False; refusing to teardown. "
            f"Recover artifacts with: python lifecycle.py pull --exp-id {exp_id} "
            f"then re-run teardown. To force teardown anyway (loses any "
            f"un-pulled artifacts): python lifecycle.py teardown "
            f"--exp-id {exp_id} --force"
        )

    env = sentinel["environment"]
    for app in sentinel.get("apps", []):
        try:
            app_stop(env, app)
        except RuntimeError as exc:
            print(f"  warn: app stop {app}: {exc}", file=sys.stderr)

    try:
        delete_environment(env)
    except RuntimeError as exc:
        sentinel["teardown_error"] = str(exc)
        save_sentinel(sentinel, workspace)
        raise

    sentinel["torn_down"] = True
    sentinel["torn_down_at"] = now_iso()
    save_sentinel(sentinel, workspace)
    return {"environment": env, "stopped_apps": sentinel.get("apps", [])}


# CLI

def cmd_status(args: argparse.Namespace) -> int:
    sentinel = load_sentinel()
    if sentinel is None:
        print("(no sentinel — Modal not used in this workspace)")
        return 0
    print(json.dumps(sentinel, indent=2))
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    try:
        result = pull_all(args.exp_id)
    except RuntimeError as exc:
        print(f"pull failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


def cmd_teardown(args: argparse.Namespace) -> int:
    try:
        result = teardown(args.exp_id, force=args.force)
    except RuntimeError as exc:
        print(f"teardown failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="modal-training lifecycle")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_status = sub.add_parser("status",
                               help="print the workspace's modal sentinel")
    sp_status.set_defaults(func=cmd_status)

    sp_pull = sub.add_parser(
        "pull",
        help="execute the persisted pull manifest from Modal volumes",
    )
    sp_pull.add_argument("--exp-id", required=True)
    sp_pull.set_defaults(func=cmd_pull)

    sp_td = sub.add_parser("teardown",
                           help="delete the per-experiment environment")
    sp_td.add_argument("--exp-id", required=True)
    sp_td.add_argument("--force", action="store_true",
                       help="skip pull_complete check (orchestrator sweep only)")
    sp_td.set_defaults(func=cmd_teardown)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
