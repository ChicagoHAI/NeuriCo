"""Child-process entrypoint for one manager-driven NeuriCo AutoResearch run."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

# NeuriCo's core modules use the historical top-level ``core`` namespace.
# The ACP child starts from Harbor's task workspace, so establish the same
# import roots as NeuriCo's own runner before importing any core module.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SRC_ROOT = _PROJECT_ROOT / "src"
sys.path.insert(0, str(_SRC_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT))

from core.hitl_run_control import HitlRunStopRequested  # noqa: E402
from core.idea_manager import IdeaManager  # noqa: E402
from core.runner import ResearchRunner  # noqa: E402

from .runtime import HarborAutoResearchTask, build_harbor_idea  # noqa: E402


TIME_LIMIT_EXIT_CODE = 124


def execute_autoresearch(
    *,
    instruction: str,
    workspace: Path,
    ideas_dir: Path,
    iterations: int = 1,
    time_limit_seconds: int | None = None,
) -> dict[str, Any]:
    """Submit a Harbor task through NeuriCo and run headless Auto HITL AutoResearch."""
    if iterations < 1:
        raise ValueError("AutoResearch iterations must be at least 1")
    if time_limit_seconds is not None and (
        type(time_limit_seconds) is not int or time_limit_seconds <= 0
    ):
        raise ValueError("AutoResearch time limit must be a positive integer")

    task = HarborAutoResearchTask(instruction=instruction, workspace=workspace)
    idea_manager = IdeaManager(ideas_dir)
    idea_id = idea_manager.submit_idea(build_harbor_idea(task), validate=True)

    # The idea metadata points at Harbor's existing repository, so the local
    # runner selects it as the authoritative AutoResearch workspace. A direct
    # runner invocation hosts the manager headlessly; "cli" selects the managed
    # entry surface without starting a browser, while Auto mode forbids human
    # escalation and lets the manager resolve every review boundary itself.
    # NeuriCo owns the persisted deadline, stop propagation, and selected-node
    # finalization. The adapter only translates its completed budget stop at the
    # child-process boundary.
    runner = ResearchRunner(use_github=False)
    try:
        return runner.run_research(
            idea_id=idea_id,
            provider="codex",
            full_permissions=True,
            multi_agent=True,
            use_scribe=False,
            write_paper=False,
            scoring_enabled=True,
            benchmark_mode=True,
            hitl_autoresearch="cli",
            hitl_manager_no_browser=True,
            hitl_mode="auto",
            autoresearch_iterations=iterations,
            time_limit_seconds=time_limit_seconds,
        )
    except HitlRunStopRequested as stop:
        if "budget_exhausted" not in str(stop):
            raise
        print(
            "NeuriCo reached its native run-time limit and completed AutoResearch "
            "budget finalization in the Harbor workspace.",
            flush=True,
        )
        return {
            "success": False,
            "stopped": True,
            "time_limit_reached": True,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Harbor task with NeuriCo AutoResearch")
    parser.add_argument("--instruction-file", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--ideas-dir", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--time-limit-seconds", type=int)
    args = parser.parse_args()

    instruction = args.instruction_file.read_text(encoding="utf-8")
    result = execute_autoresearch(
        instruction=instruction,
        workspace=args.workspace,
        ideas_dir=args.ideas_dir,
        iterations=args.iterations,
        time_limit_seconds=args.time_limit_seconds,
    )
    if result.get("time_limit_reached", False):
        raise SystemExit(TIME_LIMIT_EXIT_CODE)
    if not result.get("success", False):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
