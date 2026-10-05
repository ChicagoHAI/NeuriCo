"""Regression tests for the dependency-only research workspace scaffold."""

from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = PROJECT_ROOT / "templates"
WORKSPACE_TEMPLATE_PATHS = sorted(
    [
        TEMPLATE_ROOT / "agents" / "resource_finder.txt",
        TEMPLATE_ROOT / "agents" / "session_instructions.txt",
    ]
    + list((TEMPLATE_ROOT / "domains").glob("*/resource_finder.txt"))
    + list((TEMPLATE_ROOT / "domains").glob("*/session_instructions.txt"))
)


@pytest.mark.parametrize(
    "template_path",
    WORKSPACE_TEMPLATE_PATHS,
    ids=lambda path: str(path.relative_to(TEMPLATE_ROOT)),
)
def test_research_workspace_is_dependency_only(template_path: Path):
    """The generated workspace must not make uv build a nonexistent package."""
    template = template_path.read_text(encoding="utf-8")

    assert 'name = "research-workspace"' in template
    assert "uv add " in template
    assert "[build-system]" not in template
    assert "hatchling" not in template.lower()
