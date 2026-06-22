"""Unit tests for the v3 world-model data model (ResearchState).

Covers the PR-1 storage layer: findings-as-spine, layered decisions, structured
options, the new experiment/hypothesis/incident fields, and — critically —
forward-migration of a pre-v3 state file so the running manager never crashes on
an old `research_state.json`.

Run: python -m pytest tests/test_research_state.py
"""

import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from interactive.research_state import (  # noqa: E402
    DECISION_LAYERS, HYP_STATUSES, ResearchState, SCHEMA_VERSION,
)


def _fresh(tmp_path) -> ResearchState:
    return ResearchState(tmp_path)


# ---------------------------------------------------------------- findings

def test_add_finding_returns_f_id_and_dedups(tmp_path):
    r = _fresh(tmp_path)
    f1 = r.add_finding("CoT lifts GSM8K by 12pts", kind="result", insight="prompting matters")
    assert f1 == "F1"
    # Same text dedups to the same id; insight backfills.
    f1b = r.add_finding("cot lifts gsm8k by 12pts")
    assert f1b == "F1"
    assert len(r.state["findings"]) == 1
    f2 = r.add_finding("baseline overfits", kind="dead_end")
    assert f2 == "F2"
    fnode = r.state["findings"][0]
    assert fnode["kind"] == "result"
    assert fnode["insight"] == "prompting matters"
    assert fnode["evidence"] == [] and fnode["links"] == []


def test_add_finding_bad_kind_falls_back_to_note(tmp_path):
    r = _fresh(tmp_path)
    fid = r.add_finding("something", kind="bogus")
    assert r.state["findings"][0]["kind"] == "note"
    assert fid == "F1"


# --------------------------------------------------------------- decisions

def test_decision_defaults_to_global_and_normalizes_options(tmp_path):
    r = _fresh(tmp_path)
    did = r.add_decision(
        question="Which benchmark?", chosen="GSM8K",
        options=["GSM8K", "MATH", "SVAMP"], layer="experiment_design")
    assert did == "D1"
    d = r.state["decisions"][0]
    assert d["finding"] == "global"
    assert d["layer"] == "experiment_design"
    # legacy [str] options become [{text,status}] with the chosen one flagged
    statuses = {o["text"]: o["status"] for o in d["options"]}
    assert statuses["GSM8K"] == "chosen"
    assert statuses["MATH"] == "alternative"
    # review/interaction fields left empty for later agents
    assert d["importance"] == "" and d["should_engage"] is None
    assert d["sequence"] is None and d["author"] == ""


def test_decision_chosen_added_when_not_in_options(tmp_path):
    r = _fresh(tmp_path)
    r.add_decision(question="Q", chosen="surprise", options=["a", "b"])
    opts = r.state["decisions"][0]["options"]
    assert {"text": "surprise", "status": "chosen"} in opts


def test_decision_invalid_layer_becomes_none(tmp_path):
    r = _fresh(tmp_path)
    r.add_decision(question="Q", layer="not_a_layer")
    assert r.state["decisions"][0]["layer"] is None
    for layer in DECISION_LAYERS:
        r.add_decision(question=f"Q-{layer}", layer=layer)
    assert {d["layer"] for d in r.state["decisions"][1:]} == set(DECISION_LAYERS)


def test_reparent_decision(tmp_path):
    r = _fresh(tmp_path)
    fid = r.add_finding("a finding")
    did = r.add_decision(question="made before the finding existed")
    assert r.state["decisions"][0]["finding"] == "global"
    assert r.reparent_decision(did, fid) is True
    assert r.state["decisions"][0]["finding"] == fid
    assert r.reparent_decision("D999", fid) is False


def test_decisions_for_returns_layer_ordered(tmp_path):
    r = _fresh(tmp_path)
    fid = r.add_finding("f")
    r.add_decision(question="interp", finding=fid, layer="interpretation")
    r.add_decision(question="hyp", finding=fid, layer="hypothesis")
    r.add_decision(question="global one", finding="global", layer="method")
    got = [d["question"] for d in r.decisions_for(fid)]
    assert got == ["hyp", "interp"]  # hypothesis before interpretation; global excluded


# ------------------------------------------------------- hypotheses / exp

def test_refuted_is_a_valid_status(tmp_path):
    r = _fresh(tmp_path)
    assert "refuted" in HYP_STATUSES
    hid = r.upsert_hypothesis("H stmt", status="refuted")
    assert r.state["hypotheses"][0]["status"] == "refuted"
    # upsert by statement updates in place
    assert r.upsert_hypothesis("h stmt", status="supported") == hid
    assert r.state["hypotheses"][0]["status"] == "supported"


