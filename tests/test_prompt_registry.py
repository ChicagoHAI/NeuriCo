"""The prompt registry (core.prompt_registry), docs/AGENT_FACTORY_ASSESSMENT.md step 6.

The goldens under tests/fixtures/prompts/golden/ were rendered by the code
before the registry existed (planner/scout ``str.replace`` over the ``{{key}}``
templates, PromptGenerator for the research roles). Every render path must
still produce them byte for byte. Regenerate deliberately with
``NEURICO_UPDATE_GOLDENS=1`` after a template change and review the diff.
"""

from __future__ import annotations

import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.prompt_registry import PromptRegistry, RenderedPrompt, canonical_variables  # noqa: E402
from core.run_ledger import RunLedger  # noqa: E402
from safety import model_scout, planner  # noqa: E402
from safety.kb import KB, save_yaml  # noqa: E402
from templates.prompt_generator import PromptGenerator  # noqa: E402

TEMPLATES = PROJECT_ROOT / "templates"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "prompts"
GOLDEN = FIXTURES / "golden"
IDEA = yaml.safe_load((FIXTURES / "idea.yaml").read_text(encoding="utf-8"))
FROZEN = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
KB_ROOT_TOKEN = "<KB_ROOT>"
WORK_DIR = Path("/work/idea")


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FROZEN if tz is None else FROZEN.astimezone(tz)


def build_fixture_kb(root: Path) -> KB:
    seed = yaml.safe_load((FIXTURES / "kb_seed.yaml").read_text(encoding="utf-8"))
    kb = KB(root)
    kb.ensure_layout()
    for name, data in seed["catalog"].items():
        save_yaml(kb.catalog_dir / f"{name}.yaml", data)
    save_yaml(kb.campaigns_dir / f"{seed['campaign']['name']}.yaml", seed["campaign"])
    for finding in seed.get("findings", []):
        save_yaml(kb.findings_dir / f"{finding['id']}.yaml", finding)
    for name, text in (seed.get("inbox") or {}).items():
        (kb.inbox_dir / name).write_text(text, encoding="utf-8")
    for state, jobs in (seed.get("queue") or {}).items():
        for job in jobs:
            save_yaml(kb.queue_state_dir(state) / f"{job['id']}.yaml", job)
    return kb


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = tmp_path / "kb"
    monkeypatch.setenv("NEURICO_SAFETY_KB", str(root))
    monkeypatch.setattr(KB, "logs_dir", property(lambda self: self.root / "logs"))
    monkeypatch.setattr(planner, "datetime", _FrozenDatetime)
    monkeypatch.setattr(model_scout, "datetime", _FrozenDatetime)
    return build_fixture_kb(root)


