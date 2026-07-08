"""
Lifecycle helpers for the modal-vllm skill.

Thin wrapper over modal-training/lifecycle.py — same sentinel, same env
model, same secret/manifest machinery. The differences are:

  - register() always populates the sentinel's `apps` list with the
    deployed Modal app name so teardown() knows what to stop.
  - capture_endpoint() writes .neurico/modal_endpoint.json with URL +
    proxy-auth tokens for experiment code to read.
  - pull_all() additionally snapshots a redacted copy of that endpoint
    JSON to artifacts/vllm_endpoint.json (drops the secret, keeps the
    URL/model/flags for redeploy provenance).
  - teardown() stops every registered app before deleting the env.

CLI:
    python lifecycle.py status   --exp-id <id>
    python lifecycle.py pull     --exp-id <id>
    python lifecycle.py teardown --exp-id <id> [--force]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Reuse the training skill's lifecycle as the base — same workspace, same
# sentinel. The modal-training skill is always shipped alongside this one.
#
# We CANNOT do `import lifecycle as base` here, because the calling template
# already imported THIS file as `lifecycle` and cached it in sys.modules. A
# plain `import lifecycle` would re-bind to the cached vllm module instead
# of the training one. Load by explicit file path with a unique name so it
# lives at sys.modules["_modal_training_lifecycle"], unambiguously.
import importlib.util as _ilu  # noqa: E402


def _find_sibling_skill(skill_name: str, script_name: str) -> Path:
    """
    Walk upward from this file looking for a sibling skill's script.

    The previous implementation hard-coded `.claude/skills/...` resolved
    against the CWD. That broke under any non-cwd invocation (Modal
    container shells, agent subprocess started in a subdir, codex/gemini
    provider workspaces that use a different skills root). Walking up from
    __file__ instead means the lookup is invariant to the caller's CWD and
    to the provider directory naming.
    """
    here = Path(__file__).resolve().parent
    for ancestor in [here, *here.parents]:
        # ancestor/<skill_name>/scripts/<script_name>
        candidate = ancestor / skill_name / "scripts" / script_name
        if candidate.exists():
            return candidate
        # ancestor/skills/<skill_name>/scripts/<script_name>
        candidate = ancestor / "skills" / skill_name / "scripts" / script_name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"could not locate {skill_name}/scripts/{script_name} relative to "
        f"{Path(__file__).resolve()}; install the modal-training skill "
        f"alongside modal-vllm under the same skills root."
    )


_base_path = _find_sibling_skill("modal-training", "lifecycle.py")
_spec = _ilu.spec_from_file_location(
    "_modal_training_lifecycle", str(_base_path),
)
base = _ilu.module_from_spec(_spec)
sys.modules["_modal_training_lifecycle"] = base
_spec.loader.exec_module(base)  # type: ignore[union-attr]

ENDPOINT_REL = Path(".neurico") / "modal_endpoint.json"


def _run(cmd: List[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, check=False)


# register / capture / pull / teardown

def register(
    exp_id: str,
    app_name: str,
    volumes: Optional[List[str]] = None,
    required_secrets: Optional[Dict[str, List[str]]] = None,
    pull_manifest: Optional[List[Dict[str, Any]]] = None,
    share_hf_cache: bool = False,
    workspace: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Register the per-experiment env and the deployed app name.

    See modal-training/scripts/lifecycle.py:register for required_secrets
    and pull_manifest semantics. vLLM templates usually pass an empty
    manifest — the vllm-specific endpoint JSON redact happens inside this
    skill's pull_all(), independently of the volume-pull machinery.
    """
    return base.register(
        exp_id,
        volumes=volumes or [],
        apps=[app_name],
        required_secrets=required_secrets,
        pull_manifest=pull_manifest,
        share_hf_cache=share_hf_cache,
        workspace=workspace,
    )


def capture_endpoint(
    exp_id: str,
    url: str,
    key: str,
    secret: str,
    base_model: str,
    base_model_revision: str = "main",
    lora_repo: str = "",
    vllm_flags: Optional[Dict[str, Any]] = None,
    workspace: Optional[Path] = None,
) -> Path:
    """
    Persist endpoint URL + tokens for experiment code to read.

    The live JSON (with secret) lives in .neurico/ and is destroyed at
    teardown. A redacted copy (no secret) is left in artifacts/ for
    redeploy provenance.
    """
    ws = base.workspace_root(workspace)
    live = ws / ENDPOINT_REL
    live.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "exp_id": exp_id,
        "url": url,
        "key": key,
        "secret": secret,
        "base_model": base_model,
        "base_model_revision": base_model_revision,
        "lora_repo": lora_repo,
        "vllm_flags": vllm_flags or {},
        "captured_at": base.now_iso(),
    }
    live.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # Use update_sentinel so the read-modify-write is one locked transaction.
    # A prior load_sentinel + mutate + save_sentinel dropped the sentinel lock
    # between the read and write, letting a concurrent pull_all() or teardown()
    # commit its own change in between and get clobbered when this write landed
    # (e.g. pull_complete=True flipped back to the older value).
    def _mark_captured(existing: Dict[str, Any]) -> Dict[str, Any]:
        existing["endpoint_captured"] = True
        existing["endpoint_captured_at"] = base.now_iso()
        return existing
    base.update_sentinel(workspace, _mark_captured)
    return live


