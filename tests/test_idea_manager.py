"""Tests for core.idea_manager module."""

import pytest
import yaml
from unittest.mock import patch, MagicMock

from core.idea_manager import IdeaManager


@pytest.fixture
def manager(tmp_ideas_dir, tmp_config_dir):
    """Return an IdeaManager using temp directories with mocked ConfigLoader."""
    mock_loader = MagicMock()
    mock_loader.get_valid_domains.return_value = [
        "artificial_intelligence", "machine_learning", "data_science"
    ]
    mock_loader.should_allow_unknown_domains.return_value = True
    mock_loader.get_default_domain.return_value = "artificial_intelligence"

    with patch("core.idea_manager.ConfigLoader", return_value=mock_loader):
        mgr = IdeaManager(ideas_dir=tmp_ideas_dir)
    # Store mock so tests can reconfigure it
    mgr._mock_loader = mock_loader
    return mgr


class TestValidateIdea:
    # Verify a fully populated idea spec passes validation with no errors
    def test_valid_idea_passes(self, manager, sample_idea_spec):
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            result = manager.validate_idea(sample_idea_spec)
        assert result["valid"] is True
        assert result["errors"] == []

    # Verify spec without top-level 'idea' key is rejected immediately
    def test_missing_top_level_idea_key(self, manager):
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            result = manager.validate_idea({"title": "oops"})
        assert result["valid"] is False
        assert any("Missing top-level 'idea' key" in e for e in result["errors"])

    # Verify missing required field 'title' produces an error
    def test_missing_title(self, manager):
        spec = {"idea": {"domain": "machine_learning", "hypothesis": "A long enough hypothesis here"}}
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            result = manager.validate_idea(spec)
        assert result["valid"] is False
        assert any("title" in e for e in result["errors"])

    # Verify missing required field 'domain' produces an error
    def test_missing_domain(self, manager):
        spec = {"idea": {"title": "Test", "hypothesis": "A long enough hypothesis here"}}
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            result = manager.validate_idea(spec)
        assert result["valid"] is False
        assert any("domain" in e for e in result["errors"])

    # Verify missing required field 'hypothesis' produces an error
    def test_missing_hypothesis(self, manager):
        spec = {"idea": {"title": "Test", "domain": "machine_learning"}}
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            result = manager.validate_idea(spec)
        assert result["valid"] is False
        assert any("hypothesis" in e for e in result["errors"])

    # Verify hypothesis under 20 chars triggers a warning (not an error)
    def test_short_hypothesis_warning(self, manager):
        spec = {"idea": {"title": "Test", "domain": "machine_learning", "hypothesis": "Short"}}
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            result = manager.validate_idea(spec)
        assert result["valid"] is True
        assert any("short" in w.lower() for w in result["warnings"])

    # Verify unknown domain produces a warning when allow_unknown is True
    def test_unknown_domain_warns(self, manager):
        spec = {
            "idea": {
                "title": "Test",
                "domain": "underwater_basket_weaving",
                "hypothesis": "A long enough hypothesis for testing",
            }
        }
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            result = manager.validate_idea(spec)
        assert result["valid"] is True
        assert any("Unknown domain" in w for w in result["warnings"])

    # Verify unknown domain produces an error when allow_unknown is False
    def test_unknown_domain_errors_when_disallowed(self, manager):
        manager._mock_loader.should_allow_unknown_domains.return_value = False
        spec = {
            "idea": {
                "title": "Test",
                "domain": "unknown_field",
                "hypothesis": "A sufficiently long hypothesis for testing",
            }
        }
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            result = manager.validate_idea(spec)
        assert result["valid"] is False
        assert any("Invalid domain" in e for e in result["errors"])

    # Verify invalid compute constraint value is rejected
    def test_invalid_compute_constraint(self, manager, sample_idea_spec):
        sample_idea_spec["idea"]["constraints"] = {"compute": "quantum"}
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            result = manager.validate_idea(sample_idea_spec)
        assert result["valid"] is False
        assert any("compute" in e.lower() for e in result["errors"])

    # Verify expected_outputs that isn't a list produces an error
    def test_expected_outputs_not_a_list(self, manager, sample_idea_spec):
        sample_idea_spec["idea"]["expected_outputs"] = "not_a_list"
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            result = manager.validate_idea(sample_idea_spec)
        assert result["valid"] is False
        assert any("expected_outputs must be a list" in e for e in result["errors"])

    # Verify empty expected_outputs list triggers a warning (agent decides outputs)
    def test_expected_outputs_empty_warns(self, manager, sample_idea_spec):
        sample_idea_spec["idea"]["expected_outputs"] = []
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            result = manager.validate_idea(sample_idea_spec)
        assert result["valid"] is True
        assert any("empty" in w for w in result["warnings"])

    # Verify output entries missing 'type' and 'format' fields produce errors
    def test_expected_output_missing_type_and_format(self, manager, sample_idea_spec):
        sample_idea_spec["idea"]["expected_outputs"] = [{"description": "results"}]
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            result = manager.validate_idea(sample_idea_spec)
        assert result["valid"] is False
        assert any("missing 'type'" in e for e in result["errors"])
        assert any("missing 'format'" in e for e in result["errors"])

    # Verify omitting expected_outputs entirely triggers an informational warning
    def test_no_expected_outputs_warns(self, manager, minimal_idea_spec):
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            result = manager.validate_idea(minimal_idea_spec)
        assert any("No expected_outputs" in w for w in result["warnings"])

    # Verify non-integer time_limit produces an error
    def test_time_limit_not_integer(self, manager, sample_idea_spec):
        sample_idea_spec["idea"]["constraints"] = {"time_limit": "fast"}
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            result = manager.validate_idea(sample_idea_spec)
        assert any("time_limit must be an integer" in e for e in result["errors"])

    # Verify time_limit under 60s triggers a "very short" warning
    def test_time_limit_too_short_warns(self, manager, sample_idea_spec):
        sample_idea_spec["idea"]["constraints"] = {"time_limit": 30}
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            result = manager.validate_idea(sample_idea_spec)
        assert any("very short" in w for w in result["warnings"])

    # Verify time_limit over 24h triggers a "very long" warning
    def test_time_limit_too_long_warns(self, manager, sample_idea_spec):
        sample_idea_spec["idea"]["constraints"] = {"time_limit": 100000}
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            result = manager.validate_idea(sample_idea_spec)
        assert any("very long" in w for w in result["warnings"])

    # Verify evaluation_criteria that isn't a list produces an error
    def test_evaluation_criteria_not_a_list(self, manager, sample_idea_spec):
        sample_idea_spec["idea"]["evaluation_criteria"] = "just a string"
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            result = manager.validate_idea(sample_idea_spec)
        assert any("evaluation_criteria must be a list" in e for e in result["errors"])

    # Verify empty evaluation_criteria list triggers a warning
    def test_evaluation_criteria_empty_warns(self, manager, sample_idea_spec):
        sample_idea_spec["idea"]["evaluation_criteria"] = []
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            result = manager.validate_idea(sample_idea_spec)
        assert any("No evaluation criteria" in w for w in result["warnings"])


