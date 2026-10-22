"""Regression tests for the dependency-only research workspace scaffold."""

from pathlib import Path
import re
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from templates.prompt_generator import PromptGenerator  # noqa: E402
from agents.rule_maker import generate_rule_maker_prompt  # noqa: E402
from agents.rule_maker_bootstrap import (  # noqa: E402
    generate_managed_baseline_rule_maker_prompt,
)
from core.research_environment import (  # noqa: E402
    WorkspaceMode,
    configure_workspace_mode,
    render_research_environment_placeholders,
)


TEMPLATE_ROOT = PROJECT_ROOT / "templates"
WORKSPACE_TEMPLATE_PATHS = sorted(
    [
        TEMPLATE_ROOT / "agents" / "resource_finder.txt",
        TEMPLATE_ROOT / "agents" / "session_instructions.txt",
    ]
    + list((TEMPLATE_ROOT / "domains").glob("*/resource_finder.txt"))
    + list((TEMPLATE_ROOT / "domains").glob("*/session_instructions.txt"))
)
DOMAINS = sorted(
    {path.parent.name for path in WORKSPACE_TEMPLATE_PATHS if path.parent.name != "agents"}
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
    assert "uv add --project {{ research_env_dir }}" in template
    assert "uv venv {{ research_venv_dir }}" in template
    assert "cat > {{ research_project_path }}" in template
    assert "source .venv" not in template
    assert "cat > pyproject.toml" not in template
    assert "uv venv\n" not in template
    assert not re.search(r"^\s*uv pip install(?! --python)\b", template, re.MULTILINE)
    assert not re.search(r"^\s*(?:pip install|pip freeze)\b", template, re.MULTILINE)
    assert "-m pip" not in template
    assert "[build-system]" not in template
    assert "hatchling" not in template.lower()


@pytest.mark.parametrize(
    "skill_path",
    [
        TEMPLATE_ROOT / "skills" / "literature-review" / "SKILL.md",
        TEMPLATE_ROOT / "skills" / "paper-finder" / "SKILL.md",
    ],
    ids=lambda path: str(path.relative_to(TEMPLATE_ROOT)),
)
def test_bundled_research_skills_do_not_recommend_direct_pip(skill_path: Path):
    skill = skill_path.read_text(encoding="utf-8")

    assert "pip install" not in skill
    assert "uv add --project {{ research_env_dir }}" in skill


@pytest.mark.parametrize(
    ("workspace_mode", "project", "venv"),
    [
        (WorkspaceMode.NATIVE, ".", ".venv"),
        (
            WorkspaceMode.EMBEDDED,
            "neurico-research-env",
            "neurico-research-env/.venv",
        ),
    ],
)
@pytest.mark.parametrize("domain", ["general", *DOMAINS])
def test_generated_prompts_use_the_selected_research_environment(
    domain: str,
    workspace_mode: WorkspaceMode,
    project: str,
    venv: str,
):
    generator = PromptGenerator(workspace_mode=workspace_mode)
    idea = {"idea": {"domain": domain}}

    resource_prompt = generator.generate_resource_finder_prompt(idea)
    session_prompt = generator.generate_session_instructions(
        "research prompt",
        "/tmp/research-workspace",
        domain=domain,
        idea_spec=idea["idea"],
    )

    prompts = (resource_prompt, session_prompt)
    for prompt in prompts:
        assert venv in prompt
        assert f"uv add --project {project}" in prompt
        assert "{{ research_" not in prompt
    assert f"{venv}/bin/python" in "\n".join(prompts)


@pytest.mark.parametrize(
    ("workspace_mode", "expected"),
    [
        (WorkspaceMode.NATIVE, "uv add --project . pypdf"),
        (
            WorkspaceMode.EMBEDDED,
            "uv add --project neurico-research-env pypdf",
        ),
    ],
)
def test_copied_skill_placeholders_follow_workspace_mode(
    workspace_mode: WorkspaceMode,
    expected: str,
):
    source = "uv add --project {{ research_env_dir }} pypdf"
    assert render_research_environment_placeholders(source, workspace_mode) == expected


@pytest.mark.parametrize(
    ("workspace_mode", "python_path"),
    [
        (WorkspaceMode.NATIVE, ".venv/bin/python"),
        (
            WorkspaceMode.EMBEDDED,
            "neurico-research-env/.venv/bin/python",
        ),
    ],
)
def test_rule_maker_preflight_uses_selected_research_interpreter(
    tmp_path: Path,
    workspace_mode: WorkspaceMode,
    python_path: str,
):
    configure_workspace_mode(tmp_path, workspace_mode)

    prompt = generate_rule_maker_prompt(
        idea={"idea": {"domain": "machine_learning"}},
        work_dir=tmp_path,
        templates_dir=TEMPLATE_ROOT,
        hitl_phase="execution",
    )

    assert f"{python_path} -c" in prompt
    assert f"{python_path} scoring/eval.py" in prompt
    expected_project = (
        "." if workspace_mode is WorkspaceMode.NATIVE else "neurico-research-env"
    )
    assert f"uv add --project {expected_project}" in prompt
    assert "{research_python_path}" not in prompt

    baseline_prompt = generate_managed_baseline_rule_maker_prompt(
        candidate_manifest={},
        work_dir=tmp_path,
        templates_dir=TEMPLATE_ROOT,
        hitl_phase="execution",
    )
    assert f"{python_path} scoring/eval.py" in baseline_prompt
    assert f"with `{python_path}`" in baseline_prompt
    assert "{research_python_path}" not in baseline_prompt
