"""Tests for agent-side working directory checks at phase boundaries."""

import os
import re
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from core.directory_check import (
    EXIT_NESTED,
    EXIT_OK,
    EXIT_OUTSIDE,
    checks_path,
    classify_directory,
    record_check,
    refresh_state_document,
    summarize_directory_checks,
)
from core.pipeline_orchestrator import PipelineState


def test_classify_directory_separates_root_nested_and_outside(tmp_path):
    workspace = tmp_path / "workspace"
    nested = workspace / "code" / "baseline-repo"
    nested.mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    assert classify_directory(workspace, workspace)["status"] == "workspace_root"

    nested_result = classify_directory(workspace, nested)
    assert nested_result["status"] == "nested"
    assert nested_result["relative"] == str(Path("code") / "baseline-repo")

    outside_result = classify_directory(workspace, outside)
    assert outside_result["status"] == "outside"
    assert outside_result["relative"] is None


def test_record_check_skips_consecutive_duplicates(tmp_path):
    result = classify_directory(tmp_path, tmp_path)

    assert record_check(tmp_path, "3", result) is True
    assert record_check(tmp_path, "3", result) is False
    assert record_check(tmp_path, "4", result) is True

    nested = tmp_path / "results"
    nested.mkdir()
    assert record_check(tmp_path, "4", classify_directory(tmp_path, nested)) is True

    summary = summarize_directory_checks(tmp_path)
    assert summary["total"] == 3
    assert summary["nested"] == 1
    assert summary["last_status"] == "nested"
    assert summary["last_phase"] == "4"


def test_summarize_returns_none_before_any_check(tmp_path):
    assert summarize_directory_checks(tmp_path) is None


def test_refresh_updates_state_document_during_the_stage(tmp_path):
    pipeline = PipelineState(tmp_path)
    pipeline.start_stage("experiment_runner")
    nested = tmp_path / "code"
    nested.mkdir()
    record_check(tmp_path, "3", classify_directory(tmp_path, nested))

    assert refresh_state_document(tmp_path) is True
    state_text = (tmp_path / "STATE.md").read_text()
    assert "1 nested, 0 outside" in state_text
    assert "last `nested` after phase 3" in state_text

    # The orchestrator stays the only writer of pipeline state.
    assert "directory_checks" not in (
        tmp_path / ".neurico" / "pipeline_state.json"
    ).read_text()


def test_refresh_fails_soft_without_pipeline_state(tmp_path):
    assert refresh_state_document(tmp_path) is False


def _run_cli(workspace: Path, cwd: Path) -> subprocess.CompletedProcess:
    """Run the CLI from `cwd`, which is the agent shell location under test."""
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    return subprocess.run(
        [sys.executable, "-m", "core.directory_check",
         "--workspace", str(workspace), "--phase", "3"],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )


def test_cli_reports_each_location_with_a_distinct_exit_code(tmp_path):
    workspace = tmp_path / "workspace"
    nested = workspace / "code"
    nested.mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    at_root = _run_cli(workspace, workspace)
    assert at_root.returncode == EXIT_OK
    assert "OK:" in at_root.stdout

    in_nested = _run_cli(workspace, nested)
    assert in_nested.returncode == EXIT_NESTED
    assert f"cd {workspace.resolve()}" in in_nested.stdout

    elsewhere = _run_cli(workspace, outside)
    assert elsewhere.returncode == EXIT_OUTSIDE
    assert f"cd {workspace.resolve()}" in elsewhere.stdout
    assert "outside the workspace" in elsewhere.stdout

    assert checks_path(workspace).exists()
    assert summarize_directory_checks(workspace)["outside"] == 1


def _boundary_block(work_dir: str, domain: str) -> str:
    """Return the rendered boundary-check block as one whitespace-normalized line.

    Collapsing newlines lets the assertions below match required behaviour
    without depending on where the block happens to wrap.
    """
    from templates.prompt_generator import PromptGenerator

    prompt = PromptGenerator().generate_session_instructions(
        "Investigate the research question.",
        work_dir,
        domain=domain,
        idea_spec={"max_directions": 2},
    )
    assert "PHASE BOUNDARY DIRECTORY CHECK" in prompt
    block = prompt.split("PHASE BOUNDARY DIRECTORY CHECK", 1)[1]
    return re.sub(r"\s+", " ", block)


def test_rendered_prompt_requires_a_check_at_every_phase_boundary(tmp_path):
    block = _boundary_block(str(tmp_path), "general")

    assert re.search(r"end of (every|each) phase", block, re.IGNORECASE)
    assert f"neurico-check-dir --phase <number> --workspace {tmp_path}" in block


def test_rendered_prompt_requires_recovery_recheck_and_exit_zero(tmp_path):
    block = _boundary_block(str(tmp_path), "general")

    # Both failing classifications must route to the same recovery.
    assert "exit 3" in block and "exit 4" in block
    assert re.search(rf"exit 3 or 4.{{0,80}}cd {re.escape(str(tmp_path))}", block)

    # Recovery is cd back, then run the checker again, repeating until it passes.
    assert re.search(r"neurico-check-dir again", block)
    assert re.search(r"[Rr]epeat until.{0,40}exit 0", block)

    # The next phase does not start on a failed check.
    assert re.search(
        r"[Dd]o not (begin|start|continue).{0,80}exit 0", block
    )


def test_rendered_prompt_allows_subdirectory_work_within_a_phase(tmp_path):
    block = _boundary_block(str(tmp_path), "general")

    assert re.search(r"subdirectory during a phase is fine", block, re.IGNORECASE)


def test_domain_overrides_receive_the_boundary_requirements(tmp_path):
    block = _boundary_block(str(tmp_path), "finance")

    assert re.search(r"end of (every|each) phase", block, re.IGNORECASE)
    assert f"cd {tmp_path}" in block
    assert "exit 0" in block