def test_experiment_carries_domain_general_fields(tmp_path):
    r = _fresh(tmp_path)
    eid = r.add_experiment(agent="experiment_runner", run_id="run-1",
                           name="GSM8K eval", mode="empirical_experiment",
                           design="vary prompt across 200 items")
    e = r.state["experiments"][0]
    assert eid == "E1"
    assert e["name"] == "GSM8K eval" and e["mode"] == "empirical_experiment"
    assert e["ranBy"] == "experiment_runner"  # provenance mirrors agent
    # bad mode is dropped to ""
    r.add_experiment(agent="x", run_id="run-2", mode="telepathy")
    assert r.state["experiments"][1]["mode"] == ""


def test_incident_records_author_and_dedups(tmp_path):
    r = _fresh(tmp_path)
    r.add_incident("tool_error", "boom", author="experiment_runner")
    r.add_incident("tool_error", "boom", author="experiment_runner")  # consecutive dup
    assert len(r.state["incidents"]) == 1
    assert r.state["incidents"][0]["author"] == "experiment_runner"


# ------------------------------------------------------------- migration

def test_blank_state_has_v3_shape(tmp_path):
    r = _fresh(tmp_path)
    assert r.state["schema_version"] == SCHEMA_VERSION
    # assessments node removed in PR 2 (engage signal moved onto decisions).
    assert "assessments" not in r.state
    assert not hasattr(r, "add_assessment")
    assert not hasattr(r, "latest_assessment")


def test_forward_migration_from_pre_v3_state(tmp_path):
    """A research_state.json written before v3: flat findings (no id), decisions
    with [str] options and no finding/layer, experiments without name/mode. Loading
    it must not crash and must backfill the v3 shape."""
    legacy = {
        "updated_at": "2026-01-01T00:00:00",
        "narrative": "old run", "current_best": "", "crux": "",
        "hypotheses": [{"id": "H1", "statement": "h", "status": "alive",
                        "evidence": "", "updated_at": "2026-01-01T00:00:00"}],
        "experiments": [{"id": "E1", "agent": "experiment_runner", "run_id": "r1",
                         "rationale": "", "hypothesis": "", "status": "done",
                         "result": "ok", "ts": "2026-01-01T00:00:00"}],
        "findings": [{"text": "a flat finding", "kind": "result",
                      "ts": "2026-01-01T00:00:00"}],
        "open_questions": [],
        "decisions": [{"id": "D1", "question": "old?", "options": ["x", "y"],
                       "chosen": "x", "rationale": "", "by": "manager",
                       "ts": "2026-01-01T00:00:00"}],
        "incidents": [{"ts": "2026-01-01T00:00:00", "kind": "tool_error",
                       "detail": "old boom"}],
    }
    neurico = tmp_path / ".neurico"
    neurico.mkdir(parents=True)
    (neurico / "research_state.json").write_text(json.dumps(legacy))

    r = ResearchState(tmp_path)

    # finding gained an F-id + v3 fields
    f = r.state["findings"][0]
    assert f["id"].startswith("F")
    assert f["insight"] == "" and f["evidence"] == [] and f["links"] == []
    # decision gained finding/layer + normalized options + empty review fields
    d = r.state["decisions"][0]
    assert d["finding"] == "global" and d["layer"] is None
    assert {o["text"]: o["status"] for o in d["options"]}["x"] == "chosen"
    assert d["importance"] == "" and d["should_engage"] is None
    # experiment gained name/mode/design/ranBy
    e = r.state["experiments"][0]
    assert e["ranBy"] == "experiment_runner" and e["mode"] == ""
    # incident gained author; hypothesis gained links
    assert r.state["incidents"][0]["author"] == ""
    assert r.state["hypotheses"][0]["links"] == []
    # migration is persisted and idempotent
    r2 = ResearchState(tmp_path)
    assert r2.state["findings"][0]["id"] == f["id"]


def test_migration_is_idempotent_no_duplicate_ids(tmp_path):
    r = _fresh(tmp_path)
    r.add_finding("one")
    r.add_finding("two")
    ids = [f["id"] for f in r.state["findings"]]
    r2 = ResearchState(tmp_path)
    assert [f["id"] for f in r2.state["findings"]] == ids == ["F1", "F2"]


# --------------------------------------------------------- read / render

def test_snapshot_and_digest_include_findings(tmp_path):
    r = _fresh(tmp_path)
    fid = r.add_finding("key result", insight="so what")
    r.add_decision(question="why?", finding=fid, layer="interpretation", chosen="because")
    snap = r.snapshot()
    assert snap["schema_version"] == SCHEMA_VERSION
    assert snap["counts"]["findings"] == 1
    assert any(f["id"] == fid for f in snap["findings"])
    digest = r.digest_section()
    assert "Findings (the spine" in digest
    assert fid in digest
    assert f"[{fid}/interpretation]" in digest


def test_empty_digest_message(tmp_path):
    r = _fresh(tmp_path)
    assert "empty" in r.digest_section()


# ------------------------------------------- manager authoring (PR 2 wiring)

