"""Validation tests for the direction-budget idea option."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.idea_manager import IdeaManager


def _idea(max_directions=None):
    idea = {
        "title": "A sufficiently descriptive research idea",
        "domain": "machine_learning",
        "hypothesis": "A concrete hypothesis that is long enough for validation.",
    }
    if max_directions is not None:
        idea["max_directions"] = max_directions
    return {"idea": idea}


def test_max_directions_is_optional_and_defaults_to_valid_workflow(tmp_path):
    result = IdeaManager(tmp_path).validate_idea(_idea())

    assert result["valid"] is True


def test_max_directions_accepts_values_in_supported_range(tmp_path):
    result = IdeaManager(tmp_path).validate_idea(_idea(5))

    assert result["valid"] is True


def test_max_directions_rejects_invalid_values(tmp_path):
    manager = IdeaManager(tmp_path)

    for value in (0, 11, "3", True):
        result = manager.validate_idea(_idea(value))
        assert result["valid"] is False
        assert any("max_directions" in error for error in result["errors"])
