"""Keep the model registry current: discover the newest open-weight members of tracked families.

Queries the Hugging Face Hub for each tracked author, keeps text chat/instruct models with
open weights, reads parameter counts from the safetensors metadata, estimates the bf16 memory
a single GPU would need, and:

- writes ``catalog/models_latest.yaml`` (everything discovered, newest first, with sizes);
- adds new members that fit the campaign's GPU budget to ``catalog/models.yaml`` as
  ``access: vllm:<hf_id>`` entries tagged ``discovered: <date>`` and ``generation``;
- marks older catalog entries of the same family ``superseded_by`` the newest generation;
- drops a note in ``inbox/`` listing what is new, for the planner.

The daemon runs this before every planner round; ``./neurico safety kb refresh-models`` runs it
by hand. Nothing is downloaded here.
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from safety.kb import KB, load_yaml, save_yaml, slugify, utc_now

TRACKED_AUTHORS = {
    "Qwen": "qwen", "deepseek-ai": "deepseek", "moonshotai": "kimi", "zai-org": "glm",
}
# Main-line text model names per author (anything else: VL/audio/tooling/experimental repos).
MAINLINE = {
    "Qwen": re.compile(r"^Qwen\d(?:\.\d)?-[0-9.]+B(?:-A[0-9.]+B)?(?:-Instruct|-Thinking|-Flash)?$"),
    "deepseek-ai": re.compile(r"^DeepSeek-(?:V\d(?:\.\d)?|R\d)(?:-(?:Flash|Pro|Lite|Chat|Distill-[A-Za-z0-9.-]+|0528-Qwen3-8B))?(?:-\d{4})?$"),
    "moonshotai": re.compile(r"^(?:Kimi-K\d(?:\.\d)?(?:-Instruct|-Thinking)?(?:-\d{4})?|Moonlight-[0-9]+B-A[0-9]+B-Instruct)$"),
    "zai-org": re.compile(r"^GLM-\d(?:\.\d)?(?:-Flash|-Air|-[0-9]+B(?:-0414|-Chat)?)?$|^GLM-Z\d-[0-9]+B-0414$"),
}
GENERATION = {
    "Qwen": re.compile(r"^(Qwen\d(?:\.\d)?)"), "deepseek-ai": re.compile(r"^(DeepSeek-(?:V\d(?:\.\d)?|R\d))"),
    "moonshotai": re.compile(r"^(Kimi-K\d(?:\.\d)?|Moonlight)"), "zai-org": re.compile(r"^(GLM-(?:Z)?\d(?:\.\d)?)"),
}
BYTES_PER_PARAM_BF16 = 2.0


def _get(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "neurico-safety/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _generation(model_id: str) -> str:
    author, name = model_id.split("/", 1)
    pattern = GENERATION.get(author)
    m = pattern.match(name) if pattern else None
    return m.group(1).lower() if m else name.lower()


def discover(author: str, limit: int = 200) -> List[Dict[str, Any]]:
    rows = []
    pattern = MAINLINE.get(author)
    for m in _get(f"https://huggingface.co/api/models?author={author}&sort=lastModified&direction=-1&limit={limit}"):
        mid = m["id"]
        if pattern and not pattern.match(mid.split("/", 1)[1]):
            continue
        try:
            info = _get(f"https://huggingface.co/api/models/{mid}?blobs=true")
        except Exception:  # noqa: BLE001
            continue
        if info.get("pipeline_tag") not in ("text-generation", "image-text-to-text", None):
            continue
        params = ((info.get("safetensors") or {}).get("total") or 0) / 1e9
        weights_gb = sum(s.get("size", 0) for s in info.get("siblings", []) if s.get("rfilename", "").endswith(".safetensors")) / 1e9
        if not params and not weights_gb:
            continue
        rows.append({
            "hf_id": mid, "family": TRACKED_AUTHORS[author], "generation": _generation(mid),
            "params_b": round(params, 1), "weights_gb": round(weights_gb, 1),
            "bf16_gb": round(params * BYTES_PER_PARAM_BF16, 1) if params else round(weights_gb, 1),
            "last_modified": (info.get("lastModified") or "")[:10], "gated": bool(info.get("gated")),
            "license": next((t.split(":", 1)[1] for t in info.get("tags", []) if t.startswith("license:")), None),
            "downloads": info.get("downloads"),
        })
    return rows


def refresh(kb: KB, *, max_gpu_gb: float = 80.0, headroom: float = 0.75) -> Dict[str, Any]:
    kb.ensure_layout()
    discovered: List[Dict[str, Any]] = []
    for author in TRACKED_AUTHORS:
        try:
            discovered += discover(author)
        except Exception as e:  # noqa: BLE001
            discovered.append({"hf_id": f"{author}/<error>", "family": TRACKED_AUTHORS[author], "error": str(e)[:200]})
    discovered.sort(key=lambda r: (r.get("family", ""), r.get("last_modified", "")), reverse=True)
    save_yaml(kb.catalog_dir / "models_latest.yaml",
              {"refreshed": utc_now(), "max_gpu_gb": max_gpu_gb, "models": discovered})

    catalog_path = kb.catalog_dir / "models.yaml"
    catalog = load_yaml(catalog_path) or {"models": []}
    by_hf = {str(m.get("access", "")).split(":", 1)[1]: m for m in catalog["models"]
             if str(m.get("access", "")).startswith("vllm:")}
    added: List[str] = []
    newest_gen: Dict[str, Any] = {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for row in discovered:
        if "error" in row:
            continue
        fam = row["family"]
        if fam not in newest_gen or row["last_modified"] > newest_gen[fam][1]:
            newest_gen[fam] = (row["generation"], row["last_modified"])
        fits = row["bf16_gb"] <= max_gpu_gb * headroom
        if row["hf_id"] in by_hf or not fits or row.get("gated"):
            continue
        entry = {
            "id": slugify(row["hf_id"].split("/", 1)[1]), "family": fam, "vendor": row["hf_id"].split("/")[0],
            "access": f"vllm:{row['hf_id']}", "params_b": row["params_b"], "generation": row["generation"],
            "gpu_memory_gb": int(min(max_gpu_gb, max(8, row["bf16_gb"] * 1.3 + 4))),
            "gpu_memory_utilization": round(min(0.9, max(0.3, (row["bf16_gb"] * 1.3 + 4) / max_gpu_gb)), 2),
            "max_model_len": 16384 if row["params_b"] <= 14 else 8192,
            "license": row["license"], "release_date": row["last_modified"], "discovered": today,
            "serve_args": ["--trust-remote-code"] if fam in ("kimi", "glm", "deepseek") else [],
        }
        catalog["models"].append(entry)
        by_hf[row["hf_id"]] = entry
        added.append(entry["id"])
    # A model is superseded only when a NEWER generation of its family has a member of a similar
    # size class (within 2.5x parameters) that fits one GPU; otherwise it stays the best of its class.
    servable = [m for m in catalog["models"] if str(m.get("access", "")).startswith("vllm:") and not m.get("role")]
    for m in servable:
        m.setdefault("generation", _generation(m["access"].split(":", 1)[1]))
    gen_date = {r["generation"]: r["last_modified"] for r in discovered if "error" not in r}
    for m in servable:
        fam, gen, params = m.get("family"), m.get("generation"), float(m.get("params_b") or 0)
        newer = [o for o in servable if o.get("family") == fam and o is not m
                 and gen_date.get(o.get("generation"), "") > gen_date.get(gen, "")
                 and params and float(o.get("params_b") or 0) and 1 / 2.5 <= float(o["params_b"]) / params <= 2.5]
        if newer:
            m["superseded_by"] = max(newer, key=lambda o: gen_date.get(o.get("generation"), ""))["id"]
        else:
            m.pop("superseded_by", None)
    save_yaml(catalog_path, catalog)

    note = None
    if added:
        kb.inbox_dir.mkdir(parents=True, exist_ok=True)
        note = kb.inbox_dir / f"{today}-new-models.md"
        lines = [f"# New open-weight models added to the catalog ({today})", "",
                 "Newest generation per family: " + ", ".join(f"{f}={g[0]} ({g[1]})" for f, g in sorted(newest_gen.items())), "",
                 "Prefer these as subjects; older generations are baselines only.", ""]
        for mid in added:
            e = by_hf[next(k for k, v in by_hf.items() if v.get("id") == mid)]
            lines.append(f"- {mid}: {e['access']} {e['params_b']}B, released {e['release_date']}, needs ~{e['gpu_memory_gb']} GB")
        note.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"discovered": len([r for r in discovered if "error" not in r]), "added": added,
            "newest": {f: g[0] for f, g in newest_gen.items()}, "inbox": str(note) if note else None}


def latest_models_summary(kb: KB, limit: int = 30) -> str:
    """Short text block for planner prompts: newest generation per family and catalog ids."""
    latest = load_yaml(kb.catalog_dir / "models_latest.yaml") or {}
    catalog = kb.models()
    lines = [f"(refreshed {latest.get('refreshed', 'never')}; ids in the registry can be used in jobs)"]
    newest: Dict[str, str] = {}
    for row in latest.get("models", []):
        if "error" in row:
            continue
        newest.setdefault(row["family"], row["generation"])
    for fam, gen in sorted(newest.items()):
        ids = [m["id"] for m in catalog.values() if m.get("family") == fam and m.get("generation") == gen]
        older = [m["id"] for m in catalog.values() if m.get("family") == fam and m.get("superseded_by")]
        lines.append(f"- {fam}: newest generation {gen}; registry ids {ids or '(none fits one GPU)'}; older (baselines only): {older[:6]}")
    return "\n".join(lines[: limit + 1])
