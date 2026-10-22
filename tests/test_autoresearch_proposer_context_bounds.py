"""Regression coverage for bounded AutoResearch proposer context."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import agents.autoresearch_proposer as proposer  # noqa: E402


def test_results_summary_does_not_trust_virtualenv_marker(tmp_path):
    results = tmp_path / "results"
    ordinary = results / "experiment_runner" / "metrics.json"
    ordinary.parent.mkdir(parents=True)
    ordinary.write_text('{"score": 1}\n')
    environment = results / "experiment_runner" / "state_embedding" / "state_env"
    package = environment / "lib" / "python" / "site-packages" / "package.py"
    package.parent.mkdir(parents=True)
    (environment / "pyvenv.cfg").write_text("home = /python\n")
    package.write_text("VALUE = 1\n")

    summary = proposer._summarize_directory(results)
    paths = [str(entry.get("path", "")) for entry in summary]

    assert "experiment_runner/metrics.json" in paths
    assert not any("site-packages" in path for path in paths)
    assert "experiment_runner/state_embedding/state_env/" in paths


def test_results_summary_is_bounded_and_reports_truncation(tmp_path, monkeypatch):
    results = tmp_path / "results"
    results.mkdir()
    for index in range(8):
        (results / f"result_{index}.json").write_text("{}\n")
    monkeypatch.setattr(proposer, "MAX_RESULTS_SUMMARY_ENTRIES", 3)

    summary = proposer._summarize_directory(results)

    assert len(summary) == 4
    assert summary[-1]["type"] == "truncated"


def test_src_tree_is_bounded_and_prunes_dependencies(tmp_path, monkeypatch):
    source = tmp_path / "src"
    source.mkdir()
    for index in range(8):
        (source / f"module_{index}.py").write_text("pass\n")
    dependency = source / "node_modules" / "package" / "index.js"
    dependency.parent.mkdir(parents=True)
    dependency.write_text("module.exports = {}\n")
    monkeypatch.setattr(proposer, "MAX_SRC_TREE_ENTRIES", 3)

    tree = proposer._list_tree(source)

    assert len(tree) == 4
    assert tree[-1].startswith("src/[additional entries omitted")
    assert not any("node_modules" in entry for entry in tree)


def test_src_tree_keeps_project_directories_named_env(tmp_path):
    source = tmp_path / "src"
    module = source / "env" / "configuration.py"
    module.parent.mkdir(parents=True)
    module.write_text("SETTING = True\n")

    tree = proposer._list_tree(source)

    assert "src/env/" in tree
    assert "src/env/configuration.py" in tree


def test_generated_prompt_rejects_unbounded_authoritative_context(tmp_path, monkeypatch):
    work_dir = tmp_path / "workspace"
    attempt_dir = work_dir / "logs" / "attempt"
    scoring = work_dir / "scoring"
    scoring.mkdir(parents=True)
    (scoring / "interface.md").write_text("x" * 2_000)
    monkeypatch.setattr(proposer, "MAX_AUTORESEARCH_PROPOSER_PROMPT_CHARS", 1_000)

    with pytest.raises(
        proposer.AutoResearchProposerPromptTooLargeError,
        match="scoring_interface_md",
    ):
        proposer.generate_autoresearch_proposal_prompt(
            idea={"idea": {"title": "Bounded prompt", "domain": "testing"}},
            work_dir=work_dir,
            parent_sha="a" * 40,
            attempt_dir=attempt_dir,
            templates_dir=Path(__file__).resolve().parents[1] / "templates",
        )
