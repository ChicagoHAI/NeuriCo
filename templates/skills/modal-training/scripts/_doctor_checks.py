"""
Shared doctor checks for the modal-training and modal-vllm skills.

Importable from either skill's check_modal_setup.py. Each check returns a
dict with at least {"ok": bool}; failures additionally include
{"fix": "<command>"} so callers can surface actionable guidance.

Exit-code convention used by callers:
    0  all green
    1  soft fix (user can resolve)
    2  hard fail (structural)
    10 probe roundtrip failed
"""
from __future__ import annotations

import json
import os
import secrets as _secrets
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

MIN_MODAL_VERSION = (1, 4)
WORKSPACE_FREE_GB_WARN = 5
WORKSPACE_FREE_GB_HARD = 1
ENV_QUOTA_WARN = 40           # Modal default is 50 envs/workspace


def _run(cmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False
    )


def _parse_version(s: str) -> Optional[tuple]:
    for token in s.replace(":", " ").replace(",", " ").split():
        if token and token[0].isdigit() and "." in token:
            try:
                return tuple(int(x) for x in token.split(".")[:3])
            except ValueError:
                continue
    return None


def check_cli() -> Dict[str, Any]:
    """Verify the modal CLI is installed at an acceptable version."""
    path = shutil.which("modal")
    if path is None:
        return {
            "ok": False,
            "fix": "pip install modal",
            "detail": "modal CLI not found in PATH",
        }
    r = _run(["modal", "--version"])
    if r.returncode != 0:
        return {"ok": False, "fix": "pip install --upgrade modal",
                "detail": f"modal --version exited {r.returncode}"}
    version = _parse_version(r.stdout) or (0, 0, 0)
    if version < MIN_MODAL_VERSION:
        return {
            "ok": False,
            "fix": "pip install --upgrade 'modal>=1.4'",
            "version": ".".join(map(str, version)),
            "detail": f"installed modal {version} < required {MIN_MODAL_VERSION}",
        }
    return {"ok": True, "version": ".".join(map(str, version)), "path": path}


def _auth_source() -> str:
    """
    Identify which auth path the CLI is using.

    The Modal CLI honors MODAL_TOKEN_ID / MODAL_TOKEN_SECRET first, then
    ~/.modal.toml. In the Docker image, ~/.modal.toml is bind-mounted
    from the host. Knowing which path is active gives precise fix advice
    when auth breaks.
    """
    if os.environ.get("MODAL_TOKEN_ID") and os.environ.get("MODAL_TOKEN_SECRET"):
        return "env_vars"
    if Path("~/.modal.toml").expanduser().exists():
        return "modal_toml"
    return "none"


def check_auth() -> Dict[str, Any]:
    """Verify the Modal auth token works and report which source supplied it."""
    r = _run(["modal", "token", "info"])
    source = _auth_source()
    if r.returncode != 0:
        # Fix message depends on context. Inside a container with no host
        # mount and no env vars, telling the user to "modal token new" inside
        # the container is wrong (no browser). Surface both options.
        fix = (
            "On host: `modal token new` (creates ~/.modal.toml which "
            "neurico's Docker run mounts in). "
            "For CI / autonomous runs: export MODAL_TOKEN_ID and "
            "MODAL_TOKEN_SECRET before invoking."
        )
        return {"ok": False, "fix": fix, "source": source,
                "detail": "modal token info failed; not authenticated"}
    workspace = None
    user = None
    for line in r.stdout.splitlines():
        if line.startswith("Workspace:"):
            workspace = line.split(":", 1)[1].strip().split()[0]
        elif line.startswith("User:"):
            user = line.split(":", 1)[1].strip().split()[0]
    if not workspace:
        return {"ok": False, "fix": "modal token new (on host)",
                "source": source,
                "detail": "could not parse workspace from token info"}
    return {"ok": True, "workspace": workspace, "user": user,
            "source": source}


