"""Periodic markdown digest from runs/ and findings/, plus per-family scorecards."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from safety.kb import KB, utc_now


def _recent(records: List[Dict[str, Any]], key: str, days: int) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for record in records:
        stamp = record.get(key)
        try:
            when = datetime.fromisoformat(stamp) if stamp else None
        except ValueError:
            when = None
        if when is None or when >= cutoff:
            out.append(record)
    return out


def scorecards(kb: KB) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """family -> model -> eval -> latest metrics (from suite runs and skill results)."""
    models = kb.models()
    cards: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(lambda: defaultdict(dict))
    for run in sorted(kb.list_runs(), key=lambda r: r.get("finished") or ""):
        pairs = run.get("pairs") or [{"eval": r.get("eval_id"), "model": r.get("model_id"), "status": r.get("status"),
                                      "metrics": r.get("metrics"), "n": r.get("n")} for r in run.get("results") or []]
        for pair in pairs:
            if pair.get("status") != "success" or not pair.get("eval"):
                continue
            family = models.get(pair["model"], {}).get("family", "other")
            cards[family][pair["model"]][pair["eval"]] = {"metrics": pair.get("metrics"), "n": pair.get("n"),
                                                          "run": run["run_id"], "finished": run.get("finished")}
    return cards


def write_digest(kb: KB, days: int = 7) -> Path:
    kb.ensure_layout()
    runs = _recent(kb.list_runs(), "finished", days)
    findings = kb.list_findings()
    new_findings = _recent(findings, "created", days)
    lines = [f"# Safety engine digest: last {days} day(s)", "", f"Generated {utc_now()}", ""]
    lines += [f"## Runs ({len(runs)})", ""]
    for run in runs:
        extra = run.get("github_url") or run.get("results_dir") or run.get("workspace") or ""
        lines.append(f"- {run['run_id']} [{run.get('kind')}] {run.get('title', '')} ({run.get('finished')}) {extra}")
        for pair in (run.get("pairs") or [])[:20]:
            lines.append(f"    - {pair.get('eval')} x {pair.get('model')}: {pair.get('status')} n={pair.get('n')} "
                         f"{_fmt_metrics(pair.get('metrics'))}")
    lines += ["", f"## Findings: {len(new_findings)} new, {len(findings)} total", ""]
    by_status: Dict[str, int] = defaultdict(int)
    for finding in findings:
        by_status[finding.get("status", "?")] += 1
    lines.append("status counts: " + ", ".join(f"{k}={v}" for k, v in sorted(by_status.items())))
    for finding in new_findings:
        lines.append(f"- {finding['id']} [{finding.get('status')}] {finding.get('title')} "
                     f"(models: {', '.join(finding.get('models') or [])})")
    lines += ["", "## Scorecards (latest successful result per model x eval)", ""]
    for family, per_model in scorecards(kb).items():
        lines.append(f"### {family}")
        for model, per_eval in per_model.items():
            lines.append(f"- {model}")
            for eval_id, entry in sorted(per_eval.items()):
                lines.append(f"    - {eval_id}: {_fmt_metrics(entry.get('metrics'))} (n={entry.get('n')}, {entry['run']})")
        lines.append("")
    lines += [f"## Spend (run ledgers, last {days} day(s))", ""] + spend_lines(kb, days) + [""]
    path = kb.reports_dir / f"digest-{datetime.now(timezone.utc).strftime('%Y%m%d')}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (kb.reports_dir / "latest-digest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def spend_lines(kb: KB, days: int) -> List[str]:
    """Agent spend from the ledgers (safety.spend); the daemon's state names the job workspaces."""
    from safety import spend
    from safety.kb import load_json
    try:
        state = load_json(kb.state_file) or {}
        campaign = (state.get("daemon") or {}).get("campaign")
        return spend.format_report(spend.report(kb, campaign, state, days=days))
    except Exception as e:  # noqa: BLE001 - the digest must not fail on a broken ledger
        return [f"- unavailable: {type(e).__name__}: {e}"]


def _fmt_metrics(metrics: Any) -> str:
    if not isinstance(metrics, dict):
        return ""
    parts = []
    for name, value in metrics.items():
        if isinstance(value, float):
            parts.append(f"{name}={value:.3f}")
        else:
            parts.append(f"{name}={value}")
    return " ".join(parts[:6])
