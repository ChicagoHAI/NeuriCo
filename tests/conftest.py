"""Shared fixtures for NeuriCo tests."""

import sys
from pathlib import Path

import pytest
import yaml

# Add src/ to path so core modules are importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Create a temp directory with a valid domains.yaml config."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Minimal domains config matching the structure of config/domains.yaml
    domains_config = {
        "default_domain": "artificial_intelligence",
        "domains": {
            "artificial_intelligence": {
                "name": "Artificial Intelligence",
                "description": "AI research",
                "has_template": True,
            },
            "machine_learning": {
                "name": "Machine Learning",
                "description": "ML research",
                "has_template": True,
            },
            "data_science": {
                "name": "Data Science",
                "description": "Data analysis",
                "has_template": False,
            },
        },
        "validation": {"allow_unknown": True, "warn_missing_template": True},
    }

    with open(config_dir / "domains.yaml", "w") as f:
        yaml.dump(domains_config, f)

    return config_dir


@pytest.fixture
def tmp_ideas_dir(tmp_path):
    """Create a temp directory structure for idea storage."""
    ideas_dir = tmp_path / "ideas"
    ideas_dir.mkdir()
    return ideas_dir


@pytest.fixture
def sample_idea_spec():
    """Return a valid idea specification dict with all optional fields populated."""
    return {
        "idea": {
            "title": "Test ML Experiment",
            "domain": "machine_learning",
            "hypothesis": "Fine-tuning with curriculum learning improves convergence speed",
            "expected_outputs": [
                {"type": "metrics", "format": "json", "fields": ["accuracy", "loss"]}
            ],
            "evaluation_criteria": ["Convergence speed improvement > 10%"],
        }
    }


@pytest.fixture
def minimal_idea_spec():
    """Return a minimal valid idea specification (only required fields)."""
    return {
        "idea": {
            "title": "Minimal Test Idea",
            "domain": "artificial_intelligence",
            "hypothesis": "This is a sufficiently long hypothesis for testing purposes",
        }
    }