def check_envs() -> Dict[str, Any]:
    """Report Modal environment quota usage and any stale neurico-* envs."""
    r = _run(["modal", "environment", "list"])
    if r.returncode != 0:
        return {"ok": False, "fix": "Check Modal dashboard / re-auth",
                "detail": f"modal environment list exited {r.returncode}"}
    names: List[str] = []
    for line in r.stdout.splitlines():
        s = line.strip()
        if not s or s.startswith(("┏", "┡", "└", "┃", "━", "┳", "┻")):
            continue
        if s.startswith("│"):
            parts = [p.strip() for p in s.strip("│").split("│")]
            if parts and parts[0] and parts[0] != "name":
                names.append(parts[0])
    neurico_envs = [n for n in names if n.startswith("neurico-")]
    out: Dict[str, Any] = {
        "ok": True,
        "active_envs": len(names),
        "active_neurico_envs": len(neurico_envs),
        "neurico_env_names": neurico_envs,
    }
    if len(names) >= ENV_QUOTA_WARN:
        out["warning"] = (
            f"{len(names)} envs in use (Modal default cap is 50). "
            f"Stale neurico-* envs can be deleted with: "
            f"modal environment delete <name> -y"
        )
    return out


def check_secret(secret_name: str,
                 source_env_vars: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Check that a Modal secret can be provisioned for a per-experiment env.

    With per-env mint semantics (lifecycle.register's required_secrets),
    what actually matters is whether the local env vars the lifecycle
    would read are set — not whether the secret exists in `main`. Modal
    won't let us read secret values back from `main` anyway.

    `source_env_vars` is the list of local env vars used to mint the
    secret (e.g. ["HF_TOKEN"] for huggingface-secret). If provided, we
    verify they are set in the local environment. As a courtesy we also
    check whether a same-named secret exists in `main` so users see both
    pieces of context.
    """
    out: Dict[str, Any] = {"name": secret_name, "ok": True}

    # Local env vars are the ground truth — lifecycle mints from these.
    if source_env_vars:
        missing = [n for n in source_env_vars if not os.environ.get(n)]
        if missing:
            out["ok"] = False
            out["fix"] = (
                f"Set {missing} in your shell or in neurico/.env. "
                f"lifecycle.register() reads these to mint "
                f"{secret_name!r} into each per-experiment env."
            )
            out["missing_env_vars"] = missing
            return out
        out["source_env_vars_set"] = source_env_vars

    # Best-effort: see if a same-named secret already exists in `main`. Not a
    # hard requirement (we re-mint per env), but useful context for the user.
    r = _run(["modal", "secret", "list"])
    if r.returncode == 0:
        out["exists_in_main"] = any(
            secret_name in line for line in r.stdout.splitlines()
        )
    return out


def check_disk(workspace_path: Path) -> Dict[str, Any]:
    """Verify the workspace has enough free disk for pulled artifacts."""
    try:
        usage = shutil.disk_usage(workspace_path)
    except FileNotFoundError:
        return {"ok": False, "fix": f"mkdir -p {workspace_path}",
                "detail": f"path missing: {workspace_path}"}
    free_gb = usage.free / (1024 ** 3)
    out = {"ok": True, "free_gb": round(free_gb, 1),
           "path": str(workspace_path)}
    if free_gb < WORKSPACE_FREE_GB_HARD:
        out["ok"] = False
        out["fix"] = "Free disk space; LoRA adapters need ~5 GB"
    elif free_gb < WORKSPACE_FREE_GB_WARN:
        out["warning"] = (
            f"only {free_gb:.1f} GB free; LoRA adapter pulls need ~5 GB"
        )
    return out


def probe_roundtrip() -> Dict[str, Any]:
    """
    End-to-end: create a throwaway env + volume, delete the env, confirm
    cleanup. ~5 seconds, no GPU spend.
    """
    env_name = f"neurico-doctor-{_secrets.token_hex(4)}"
    vol_name = f"{env_name}-probe-vol"
    steps: List[Dict[str, Any]] = []

    def step(name: str, cmd: List[str]) -> bool:
        r = _run(cmd, timeout=60)
        ok = r.returncode == 0
        steps.append({"name": name, "ok": ok, "cmd": " ".join(cmd),
                      "stderr": r.stderr.strip()[:200] if not ok else None})
        return ok

    if not step("create_env", ["modal", "environment", "create", env_name]):
        return {"ok": False, "steps": steps,
                "detail": "could not create probe environment"}

    volume_ok = step("create_volume",
                     ["modal", "volume", "create",
                      f"--env={env_name}", vol_name])
    # Always attempt cleanup, even if create_volume failed — we must not leak
    # the env we just created.
    cleanup_ok = step("delete_env",
                      ["modal", "environment", "delete", env_name, "-y"])

    if not cleanup_ok:
        return {
            "ok": False,
            "steps": steps,
            "detail": (f"probe env left over; run: "
                       f"modal environment delete {env_name} -y"),
            "leaked_env": env_name,
        }
    if not volume_ok:
        return {"ok": False, "steps": steps,
                "detail": "could not create probe volume"}
    return {"ok": True, "steps": steps}


def run_all(
    workspace_path: Path,
    required_secrets: Optional[Dict[str, List[str]]] = None,
    probe: bool = False,
) -> Dict[str, Any]:
    """
    Compose every check. Caller maps the dict to exit codes.

    `required_secrets` mirrors lifecycle.register's signature: a dict
    mapping Modal secret names to the local env vars used to mint them.
    Pass {} (or omit) for fully-public-model runs that don't need any
    secrets.
    """
    required_secrets = required_secrets or {}
    out: Dict[str, Any] = {
        "ok": True,
        "modal_cli": check_cli(),
    }
    if not out["modal_cli"]["ok"]:
        out["ok"] = False
        return out

    out["auth"] = check_auth()
    if not out["auth"]["ok"]:
        out["ok"] = False
        return out

    out["envs"] = check_envs()
    if not out["envs"]["ok"]:
        out["ok"] = False

    out["secrets"] = {}
    for secret_name, source_env_vars in required_secrets.items():
        result = check_secret(secret_name, source_env_vars=source_env_vars)
        out["secrets"][secret_name] = result
        if not result["ok"]:
            out["ok"] = False

    out["disk"] = check_disk(workspace_path)
    if not out["disk"]["ok"]:
        out["ok"] = False

    if probe:
        out["probe"] = probe_roundtrip()
        if not out["probe"]["ok"]:
            out["ok"] = False
    else:
        out["probe"] = {"skipped": True}

    return out


def print_human(report: Dict[str, Any]) -> None:
    def line(label: str, status: bool, extra: str = "") -> None:
        mark = "OK  " if status else "FAIL"
        print(f"  [{mark}] {label:<24} {extra}")

    print("Modal doctor")
    print("-" * 40)
    cli = report["modal_cli"]
    line("modal CLI", cli["ok"], cli.get("version", cli.get("detail", "")))
    if not cli["ok"]:
        print(f"         fix: {cli['fix']}")
        return

    auth = report["auth"]
    source = auth.get("source", "?")
    source_label = {
        "modal_toml": "~/.modal.toml",
        "env_vars":   "MODAL_TOKEN_ID/SECRET",
        "none":       "no auth source",
    }.get(source, source)
    line("auth", auth["ok"],
         f"{auth.get('workspace', auth.get('detail', ''))} ({source_label})")
    if not auth["ok"]:
        print(f"         fix: {auth['fix']}")
        return

    envs = report["envs"]
    extra = (f"{envs.get('active_neurico_envs', 0)} neurico envs, "
             f"{envs.get('active_envs', 0)} total")
    line("environments", envs["ok"], extra)
    if envs.get("warning"):
        print(f"         warn: {envs['warning']}")

    for name, result in report.get("secrets", {}).items():
        if result["ok"]:
            extra = "present"
            in_main = result.get("exists_in_main")
            if in_main is False:
                extra = "local env vars set (no copy in main yet — OK)"
            line(f"secret: {name}", True, extra)
        else:
            missing = result.get("missing_env_vars") or result.get("detail", "missing")
            line(f"secret: {name}", False, f"missing env vars: {missing}")
            print(f"         fix: {result['fix']}")

    disk = report["disk"]
    line("workspace disk", disk["ok"], f"{disk.get('free_gb', '?')} GB free")
    if disk.get("warning"):
        print(f"         warn: {disk['warning']}")
    if not disk["ok"]:
        print(f"         fix: {disk['fix']}")

    probe = report["probe"]
    if probe.get("skipped"):
        line("probe", True, "(skipped; use --probe to enable)")
    else:
        line("probe roundtrip", probe["ok"],
             probe.get("detail", "create/delete env succeeded"))
        if not probe["ok"] and probe.get("leaked_env"):
            print(f"         leaked: {probe['leaked_env']}")

    print("-" * 40)
    print("STATUS:", "OK" if report["ok"] else "ISSUES — see above")