class TestSubmitIdea:
    # Verify submit writes a YAML file to submitted/ with correct metadata
    def test_creates_yaml_file(self, manager, sample_idea_spec):
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            idea_id = manager.submit_idea(sample_idea_spec)

        idea_file = manager.submitted_dir / f"{idea_id}.yaml"
        assert idea_file.exists()

        with open(idea_file) as f:
            saved = yaml.safe_load(f)
        assert saved["idea"]["title"] == "Test ML Experiment"
        assert saved["idea"]["metadata"]["status"] == "submitted"

    # Verify submitting an invalid idea raises ValueError
    def test_invalid_idea_raises(self, manager):
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            with pytest.raises(ValueError, match="validation failed"):
                manager.submit_idea({"idea": {}})


class TestGenerateIdeaId:
    # Verify generated ID contains a sanitized (lowercase, underscored) title
    def test_id_contains_sanitized_title(self, manager, sample_idea_spec):
        idea_id = manager._generate_idea_id(sample_idea_spec)
        assert "test_ml_experiment" in idea_id

    # Verify generated ID ends with an 8-char hex hash for uniqueness
    def test_id_contains_hash(self, manager, sample_idea_spec):
        idea_id = manager._generate_idea_id(sample_idea_spec)
        # ID format: {safe_title}_{timestamp}_{hash8}
        parts = idea_id.rsplit("_", 1)
        assert len(parts[-1]) == 8