def _executor(tmp_path):
    """A standalone ToolExecutor backed by a fresh ResearchState — enough to
    exercise the update_research_state authoring path without a live session."""
    from interactive.tools import ToolExecutor
    from interactive.channel import TerminalChannel
    return ToolExecutor(
        work_dir=tmp_path, session=None, idea_file=tmp_path,
        provider="claude", project_root=tmp_path,
        channel=TerminalChannel(), research=ResearchState(tmp_path))


def test_update_research_state_writes_rich_findings_and_decisions(tmp_path):
    ex = _executor(tmp_path)
    out = ex._update_research_state({
        "findings": [
            {"text": "CoT lifts GSM8K +12pts", "insight": "prompting matters",
             "kind": "result"},
            "a bare-string finding",
        ],
        "decision": {
            "question": "Which benchmark?", "chosen": "GSM8K",
            "rationale": "most standard", "options": ["GSM8K", "MATH"],
            "finding": "F1", "layer": "experiment_design",
        },
        "incident": "hit a transient docker error, retried",
    })
    assert "finding" in out and "decision" in out and "incident" in out
    r = ex.research
    f = r.state["findings"][0]
    assert f["id"] == "F1" and f["insight"] == "prompting matters"
    d = r.state["decisions"][0]
    assert d["finding"] == "F1" and d["layer"] == "experiment_design"
    assert {o["text"]: o["status"] for o in d["options"]}["GSM8K"] == "chosen"
    assert r.state["incidents"][0]["kind"] == "self_reported"


def test_update_research_state_decision_defaults_to_global(tmp_path):
    ex = _executor(tmp_path)
    ex._update_research_state({"decision": {"question": "dispatch which agent?",
                                            "chosen": "experiment_runner"}})
    d = ex.research.state["decisions"][0]
    assert d["finding"] == "global" and d["layer"] is None


def test_assess_tool_is_gone(tmp_path):
    ex = _executor(tmp_path)
    assert not hasattr(ex, "_assess")
    # Unknown tool is auto-logged as an incident rather than dispatched.
    out = ex.execute("assess", {"situation": "x", "engage_user": True})
    assert "Unknown tool" in out
    assert any(i["kind"] == "unknown_tool" for i in ex.research.state["incidents"])


# ---------------------------------------- concurrency / merge-on-save (PR 4)

def test_save_merges_instead_of_clobbering_other_writer(tmp_path):
    """Two instances load the same (empty) state; each writes a different record.
    The second save must FOLD IN the first's record, not overwrite it."""
    a = ResearchState(tmp_path)
    b = ResearchState(tmp_path)  # loaded before A writes — stale view
    a.add_finding("finding from A")           # A saves -> disk has F1
    b.add_incident("tool_error", "from B")    # B (stale) saves -> must keep F1
    fresh = ResearchState(tmp_path)
    assert [f["text"] for f in fresh.state["findings"]] == ["finding from A"]
    assert any(i["detail"] == "from B" for i in fresh.state["incidents"])


def test_untouched_scalar_not_clobbered_by_stale_writer(tmp_path):
    a = ResearchState(tmp_path)
    b = ResearchState(tmp_path)  # stale: crux still ""
    a.set_fields(crux="the real crux")        # A sets crux
    b.add_finding("unrelated")                # B never touched crux
    fresh = ResearchState(tmp_path)
    assert fresh.state["crux"] == "the real crux"      # not clobbered by B's ""
    assert any(f["text"] == "unrelated" for f in fresh.state["findings"])


def test_dirty_scalar_overwrites_last_writer_wins(tmp_path):
    a = ResearchState(tmp_path)
    b = ResearchState(tmp_path)
    a.set_fields(narrative="A's story")
    b.set_fields(narrative="B's story")       # B explicitly set it -> B wins
    assert ResearchState(tmp_path).state["narrative"] == "B's story"


def test_ids_mint_against_disk_no_collision_across_instances(tmp_path):
    a = ResearchState(tmp_path)
    fid_a = a.add_finding("alpha")            # F1
    b = ResearchState(tmp_path)               # loads, sees F1
    fid_b = b.add_finding("beta")             # must mint F2, not F1
    assert fid_a == "F1" and fid_b == "F2"
    fresh = ResearchState(tmp_path)
    assert [f["id"] for f in fresh.state["findings"]] == ["F1", "F2"]


def test_concurrent_threads_all_incidents_survive(tmp_path):
    """N threads, each its own ResearchState, append a unique incident at once.
    The flock + merge must preserve every one (incidents union by kind/detail)."""
    ResearchState(tmp_path)  # initialize the file
    n = 8
    barrier = threading.Barrier(n)

    def worker(i):
        r = ResearchState(tmp_path)
        barrier.wait()  # maximize overlap
        r.add_incident("worker", f"incident-{i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    fresh = ResearchState(tmp_path)
    details = {i["detail"] for i in fresh.state["incidents"]}
    assert {f"incident-{i}" for i in range(n)} <= details