_REDACTED_KEYS = {"key", "secret", "token", "password", "api_key"}


def _redact_payload(obj: Any) -> Any:
    """Recursively strip secret-bearing keys from a payload."""
    if isinstance(obj, dict):
        return {
            k: _redact_payload(v)
            for k, v in obj.items()
            if k.lower() not in _REDACTED_KEYS
        }
    if isinstance(obj, list):
        return [_redact_payload(x) for x in obj]
    return obj


def _redact_endpoint(live: Path, dest: Path) -> None:
    """Recursively strip secret-bearing keys from endpoint JSON, write to dest."""
    if not live.exists():
        return
    data = json.loads(live.read_text(encoding="utf-8"))
    data = _redact_payload(data)
    data["redacted"] = True
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def pull_all(
    exp_id: str,
    workspace: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Snapshot endpoint provenance, then execute the persisted pull manifest.

    The vLLM-specific bit is redacting `.neurico/modal_endpoint.json` to
    `artifacts/vllm_endpoint.json` (drops the proxy-auth secret while
    keeping the URL/model/flags for redeploy provenance). After that, we
    delegate to base.pull_all() which walks any manifest entries the
    template declared in register().
    """
    sentinel = base.load_sentinel(workspace)
    if sentinel is None:
        raise RuntimeError("no sentinel found; was register() called?")

    ws = base.workspace_root(workspace)
    live = ws / ENDPOINT_REL
    artifacts = ws / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    dest = artifacts / "vllm_endpoint.json"

    if not live.exists():
        raise RuntimeError(
            "endpoint not captured; call capture_endpoint() after modal deploy "
            "before pull_all(). Teardown is gated to preserve reproducibility."
        )
    _redact_endpoint(live, dest)

    result = base.pull_all(exp_id, workspace=workspace)
    result["pulled"].append({"dest": str(dest), "kind": "vllm_endpoint"})
    return result


def teardown(
    exp_id: str,
    force: bool = False,
    workspace: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Stop every registered app, delete the env, and clear the live
    endpoint JSON. The redacted copy under artifacts/ stays as provenance.

    Self-heal: if the user followed the documented deploy -> capture flow
    but skipped the explicit pull step, the sentinel has
    endpoint_captured=True and pull_complete=False, and base.teardown()
    would refuse — leaving the deployed app running and billing. We treat
    that exact shape as "the user meant to pull" and run pull_all() first.
    If the auto-pull itself fails, surface a precise error and leave the
    env alive so the user can recover.
    """
    sentinel = base.load_sentinel(workspace)
    if sentinel is None:
        return {"skipped": True, "reason": "no sentinel"}

    auto_pulled = False
    if (not force
            and sentinel.get("endpoint_captured")
            and not sentinel.get("pull_complete")):
        try:
            pull_all(exp_id, workspace=workspace)
            auto_pulled = True
        except RuntimeError as exc:
            raise RuntimeError(
                f"vllm teardown: endpoint captured but pull_all() failed "
                f"during self-heal; env preserved. Original error: {exc}"
            )

    result = base.teardown(exp_id, force=force, workspace=workspace)
    if auto_pulled:
        result["auto_pulled"] = True

    # Clear the live endpoint JSON (the redacted copy in artifacts/ stays).
    ws = base.workspace_root(workspace)
    live = ws / ENDPOINT_REL
    if live.exists():
        live.unlink()
    result["endpoint_cleared"] = True
    return result


# CLI

def cmd_status(args: argparse.Namespace) -> int:
    sentinel = base.load_sentinel()
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
    p = argparse.ArgumentParser(description="modal-vllm lifecycle")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_status = sub.add_parser("status")
    sp_status.set_defaults(func=cmd_status)

    sp_pull = sub.add_parser("pull")
    sp_pull.add_argument("--exp-id", required=True)
    sp_pull.set_defaults(func=cmd_pull)

    sp_td = sub.add_parser("teardown")
    sp_td.add_argument("--exp-id", required=True)
    sp_td.add_argument("--force", action="store_true")
    sp_td.set_defaults(func=cmd_teardown)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
