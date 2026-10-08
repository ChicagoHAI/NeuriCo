"""
idea_explorer.py — Cost history across NeuriCo research runs.

Scans the workspaces directory and prints a table of per-run costs
extracted from .neurico/pipeline_results.json (written after each run).

Runs that pre-date token tracking show N/A for costs.

Usage:
    python3 idea_explorer.py
    python3 idea_explorer.py --workspaces /path/to/workspaces
    python3 idea_explorer.py --json
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path


WORKSPACE_PATTERN = re.compile(
    r"^(?P<idea>.+?)_(?P<date>\d{8})_(?P<time>\d{6})_(?P<hash>[0-9a-f]+)$"
)

STAGES = ("resource_finder", "experiment_runner", "paper_writer")


def _parse_workspace_name(name: str) -> dict:
    m = WORKSPACE_PATTERN.match(name)
    if not m:
        return {}
    dt = datetime.strptime(m.group("date") + m.group("time"), "%Y%m%d%H%M%S")
    return {
        "idea": m.group("idea").replace("_", " "),
        "datetime": dt,
        "hash": m.group("hash"),
    }


def _load_run(workspace: Path) -> dict:
    meta = _parse_workspace_name(workspace.name)
    if not meta:
        return {}

    run = {
        "workspace": workspace.name,
        "idea": meta["idea"],
        "datetime": meta["datetime"].strftime("%Y-%m-%d %H:%M"),
        "status": "unknown",
        "costs": {s: None for s in STAGES},
        "total": None,
    }

    # Status from pipeline_state.json (always present)
    state_file = workspace / ".neurico" / "pipeline_state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            if state.get("completed"):
                run["status"] = "completed"
            else:
                current = state.get("current_stage", "")
                run["status"] = f"partial ({current})" if current else "partial"
        except (json.JSONDecodeError, OSError):
            pass

    # Costs from pipeline_results.json (present only after token tracking commit)
    results_file = workspace / ".neurico" / "pipeline_results.json"
    if results_file.exists():
        try:
            results = json.loads(results_file.read_text(encoding="utf-8"))
            stages = results.get("stages", {})
            total = 0.0
            has_any = False
            for s in STAGES:
                cost = stages.get(s, {}).get("token_usage", {}).get("total_cost_usd")
                if cost is not None:
                    run["costs"][s] = cost
                    total += cost
                    has_any = True
            if has_any:
                run["total"] = total
        except (json.JSONDecodeError, OSError):
            pass

    return run


def _fmt_cost(val) -> str:
    return f"${val:.4f}" if val is not None else "N/A"


def _print_table(runs: list) -> None:
    if not runs:
        print("No workspaces found.")
        return

    col_idea = max(len(r["idea"]) for r in runs)
    col_idea = max(col_idea, 4)  # min width for "IDEA" header

    header = (
        f"{'IDEA':<{col_idea}}  {'DATE':<16}  {'STATUS':<20}"
        f"  {'RF':>8}  {'ER':>8}  {'PW':>8}  {'TOTAL':>8}"
    )
    sep = "-" * len(header)

    print()
    print(header)
    print(sep)
    for r in runs:
        print(
            f"{r['idea']:<{col_idea}}  {r['datetime']:<16}  {r['status']:<20}"
            f"  {_fmt_cost(r['costs']['resource_finder']):>8}"
            f"  {_fmt_cost(r['costs']['experiment_runner']):>8}"
            f"  {_fmt_cost(r['costs']['paper_writer']):>8}"
            f"  {_fmt_cost(r['total']):>8}"
        )
    print(sep)

    # Summary row for runs that have cost data
    costed = [r for r in runs if r["total"] is not None]
    if costed:
        grand_total = sum(r["total"] for r in costed)
        print(
            f"{'Total across ' + str(len(costed)) + ' run(s)':<{col_idea + 18 + 22}}"
            f"  {'':>8}  {'':>8}  {'':>8}  {_fmt_cost(grand_total):>8}"
        )
    print()
    if len(costed) < len(runs):
        print(f"  Note: {len(runs) - len(costed)} run(s) show N/A (pre-date token tracking)")
        print()


def main():
    parser = argparse.ArgumentParser(description="Show cost history across NeuriCo research runs")
    parser.add_argument(
        "--workspaces",
        type=Path,
        default=Path(__file__).parent / "workspaces",
        help="Path to workspaces directory (default: ./workspaces)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output raw JSON instead of a table",
    )
    args = parser.parse_args()

    if not args.workspaces.exists():
        print(f"Error: workspaces directory not found: {args.workspaces}", file=sys.stderr)
        sys.exit(1)

    runs = []
    for ws in sorted(args.workspaces.iterdir()):
        if not ws.is_dir() or ws.name.startswith("."):
            continue
        run = _load_run(ws)
        if run:
            runs.append(run)

    # Sort newest first
    runs.sort(key=lambda r: r["datetime"], reverse=True)

    if args.as_json:
        print(json.dumps(runs, indent=2, default=str))
    else:
        _print_table(runs)


if __name__ == "__main__":
    main()