def _normalise(text: str, kb: KB) -> str:
    return text.replace(str(kb.root), KB_ROOT_TOKEN)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _legacy_render(template_id: str, variables: dict) -> str:
    """What safety.planner / safety.model_scout did before the registry."""
    text = (TEMPLATES / template_id).read_text(encoding="utf-8")
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def assert_golden(name: str, text: str) -> None:
    path = GOLDEN / f"{name}.txt"
    if os.environ.get("NEURICO_UPDATE_GOLDENS"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return
    assert path.exists(), f"missing golden {path}; run with NEURICO_UPDATE_GOLDENS=1"
    assert text == path.read_text(encoding="utf-8"), f"{name} prompt differs from its golden"


def assert_provenance(rendered: RenderedPrompt, template_id: str, variables: dict) -> None:
    assert rendered.template_id == template_id
    assert rendered.template_sha == _sha((TEMPLATES / template_id).read_text(encoding="utf-8"))
    assert rendered.variables_sha == _sha(canonical_variables(variables))
    assert rendered.missing == ()


# -- planner, ideator, scout: goldens plus provenance ----------------------------------------------------------
@pytest.mark.parametrize("mode", ["replicate", "ideate"])
def test_planner_prompt_matches_golden(kb, mode):
    rendered = planner.render(kb, "camp", f"plan-20261020-120000-{mode}", mode)
    assert "{{" not in rendered.text
    assert_golden(f"planner_{mode}", _normalise(rendered.text, kb))
    assert planner.render_prompt(kb, "camp", f"plan-20261020-120000-{mode}", mode) == rendered.text
    variables = {**planner.build_context(kb, "camp"), "latest_models": model_scout.latest_models_summary(kb),
                 "planner_run": f"plan-20261020-120000-{mode}", "kb_root": str(kb.root), "campaign_name": "camp",
                 "date": "2026-10-20", "max_new_jobs": "2"}
    assert_provenance(rendered, planner.TEMPLATE_IDS[mode], variables)
    assert rendered.text == _legacy_render(planner.TEMPLATE_IDS[mode], variables)


def test_scout_prompt_matches_golden(kb):
    rendered = model_scout.render(kb, "scout-20261020-120000")
    assert "{{" not in rendered.text
    assert_golden("model_scout", _normalise(rendered.text, kb))
    assert model_scout.render_prompt(kb, "scout-20261020-120000") == rendered.text
    assert rendered.template_id == model_scout.TEMPLATE_ID and rendered.missing == ()
    assert rendered.template_sha == _sha(model_scout.TEMPLATE.read_text(encoding="utf-8"))


# -- Jinja2 keeps str.replace's behaviour ------------------------------------------------------------------
def test_missing_key_stays_literal_and_is_reported(kb):
    """A key without a value renders as ``{{key}}``, exactly as str.replace left it, and is listed."""
    registry = PromptRegistry(TEMPLATES)
    variables = {**planner.build_context(kb, "camp"), "planner_run": "p", "kb_root": "/kb", "campaign_name": "camp",
                 "date": "2026-10-20", "max_new_jobs": "2"}    # no latest_models
    rendered = registry.render("agents/safety_planner.txt", variables)
    assert rendered.text == _legacy_render("agents/safety_planner.txt", variables)
    assert "{{latest_models}}" in rendered.text and rendered.missing == ("latest_models",)


def test_values_are_inserted_verbatim(tmp_path):
    """A value is never re-parsed: ``{{other}}``, ``{% ... %}`` and ``{# ... #}`` inside it stay literal.

    ``str.replace`` walking the keys in order would have expanded the ``{{b}}``
    that ``a``'s value introduced; nothing relied on that and the registry does not
    reproduce it (a KB finding quoting a template must not be able to rewrite the prompt).
    """
    (tmp_path / "t.txt").write_text("{{a}}|{{b}}", encoding="utf-8")
    rendered = PromptRegistry(tmp_path).render("t.txt", {"a": "x {{b}} {% if %} {# c #}", "b": "y"})
    assert rendered.text == "x {{b}} {% if %} {# c #}|y" and rendered.missing == ()


def test_render_keeps_trailing_newline_and_whitespace(tmp_path):
    (tmp_path / "t.txt").write_text("a={{a}} b={{b}}\n\n  tail\n", encoding="utf-8")
    rendered = PromptRegistry(tmp_path).render("t.txt", {"a": "1", "b": "2"})
    assert rendered.text == "a=1 b=2\n\n  tail\n"
    assert rendered.template_sha == _sha("a={{a}} b={{b}}\n\n  tail\n")
    assert rendered.variables_sha == _sha('{"a":"1","b":"2"}')
    assert PromptRegistry(tmp_path).list() == ["t.txt"]
    with pytest.raises(FileNotFoundError):
        PromptRegistry(tmp_path).render("absent.txt", {})


def test_variables_sha_is_order_independent_and_distinguishes_values():
    assert canonical_variables({"b": 1, "a": Path("/x")}) == '{"a":"/x","b":1}'
    one = PromptRegistry(TEMPLATES).render("agents/model_scout.txt", {"date": "d", "scout_run": "s"})
    two = PromptRegistry(TEMPLATES).render("agents/model_scout.txt", {"scout_run": "s", "date": "d"})
    other = PromptRegistry(TEMPLATES).render("agents/model_scout.txt", {"scout_run": "s", "date": "e"})
    assert one.variables_sha == two.variables_sha != other.variables_sha
    assert one.template_sha == other.template_sha


def test_domain_override_changes_template_id(tmp_path):
    (tmp_path / "agents").mkdir()
    (tmp_path / "domains" / "finance").mkdir(parents=True)
    (tmp_path / "agents" / "x.txt").write_text("base {{k}}", encoding="utf-8")
    (tmp_path / "domains" / "finance" / "x.txt").write_text("finance {{k}}", encoding="utf-8")
    registry = PromptRegistry(tmp_path)
    assert registry.render("agents/x.txt", {"k": "v"}, domain="physics").text == "base v"
    rendered = registry.render("agents/x.txt", {"k": "v"}, domain="finance")
    assert rendered.text == "finance v" and rendered.template_id == "agents/x.txt:domains/finance"


# -- research roles: the PromptGenerator wrapper changes nothing ---------------------------------------------
def test_resource_finder_prompt_matches_golden():
    direct = PromptGenerator(TEMPLATES).generate_resource_finder_prompt(IDEA, provider="claude")
    assert_golden("resource_finder", direct)
    rendered = PromptRegistry(TEMPLATES).render_role("resource_finder", IDEA, None, provider="claude")
    assert rendered.text == direct
    # the composition also reads the state contract; the id and sha cover every layer
    assert rendered.template_id == "agents/resource_finder.txt+agents/state_contract.txt"
    assert rendered.template_sha == _sha((TEMPLATES / "agents/resource_finder.txt").read_text(encoding="utf-8")
                                         + (TEMPLATES / "agents/state_contract.txt").read_text(encoding="utf-8"))
    assert rendered.variables_sha == _sha(canonical_variables(
        {"role": "resource_finder", "idea": IDEA, "work_dir": None, "provider": "claude"}))


def test_research_prompt_matches_golden():
    direct = PromptGenerator(TEMPLATES).generate_research_prompt(IDEA, root_dir=WORK_DIR)
    assert_golden("research", direct)
    rendered = PromptRegistry(TEMPLATES).render_role("researcher", IDEA, WORK_DIR)
    assert rendered.text == direct
    assert rendered.template_id == "base/researcher.txt+domains/machine_learning/core.txt"
    assert rendered.template_sha == _sha((TEMPLATES / "base/researcher.txt").read_text(encoding="utf-8")
                                         + (TEMPLATES / "domains/machine_learning/core.txt").read_text(encoding="utf-8"))
    assert PromptRegistry(TEMPLATES).render_role("experiment_runner", IDEA, WORK_DIR).text == direct


def test_unknown_role_is_rejected():
    with pytest.raises(KeyError, match="no prompt generator for role 'judge'"):
        PromptRegistry(TEMPLATES).render_role("judge", IDEA, None)


# -- the ledger line carries the hashes --------------------------------------------------------------------
def test_planner_and_scout_runs_record_template_and_variables_sha(kb, fake_cli, monkeypatch):
    monkeypatch.setattr(model_scout, "is_stale", lambda kb: False)
    monkeypatch.delenv("NEURICO_AGENT_PROVIDER", raising=False)
    outcome = planner.run_planner(kb, "camp", provider="claude", mode="replicate", timeout=60)
    assert outcome["ok"] and outcome["agent_run_id"]
    [entry] = RunLedger.read(kb.root / ".neurico" / "agent_runs.jsonl")
    prompt = fake_cli.last()["prompt"]
    assert entry["gen_ai.agent.name"] == "planner" and entry["template_id"] == "agents/safety_planner.txt"
    assert entry["template_sha"] == _sha(planner.TEMPLATE.read_text(encoding="utf-8"))
    assert entry["prompt_sha256"] == _sha(prompt) and len(entry["variables_sha"]) == 64
    assert "<KB_ROOT>" not in prompt and str(kb.root) in prompt

    scouted = model_scout.run_scout(kb, provider="claude", timeout=60)
    assert scouted["ok"]
    entries = RunLedger.read(kb.root / ".neurico" / "agent_runs.jsonl")
    assert [e["gen_ai.agent.name"] for e in entries] == ["planner", "model_scout"]
    assert entries[1]["template_id"] == "agents/model_scout.txt"
    assert entries[1]["template_sha"] == _sha(model_scout.TEMPLATE.read_text(encoding="utf-8"))
    assert len(entries[1]["variables_sha"]) == 64 and entries[1]["variables_sha"] != entry["variables_sha"]
    assert entries[1]["prompt_sha256"] == _sha(fake_cli.last()["prompt"])
