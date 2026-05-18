"""
Show NeuriCo token and cost usage history.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.usage_tracker import load_usage_history


def main() -> None:
    parser = argparse.ArgumentParser(description="Show NeuriCo cost history")
    parser.add_argument("--idea-id", help="Filter usage history to a single idea ID")
    parser.add_argument("--json", action="store_true", help="Print raw JSON records")
    parser.add_argument("--limit", type=_non_negative_int, default=20, help="Maximum records to show")
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent.parent
    records = load_usage_history(project_root)

    if args.idea_id:
        records = [record for record in records if record.get("idea_id") == args.idea_id]

    records = _dedupe_latest(records)
    records = records[-args.limit :] if args.limit else []

    if args.json:
        print(json.dumps(records, indent=2))
        return

    if not records:
        print("No usage history recorded yet.")
        return

    print("NeuriCo usage history")
    for index, record in enumerate(records):
        if index:
            print()
        print(_format_record(record))


def _dedupe_latest(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only the latest record per workspace, preserving final order."""
    latest_by_workspace: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for record in records:
        key = record.get("workspace") or record.get("idea_id") or str(len(order))
        if key not in latest_by_workspace:
            order.append(key)
        latest_by_workspace[key] = record
    return [latest_by_workspace[key] for key in order]


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be greater than or equal to 0")
    return parsed


def _format_record(record: Dict[str, Any]) -> str:
    lines = [
        f"Idea: {record.get('idea_id') or 'unknown'}",
    ]
    if record.get("title"):
        lines.append(f"  title: {record['title']}")
    if record.get("workspace"):
        lines.append(f"  workspace: {record['workspace']}")
    lines.extend(
        [
            f"  budget: {_fmt_money(record.get('budget_usd'))}",
            f"  status: {record.get('budget_status') or 'unknown'}",
            f"  total_tokens: {_fmt_int(record.get('total_tokens'))}",
            f"  total_cost: {_fmt_money(record.get('total_cost_usd'))}",
        ]
    )

    providers = record.get("providers")
    if isinstance(providers, dict) and providers:
        lines.append("  providers:")
        for provider_name in sorted(providers):
            provider = providers[provider_name]
            if not isinstance(provider, dict):
                continue
            lines.append(
                "    "
                f"- {provider_name}: "
                f"attempts={provider.get('attempt_count', 'unknown')}, "
                f"tokens={_fmt_int(provider.get('total_tokens'))}, "
                f"cost={_fmt_money(provider.get('total_cost_usd'))}"
            )

    stages = record.get("stages")
    if isinstance(stages, dict) and stages:
        lines.append("  stages:")
        for stage_name in _ordered_stage_names(stages):
            stage = stages[stage_name]
            if not isinstance(stage, dict):
                continue
            lines.append(
                "    "
                f"- {stage_name}: "
                f"attempts={stage.get('attempt_count', _attempt_count_for_stage(stage))}, "
                f"tokens={_fmt_int(stage.get('total_tokens'))}, "
                f"cost={_fmt_money(stage.get('total_cost_usd'))}"
            )
            attempts = stage.get("attempts")
            if isinstance(attempts, list) and attempts:
                for index, attempt in enumerate(attempts, start=1):
                    if not isinstance(attempt, dict):
                        continue
                    lines.append(
                        "        "
                        f"attempt {index}: "
                        f"provider={attempt.get('provider') or 'unknown'}, "
                        f"model={attempt.get('model') or 'unknown'}, "
                        f"tokens={_fmt_int(attempt.get('total_tokens'))}, "
                        f"cost={_fmt_money(attempt.get('estimated_cost_usd'))}"
                    )
    return "\n".join(lines)


def _attempt_count_for_stage(stage: Dict[str, Any]) -> Any:
    attempts = stage.get("attempts")
    if isinstance(attempts, list):
        return len(attempts)
    return "unknown"


def _ordered_stage_names(stages: Dict[str, Any]) -> List[str]:
    preferred_order = ["resource_finder", "experiment_runner", "paper_writer"]
    known = [stage for stage in preferred_order if stage in stages]
    extra = sorted(str(stage) for stage in stages if stage not in preferred_order)
    return known + extra


def _fmt_int(value: Any) -> str:
    if value is None:
        return "unknown"
    return f"{int(value):,}"


def _fmt_money(value: Any) -> str:
    if value is None:
        return "unknown"
    return f"${float(value):.4f}"


if __name__ == "__main__":
    main()
