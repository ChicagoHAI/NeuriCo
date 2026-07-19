import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl import HitlRuntime
from core.hitl_workspace_guard import HitlWorkspaceWriteGuard


def test_plan_guard_allows_only_the_living_plan(tmp_path: Path) -> None:
    plan = tmp_path / "plans" / "resource_finder_plan.md"
    plan.parent.mkdir()
    plan.write_text("original plan\n", encoding="utf-8")
    source = tmp_path / "src" / "module.py"
    source.parent.mkdir()
    source.write_text("original\n", encoding="utf-8")

    guard = HitlWorkspaceWriteGuard.capture_public(tmp_path)
    plan.write_text("revised plan\n", encoding="utf-8")
    assert guard.allow_only(["plans/resource_finder_plan.md"])["valid"] is True

    source.write_text("changed\n", encoding="utf-8")
    validation = guard.allow_only(["plans/resource_finder_plan.md"])
    assert validation["valid"] is False
    assert "src/module.py" in validation["issues"][0]


def test_proposal_context_always_installs_runtime_owned_write_gate(tmp_path: Path) -> None:
    public_file = tmp_path / "notes.md"
    public_file.write_text("unchanged\n", encoding="utf-8")
    runtime = HitlRuntime(tmp_path, "experiment_runner")
    runtime.prepare_idea_tool_context(hitl_stage="proposal", actor="experiment_runner")

    public_file.write_text("changed\n", encoding="utf-8")
    validation = runtime._tool_context["proposal_submission_validator"]()

    assert validation["valid"] is False
    assert "notes.md" in validation["issues"][0]
    runtime.clear_idea_tool_context()
    runtime.manager.stop()
