"""Unit tests for the NEURICO_IDEAS ideas-directory override.

The override lets a shared read-only NeuriCo install point each user at their
own ideas directory. It mirrors NEURICO_WORKSPACE: honored when set, otherwise
the historical <project_root>/ideas path. The submit and run entry points must
resolve the same directory so a submitted idea is found at run time.

Run: python -m pytest tests/test_ideas_dir_override.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.idea_manager import resolve_ideas_dir  # noqa: E402


def test_falls_back_to_project_root_when_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("NEURICO_IDEAS", raising=False)
    assert resolve_ideas_dir(tmp_path) == tmp_path / "ideas"


def test_default_project_root_is_repo_root_when_unset(monkeypatch):
    monkeypatch.delenv("NEURICO_IDEAS", raising=False)
    repo_root = Path(__file__).resolve().parents[1]
    assert resolve_ideas_dir() == repo_root / "ideas"


def test_env_override_wins_and_ignores_project_root(monkeypatch, tmp_path):
    override = tmp_path / "shared_ideas"
    monkeypatch.setenv("NEURICO_IDEAS", str(override))
    assert resolve_ideas_dir(tmp_path / "some" / "other" / "root") == override
    assert resolve_ideas_dir() == override


def test_submit_and_run_resolve_the_same_dir(monkeypatch, tmp_path):
    """Submit passes no project_root, run passes its install root. Under the
    override both must land on the same ideas directory."""
    override = tmp_path / "user_ideas"
    monkeypatch.setenv("NEURICO_IDEAS", str(override))
    submit_side = resolve_ideas_dir()                      # cli/submit.py
    run_side = resolve_ideas_dir(tmp_path / "install")     # core/runner.py
    assert submit_side == run_side == override