class TestIdeaLifecycle:
    # Verify a submitted idea can be retrieved by its ID
    def test_submit_and_retrieve(self, manager, sample_idea_spec):
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            idea_id = manager.submit_idea(sample_idea_spec)
            retrieved = manager.get_idea(idea_id)
        assert retrieved is not None
        assert retrieved["idea"]["title"] == "Test ML Experiment"

    # Verify status update moves the YAML file between directories
    def test_update_status_moves_file(self, manager, sample_idea_spec):
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            idea_id = manager.submit_idea(sample_idea_spec)
            assert (manager.submitted_dir / f"{idea_id}.yaml").exists()

            manager.update_status(idea_id, "in_progress")
            assert not (manager.submitted_dir / f"{idea_id}.yaml").exists()
            assert (manager.in_progress_dir / f"{idea_id}.yaml").exists()

    # Verify invalid status string raises ValueError
    def test_update_status_invalid_raises(self, manager):
        with pytest.raises(ValueError, match="Invalid status"):
            manager.update_status("fake_id", "invalid_status")

    # Verify get_idea returns None for an ID that doesn't exist
    def test_get_idea_returns_none_for_missing(self, manager):
        assert manager.get_idea("nonexistent_id_12345") is None

    # Verify update_status returns False when the idea ID is not found
    def test_update_status_returns_false_for_missing(self, manager):
        assert manager.update_status("nonexistent_id_12345", "in_progress") is False

    # Verify list_ideas filters by status and returns correct summaries
    def test_list_ideas_returns_submitted(self, manager, sample_idea_spec):
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            manager.submit_idea(sample_idea_spec)
            ideas = manager.list_ideas(status="submitted")
        assert len(ideas) == 1
        assert ideas[0]["title"] == "Test ML Experiment"

    # Verify list_ideas with status=None returns ideas across all directories
    def test_list_ideas_all_statuses(self, manager, sample_idea_spec):
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            idea_id = manager.submit_idea(sample_idea_spec)
            manager.update_status(idea_id, "in_progress")
            ideas = manager.list_ideas(status=None)
        assert len(ideas) == 1
        assert ideas[0]["status"] == "in_progress"

    # Verify list_ideas filters correctly for in_progress and completed
    def test_list_ideas_by_in_progress_and_completed(self, manager, sample_idea_spec):
        with patch("core.idea_manager.ConfigLoader", return_value=manager._mock_loader):
            idea_id = manager.submit_idea(sample_idea_spec)
            manager.update_status(idea_id, "in_progress")

            assert len(manager.list_ideas(status="in_progress")) == 1
            assert len(manager.list_ideas(status="completed")) == 0

            manager.update_status(idea_id, "completed")
            assert len(manager.list_ideas(status="in_progress")) == 0
            assert len(manager.list_ideas(status="completed")) == 1

    # Verify update_status creates metadata dict if idea was saved without one
    def test_update_status_creates_metadata(self, manager, tmp_ideas_dir):
        # Manually write an idea file without metadata
        idea_file = manager.submitted_dir / "no_meta.yaml"
        idea_file.write_text(yaml.dump({"idea": {"title": "No Metadata Idea"}}))

        result = manager.update_status("no_meta", "in_progress")
        assert result is True

        moved_file = manager.in_progress_dir / "no_meta.yaml"
        with open(moved_file) as f:
            saved = yaml.safe_load(f)
        assert saved["idea"]["metadata"]["status"] == "in_progress"

    # Verify list_ideas rejects invalid status strings
    def test_list_ideas_invalid_status_raises(self, manager):
        with pytest.raises(ValueError, match="Invalid status"):
            manager.list_ideas(status="archived")
