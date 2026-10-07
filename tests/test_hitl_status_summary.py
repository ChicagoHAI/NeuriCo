"""/status shows the stage agent's plain-language note from logs/status_now.md."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agents.rule_maker import generate_rule_maker_prompt  # noqa: E402
from core.hitl_workspace_view import HitlWorkspaceView  # noqa: E402
from interactive.hitl_terminal_ui import HitlTerminalUI  # noqa: E402
from templates.prompt_generator import PromptGenerator  # noqa: E402

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
NOTE = (
    "Testing whether repo files help a coding assistant ask better questions. "
    "Rerunning the comparison to check the first result was not luck."
)


def _ui() -> HitlTerminalUI:
    return HitlTerminalUI(interactive=False, width=lambda: 200)


def test_every_stage_prompt_asks_for_the_status_note(tmp_path):
    generator = PromptGenerator()
    prompts = {
        "resource_finder": generator.generate_resource_finder_prompt(
            {"idea": {"title": "T", "hypothesis": "H"}}
        ),
        "rule_maker": generate_rule_maker_prompt(
            {"idea": {"title": "T"}}, tmp_path, TEMPLATES_DIR
        ),
        "experiment_runner": generator.generate_session_instructions(
            "Investigate.", str(tmp_path), domain="general"
        ),
        "paper_writer": generator.generate_paper_writer_prompt(tmp_path),
    }

    for stage, prompt in prompts.items():
        assert "logs/status_now.md" in prompt, stage


def test_live_status_includes_the_note_and_its_timestamp(tmp_path):
    note = tmp_path / "logs" / "status_now.md"
    note.parent.mkdir()
    note.write_text(f"{NOTE}\n", encoding="utf-8")

    status = HitlWorkspaceView(tmp_path).live_status()

    assert status["summary"] == NOTE
    assert status["summary_updated_at"].endswith("Z")


def test_live_status_omits_summary_without_a_note(tmp_path):
    assert "summary" not in HitlWorkspaceView(tmp_path).live_status()


def test_expanded_status_puts_the_note_above_the_run_line():
    lines = _ui().expanded_status(
        {"label": "Experiment · Executing", "summary": NOTE, "summary_age": "4:12"}
    )

    assert lines[2] == f"  {NOTE}"
    assert lines[3] == "  Updated 4:12 ago"
    assert lines[5] == "  Experiment · Executing"


def test_expanded_status_without_a_note_is_unchanged():
    assert _ui().expanded_status({"label": "Ready"})[2:] == ["  Ready"]
