"""Exercise the direct runner CLI without starting research or model calls."""

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core import runner as runner_module  # noqa: E402


@pytest.fixture
def research_cli(monkeypatch, tmp_path):
    research = Mock(spec=runner_module.ResearchRunner)
    research.run_research.return_value = {"success": True, "work_dir": str(tmp_path)}
    constructor = Mock(return_value=research)
    monkeypatch.setattr(runner_module, "ResearchRunner", constructor)
    # Do not load user credentials/configuration during parser tests.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)

    def invoke(*arguments):
        monkeypatch.setattr(sys, "argv", ["runner.py", "smoke", "--no-github", *arguments])
        runner_module.main()

    return invoke, constructor, research


@pytest.mark.parametrize("workflow", ["hitl_research", "hitl_autoresearch"])
@pytest.mark.parametrize("interface", ["web", "cli"])
@pytest.mark.parametrize("focused", [False, True])
def test_managed_cli_forwards_workflow_and_focus(research_cli, workflow, interface, focused):
    invoke, constructor, research = research_cli
    arguments = ["--" + workflow.replace("_", "-"), interface]
    if focused:
        arguments.append("--focused-autoresearch")

    invoke(*arguments)

    constructor.assert_called_once()
    assert constructor.call_args.kwargs["use_github"] is False
    research.run_research.assert_called_once()
    options = research.run_research.call_args.kwargs
    assert options["idea_id"] == "smoke"
    assert options["hitl_research"] == (interface if workflow == "hitl_research" else None)
    assert options["hitl_autoresearch"] == (interface if workflow == "hitl_autoresearch" else None)
    assert options["focused_autoresearch"] is (True if focused else None)


def test_unmanaged_cli_preserves_omitted_mode_defaults(research_cli):
    invoke, _, research = research_cli
    invoke()
    options = research.run_research.call_args.kwargs
    assert options["hitl_research"] is None
    assert options["hitl_autoresearch"] is None
    assert options["focused_autoresearch"] is None


@pytest.mark.parametrize(
    "arguments", [[], ["--autoresearch"], ["--hitl-continue-autoresearch", "cli"]]
)
def test_focus_without_supported_managed_workflow_is_parser_error(research_cli, capsys, arguments):
    invoke, constructor, research = research_cli
    with pytest.raises(SystemExit) as exc:
        invoke(*arguments, "--focused-autoresearch")
    assert exc.value.code == 2
    assert (
        "--focused-autoresearch requires --hitl-research or --hitl-autoresearch"
        in capsys.readouterr().err
    )
    constructor.assert_not_called()
    research.run_research.assert_not_called()
