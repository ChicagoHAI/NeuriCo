"""Tests for smart bootstrap rule_maker activation, old-protocol input, and
isolate-when-sealed baseline scoring (continue-research).

Covers the decision logic and helpers that drive re-running the bootstrap
rule maker when new evaluation materials are supplied or no protocol exists,
the trusted-source read of a prior protocol, its injection into the prompt,
and the routing of the baseline scorer to the isolated path when sealed data
is declared. The agent/eval executions themselves are out of scope for unit
tests (they need a provider CLI).

Run: python -m pytest tests/test_bootstrap_regeneration.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.local_resources import (  # noqa: E402
    read_scoring_materials_fingerprint,
    record_scoring_materials_fingerprint,
    scoring_materials_fingerprint,
    scoring_protocol_present,
)


def _idea(datasets=None, metrics=None, results_format=None):
    inner = {"title": "A sufficiently long title", "domain": "machine_learning"}
    lr = {}
    if datasets is not None:
        lr["datasets"] = datasets
    if lr:
        inner["local_resources"] = lr
    ev = {}
    if metrics is not None:
        ev["metrics"] = metrics
    if results_format is not None:
        ev["results_format"] = results_format
    if ev:
        inner["evaluation"] = ev
    return {"idea": inner}


# ------------------------------------------------------------- fingerprint

def test_fingerprint_is_path_stable():
    # The declared path becomes data/.test/<name> after staging; the
    # fingerprint must not change when only the path changes.
    a = _idea(datasets=[{"name": "hold", "path": "/host/bench", "sealed": True}])
    b = _idea(datasets=[{"name": "hold", "path": "data/.test/hold", "sealed": True}])
    assert scoring_materials_fingerprint(a) == scoring_materials_fingerprint(b)


def test_fingerprint_dict_order_independent():
    a = _idea(metrics=[{"name": "m1", "definition": "d1", "target": "1"},
                       {"name": "m2", "definition": "d2", "target": "2"}])
    b = _idea(metrics=[{"name": "m2", "definition": "d2", "target": "2"},
                       {"name": "m1", "definition": "d1", "target": "1"}])
    assert scoring_materials_fingerprint(a) == scoring_materials_fingerprint(b)


def test_fingerprint_changes_on_new_material():
    base = _idea(datasets=[{"name": "hold", "path": "x", "sealed": True}],
                 metrics=[{"name": "m", "definition": "d", "target": "5"}])
    add_dataset = _idea(
        datasets=[{"name": "hold", "path": "x", "sealed": True},
                  {"name": "hold2", "path": "y", "sealed": True}],
        metrics=[{"name": "m", "definition": "d", "target": "5"}])
    add_metric = _idea(
        datasets=[{"name": "hold", "path": "x", "sealed": True}],
        metrics=[{"name": "m", "definition": "d", "target": "5"},
                 {"name": "m2", "definition": "d2", "target": "9"}])
    fp = scoring_materials_fingerprint(base)
    assert scoring_materials_fingerprint(add_dataset) != fp
    assert scoring_materials_fingerprint(add_metric) != fp


def test_fingerprint_ignores_unsealed_datasets():
    a = _idea(datasets=[{"name": "hold", "path": "x", "sealed": True}])
    b = _idea(datasets=[{"name": "hold", "path": "x", "sealed": True},
                        {"name": "train", "path": "z"}])
    assert scoring_materials_fingerprint(a) == scoring_materials_fingerprint(b)


def test_fingerprint_record_and_read_roundtrip(tmp_path):
    idea = _idea(metrics=[{"name": "m", "definition": "d", "target": "5"}])
    assert read_scoring_materials_fingerprint(tmp_path) is None
    record_scoring_materials_fingerprint(tmp_path, idea)
    assert (read_scoring_materials_fingerprint(tmp_path)
            == scoring_materials_fingerprint(idea))


# ------------------------------------------- activation decision inputs

def test_scoring_protocol_present_detection(tmp_path):
    # Raw/wiped workspace: no protocol.
    assert scoring_protocol_present(tmp_path) is False
    scoring = tmp_path / "scoring"
    scoring.mkdir()
    (scoring / "eval.py").write_text("print(1)")
    assert scoring_protocol_present(tmp_path) is False  # targets.json missing
    (scoring / "targets.json").write_text("{}")
    assert scoring_protocol_present(tmp_path) is True


def test_activation_conditions_match_runner_logic(tmp_path):
    # Mirror the runner branch: need_bootstrap = protocol_missing OR
    # materials_changed. Three cases.
    idea = _idea(datasets=[{"name": "hold", "path": "x", "sealed": True}])

    # (1) No protocol present -> fire.
    protocol_missing = not scoring_protocol_present(tmp_path)
    materials_changed = (read_scoring_materials_fingerprint(tmp_path)
                         != scoring_materials_fingerprint(idea))
    assert (protocol_missing or materials_changed) is True

    # Establish a protocol + record fingerprint.
    (tmp_path / "scoring").mkdir()
    (tmp_path / "scoring" / "eval.py").write_text("x")
    (tmp_path / "scoring" / "targets.json").write_text("{}")
    record_scoring_materials_fingerprint(tmp_path, idea)

    # (2) Same materials -> skip.
    protocol_missing = not scoring_protocol_present(tmp_path)
    materials_changed = (read_scoring_materials_fingerprint(tmp_path)
                         != scoring_materials_fingerprint(idea))
    assert (protocol_missing or materials_changed) is False

    # (3) New material -> fire.
    idea2 = _idea(datasets=[{"name": "hold", "path": "x", "sealed": True},
                            {"name": "hold2", "path": "y", "sealed": True}])
    materials_changed = (read_scoring_materials_fingerprint(tmp_path)
                         != scoring_materials_fingerprint(idea2))
    assert materials_changed is True


# ------------------------------------------- prior protocol (trusted read)

def test_read_prior_protocol_none_when_absent(tmp_path):
    from agents.rule_maker_bootstrap import read_prior_scoring_protocol
    assert read_prior_scoring_protocol(tmp_path) is None


def test_read_prior_protocol_prefers_sealed_copy(tmp_path):
    # A workspace at <root>/<name> has its sealed copy at
    # <root>/.scoring_sealed/<name>. The sealed copy (last validated, out of
    # the agent's reach) must win over a tampered workspace copy.
    from agents.rule_maker_bootstrap import read_prior_scoring_protocol
    from core.scoring_seal import sealed_dir_for

    work = tmp_path / "workspaces" / "idea"
    (work / "scoring").mkdir(parents=True)
    (work / "scoring" / "eval.py").write_text("TAMPERED")
    (work / "scoring" / "targets.json").write_text("{}")

    sealed = sealed_dir_for(work)
    (sealed / "scoring").mkdir(parents=True)
    (sealed / "scoring" / "eval.py").write_text("TRUSTED")
    (sealed / "scoring" / "targets.json").write_text("{}")
    (sealed / "scoring" / "interface.md").write_text("iface")

    prior = read_prior_scoring_protocol(work)
    assert prior is not None
    assert prior["eval"] == "TRUSTED"
    assert prior["interface"] == "iface"


def test_read_prior_protocol_ignores_untrusted_workspace_copy(tmp_path):
    # SECURITY: with only a worker-writable workspace copy and no sealed copy,
    # the prior read must return None ("no prior"), never trust the workspace.
    from agents.rule_maker_bootstrap import read_prior_scoring_protocol
    work = tmp_path / "workspaces" / "idea"
    (work / "scoring").mkdir(parents=True)
    (work / "scoring" / "eval.py").write_text("WS")
    (work / "scoring" / "targets.json").write_text("{}")
    assert read_prior_scoring_protocol(work) is None


def test_prompt_injects_prior_protocol_only_when_given(tmp_path):
    from agents.rule_maker_bootstrap import generate_bootstrap_rule_maker_prompt

    templates_dir = Path(__file__).resolve().parents[1] / "templates"
    work = tmp_path / "work"
    (work / ".neurico").mkdir(parents=True)

    fresh = generate_bootstrap_rule_maker_prompt(
        curated_manifest={}, work_dir=work, templates_dir=templates_dir,
        prior_protocol=None)
    assert "PRIOR SCORING PROTOCOL" not in fresh

    regen = generate_bootstrap_rule_maker_prompt(
        curated_manifest={}, work_dir=work, templates_dir=templates_dir,
        prior_protocol={"eval": "OLD_EVAL_CODE", "targets": "{}", "interface": "iface"})
    assert "PRIOR SCORING PROTOCOL" in regen
    assert "OLD_EVAL_CODE" in regen


# ------------------------------------------- isolate-when-sealed routing

def test_baseline_scorer_isolates_when_sealed(tmp_path, monkeypatch):
    # _run_scorer must route to the isolated path when the idea declares
    # sealed datasets, and stay in-workspace otherwise.
    import core.pipeline_orchestrator as po

    orch = po.ResearchPipelineOrchestrator(work_dir=tmp_path)

    calls = {"isolated": 0, "in_workspace": 0}
    monkeypatch.setattr(
        orch, "_run_isolated_baseline_scorer",
        lambda timeout, idea: (calls.__setitem__("isolated", calls["isolated"] + 1)
                               or {"success": True}))
    monkeypatch.setattr(
        po, "run_scorer",
        lambda **kw: (calls.__setitem__("in_workspace", calls["in_workspace"] + 1)
                      or {"success": True}))

    sealed_idea = _idea(datasets=[{"name": "hold", "path": "x", "sealed": True}])
    orch._run_scorer(timeout=10, idea=sealed_idea)
    assert calls == {"isolated": 1, "in_workspace": 0}

    plain_idea = _idea(datasets=[{"name": "train", "path": "z"}])
    orch._run_scorer(timeout=10, idea=plain_idea)
    assert calls == {"isolated": 1, "in_workspace": 1}


# ---- Security fixes: trusted inputs, target floor, rebaseline restore -------

def test_prompt_uses_trusted_idea_not_workspace_copy(tmp_path):
    # SECURITY: the rule maker prompt must carry the trusted orchestrator idea,
    # not a tampered workspace .neurico/idea.yaml.
    from agents.rule_maker_bootstrap import generate_bootstrap_rule_maker_prompt

    templates_dir = Path(__file__).resolve().parents[1] / "templates"
    work = tmp_path / "work"
    (work / ".neurico").mkdir(parents=True)
    (work / ".neurico" / "idea.yaml").write_text(
        "idea:\n  title: TAMPERED_WORKSPACE_IDEA\n")

    trusted = {"idea": {"title": "TRUSTED_ORCHESTRATOR_IDEA",
                        "domain": "machine_learning"}}
    prompt = generate_bootstrap_rule_maker_prompt(
        curated_manifest={}, work_dir=work, templates_dir=templates_dir,
        prior_protocol=None, idea=trusted)
    assert "TRUSTED_ORCHESTRATOR_IDEA" in prompt
    assert "TAMPERED_WORKSPACE_IDEA" not in prompt


def test_target_floor_rejects_weakened_retained_target(tmp_path):
    from agents.rule_maker_bootstrap import check_target_floor
    work = tmp_path / "work"
    (work / "scoring").mkdir(parents=True)
    # New protocol lowers a 'max' target from 0.9 to 0.5.
    (work / "scoring" / "targets.json").write_text(
        '{"properties": {"acc": {"target": 0.5, "direction": "max"}}}')
    prior = {"targets": '{"properties": {"acc": {"target": 0.9, '
                        '"direction": "max"}}}', "eval": "", "interface": ""}
    violations = check_target_floor(work, prior_protocol=prior)
    assert violations and "acc" in violations[0]

    # Meeting or exceeding the prior is fine.
    (work / "scoring" / "targets.json").write_text(
        '{"properties": {"acc": {"target": 0.95, "direction": "max"}}}')
    assert check_target_floor(work, prior_protocol=prior) == []


def test_target_floor_uses_trusted_idea_declared_target(tmp_path):
    from agents.rule_maker_bootstrap import check_target_floor
    work = tmp_path / "work"
    (work / "scoring").mkdir(parents=True)
    (work / "scoring" / "targets.json").write_text(
        '{"properties": {"f1": {"target": 0.6, "direction": "max"}}}')
    idea = {"idea": {"evaluation": {"metrics": [
        {"name": "f1", "definition": "F1 score", "target": 0.8}]}}}
    violations = check_target_floor(work, trusted_idea=idea)
    assert violations and "f1" in violations[0]


def test_rebaseline_restores_current_best_not_agent_tree(tmp_path, monkeypatch):
    # SECURITY: force_rebaseline must re-score the VALIDATED current best, not
    # an agent-mutated working tree. We assert construct_bootstrap restores to
    # current_best_sha before checkpointing.
    import core.autoresearch as ar

    calls = {"restored": None}

    class FakeCheckpoints:
        def __init__(self, work_dir):
            pass

        def checkpoint_exists(self, sha):
            return sha == "BEST_SHA"

        def restore_checkpoint(self, sha, *, clean_untracked_public=False,
                               remove_hidden_scoring=False):
            calls["restored"] = sha

        def create_checkpoint(self, message):
            raise RuntimeError("stop after restore")  # halt before the pipeline

    monkeypatch.setattr(ar, "CheckpointManager", FakeCheckpoints)
    monkeypatch.setattr(ar, "read_autoresearch_state",
                        lambda w: {"current_best_sha": "BEST_SHA"})
    monkeypatch.setattr(ar, "autoresearch_state_current_best_sha",
                        lambda s: s.get("current_best_sha"))
    # read_prior_scoring_protocol returns None naturally (no sealed copy here).

    work = tmp_path / "workspaces" / "ws"
    (work / ".neurico").mkdir(parents=True)
    try:
        ar.construct_bootstrap_initial_node(
            idea={"idea": {"title": "t", "domain": "machine_learning"}},
            idea_id="id", work_dir=work, templates_dir=tmp_path / "templates",
            provider="claude", full_permissions=True, rule_maker_timeout=1,
            scorer_timeout=1, manifest_trimmer_timeout=1,
            autoresearch_history_dir=None, force_rebaseline=True)
    except RuntimeError:
        pass  # expected: we halt at create_checkpoint
    assert calls["restored"] == "BEST_SHA", \
        "rebaseline did not restore to the validated current best first"
