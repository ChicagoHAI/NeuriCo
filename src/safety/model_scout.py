"""Model scout: an agent run that keeps the model registry current, plus the merge step.

The agent (templates/agents/model_scout.txt) has web access, reads catalog/families.yaml (data:
which families, where to look, what counts as a member, the single-GPU policy), verifies releases
against Hugging Face and vendor docs, and writes:

    catalog/models_latest.yaml            the current picture per family
    catalog/proposals/models-<run>.yaml   registry entries to add
    inbox/<date>-model-scout.md           what changed, for the planner and for humans

Python here does only two things with no family-specific knowledge: validate proposal entries
against the registry schema and merge them, and compute `superseded_by` from release dates and
parameter counts under the policy in families.yaml.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.prompt_registry import PromptRegistry, RenderedPrompt
from safety.kb import KB, PROJECT_ROOT, load_yaml, save_yaml, utc_now

TEMPLATE_ID = "agents/model_scout.txt"   # under templates/; the id config/agents.yaml names for model_scout
TEMPLATE = PROJECT_ROOT / "templates" / TEMPLATE_ID
REQUIRED_ENTRY_KEYS = ("id", "family", "access", "params_b", "generation", "gpu_memory_gb")


def policy(kb: KB) -> Dict[str, Any]:
    data = load_yaml(kb.catalog_dir / "families.yaml") or {}
    return {"single_gpu_memory_gb": 80, "headroom": 0.75, "size_class_ratio": 2.5, "stale_after_hours": 24,
            **(data.get("policy") or {})}


def is_stale(kb: KB) -> bool:
    latest = load_yaml(kb.catalog_dir / "models_latest.yaml") or {}
    stamp = latest.get("refreshed")
    if not stamp:
        return True
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(str(stamp))
    except ValueError:
        return True
    return age > timedelta(hours=float(policy(kb)["stale_after_hours"]))


def render(kb: KB, scout_run: str) -> RenderedPrompt:
    """The scout prompt with the template and variable hashes the ledger records."""
    fields = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "scout_run": scout_run, "kb_root": str(kb.root),
        "families": (kb.catalog_dir / "families.yaml").read_text(encoding="utf-8"),
        "catalog_models": (kb.catalog_dir / "models.yaml").read_text(encoding="utf-8")[:20000],
        "previous_latest": (kb.catalog_dir / "models_latest.yaml").read_text(encoding="utf-8")[:12000]
        if (kb.catalog_dir / "models_latest.yaml").exists() else "(absent)",
    }
    return PromptRegistry().render(TEMPLATE_ID, fields)


def render_prompt(kb: KB, scout_run: str) -> str:
    return render(kb, scout_run).text


def validate_entry(entry: Any, registry_access: set) -> Optional[str]:
    """Return a reason the proposal entry is rejected, or None."""
    if not isinstance(entry, dict):
        return "not a mapping"
    access = str(entry.get("access") or "")
    if ":" not in access:
        return "access must be <scheme>:<target>"
    local = access.startswith("vllm:")
    required = REQUIRED_ENTRY_KEYS if local else ("id", "family", "access", "generation")
    missing = [k for k in required if entry.get(k) in (None, "")]
    if missing:
        return f"missing {missing}"
    if access in registry_access:
        return "already in the registry"
    if local:
        try:
            float(entry["params_b"]); float(entry["gpu_memory_gb"])
        except (TypeError, ValueError):
            return "params_b and gpu_memory_gb must be numbers"
    return None


def merge_proposals(kb: KB, proposal_file: Optional[Path] = None) -> Dict[str, Any]:
    """Merge validated proposal entries into catalog/models.yaml and recompute supersession."""
    catalog_path = kb.catalog_dir / "models.yaml"
    catalog = load_yaml(catalog_path) or {"models": []}
    files = [proposal_file] if proposal_file else sorted((kb.catalog_dir / "proposals").glob("models-*.yaml"))
    accepted, rejected = [], []
    registry_access = {str(m.get("access")) for m in catalog["models"]}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for path in files:
        if not path or not path.exists():
            continue
        data = load_yaml(path) or {}
        entries = data.get("models") if isinstance(data, dict) else data
        for entry in entries or []:
            reason = validate_entry(entry, registry_access)
            if reason:
                rejected.append((path.name, entry.get("id") if isinstance(entry, dict) else str(entry)[:40], reason))
                continue
            entry = dict(entry)
            if not str(entry["access"]).startswith("vllm:"):
                entry["api"] = True  # served by a provider, not by us
            entry.setdefault("discovered", today)
            entry.setdefault("proposed_by", path.stem)
            catalog["models"].append(entry)
            registry_access.add(str(entry["access"]))
            accepted.append(entry["id"])
        merged = path.with_suffix(".merged.yaml")
        path.replace(merged)
    recompute_supersession(catalog, policy(kb))
    save_yaml(catalog_path, catalog)
    return {"accepted": accepted, "rejected": rejected}


def recompute_supersession(catalog: Dict[str, Any], pol: Dict[str, Any]) -> None:
    """`superseded_by` = the newest later-released member of the same family within the size class."""
    ratio = float(pol.get("size_class_ratio", 2.5))
    servable = [m for m in catalog.get("models", []) if not m.get("role") and m.get("release_date")]
    for m in servable:
        params = float(m.get("params_b") or 0)
        newer = [o for o in servable if o.get("family") == m.get("family") and o is not m
                 and str(o.get("release_date")) > str(m.get("release_date")) and params
                 and float(o.get("params_b") or 0) and 1 / ratio <= float(o["params_b"]) / params <= ratio]
        if newer:
            m["superseded_by"] = max(newer, key=lambda o: str(o.get("release_date")))["id"]
        else:
            m.pop("superseded_by", None)


def latest_models_summary(kb: KB) -> str:
    """Text block for planner prompts: newest generation per family and usable registry ids."""
    latest = load_yaml(kb.catalog_dir / "models_latest.yaml") or {}
    registry = kb.models()
    lines = [f"(scout refreshed {latest.get('refreshed', 'never')}; registry ids below can be used in jobs)"]
    for fam, info in sorted((latest.get("families") or {}).items()):
        current = [m["id"] for m in registry.values() if m.get("family") == fam and not m.get("superseded_by")
                   and not m.get("role")]
        older = [m["id"] for m in registry.values() if m.get("family") == fam and m.get("superseded_by")]
        lines.append(f"- {fam}: newest generation {info.get('newest_generation')} (released {info.get('released')}); "
                     f"current registry ids {current or '(none fits one GPU)'}; older, baselines only: {older[:6]}")
    return "\n".join(lines)


def run_scout(kb: KB, *, provider: str = "codex", model: Optional[str] = None, agent_auth: Optional[str] = None,
              timeout: int = 2400, dry_run: bool = False) -> Dict[str, Any]:
    """One scout session in the KB root (the model_scout role; Codex by default), then the merge."""
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from core.agent_factory import AgentFactory

    kb.ensure_layout()
    (kb.catalog_dir / "proposals").mkdir(parents=True, exist_ok=True)
    scout_run = datetime.now(timezone.utc).strftime("scout-%Y%m%d-%H%M%S")
    rendered = render(kb, scout_run)
    prompt = rendered.text
    log_dir = kb.logs_dir / "scout"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / f"{scout_run}_prompt.md").write_text(prompt, encoding="utf-8")
    if dry_run:
        return {"ok": True, "scout_run": scout_run, "prompt": str(log_dir / f"{scout_run}_prompt.md")}
    # Artifacts keep the scout-run name; the prompt was saved as <run>_prompt.md above.
    factory = AgentFactory()
    spec = factory.spec("model_scout", provider=provider, model=model, auth=agent_auth, timeout=timeout,
                        transcript={"logs_dir": log_dir, "stem": scout_run, "save_prompt": False})
    result = factory.run(factory.build(spec, {"NEURICO_SAFETY_KB": str(kb.root)}), prompt, kb.root, prompt_meta=rendered)
    outcome = merge_proposals(kb)
    latest = load_yaml(kb.catalog_dir / "models_latest.yaml") or {}
    record = {"ok": result.success, "scout_run": scout_run, "at": utc_now(),
              "refreshed": latest.get("refreshed"), "accepted": outcome["accepted"], "rejected": outcome["rejected"],
              "log": str(result.log_file), "agent_run_id": result.run_id, "cost_usd": result.usage.cost_usd}
    save_yaml(log_dir / f"{scout_run}_outcome.yaml", record)
    return record
