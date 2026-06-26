"""Tests for the decision-log skill."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

NEURICO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(NEURICO_ROOT / "templates" / "skills" / "decision-log" / "scripts"))
from decision_log import (  # noqa: E402
    CATEGORIES,
    DECISION_CATEGORIES,
    OBSERVATION_CATEGORIES,
    CycleError,
    DecisionLog,
    DecisionNode,
)


@pytest.fixture
def chain():
    """A small DAG used by many tests.

           a (model)
          / \
         b   d
         |
         c
    """
    log = DecisionLog()
    a = log.add(question="model?", choice="VideoMAE", category="model")
    b = log.add(question="features?", choice="intermediate", category="method",
                premises=[a])
    c = log.add(question="layer?", choice="block 8", category="hyperparam",
                premises=[b])
    d = log.add(question="frames?", choice="16", category="hyperparam",
                premises=[a])
    return log, a, b, c, d


# =============================================================
class TestAddHappy:
    def test_add_root_no_premises(self):
        log = DecisionLog()
        aid = log.add(question="Q", choice="C", category="model")
        n = log.get(aid)
        assert n.status == "active"
        assert n.premises == []
        assert n.created_at != ""

    def test_add_with_single_premise(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        b = log.add(question="Q", choice="B", category="hyperparam", premises=[a])
        assert log.get(b).premises == [a]

    def test_add_with_multiple_premises(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        b = log.add(question="Q", choice="B", category="dataset")
        c = log.add(question="Q", choice="C", category="hyperparam", premises=[a, b])
        assert log.get(c).premises == [a, b]

    def test_add_with_explicit_id(self):
        log = DecisionLog()
        aid = log.add(question="Q", choice="X", category="model", id="my-id")
        assert aid == "my-id"

    def test_add_with_rationale_and_alternatives(self):
        log = DecisionLog()
        aid = log.add(question="Q", choice="VideoMAE-Large", category="model",
                      rationale="MAE transfers",
                      alternatives=["TimeSformer", "I3D"])
        n = log.get(aid)
        assert n.rationale == "MAE transfers"
        assert n.alternatives == ["TimeSformer", "I3D"]
        assert "videomae" in aid.lower()

    def test_duplicate_slug_auto_suffixes(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="X", category="model")
        b = log.add(question="Q", choice="X", category="model")
        c = log.add(question="Q", choice="X", category="model")
        assert a != b != c
        assert b.endswith("-2")
        assert c.endswith("-3")

    @pytest.mark.parametrize("cat", sorted(DECISION_CATEGORIES))
    def test_each_valid_decision_category(self, cat):
        log = DecisionLog()
        log.add(question="Q", choice=cat, category=cat)
        assert len(log.find()) == 1

    def test_premises_as_tuple(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        b = log.add(question="Q", choice="B", category="dataset")
        c = log.add(question="Q", choice="C", category="hyperparam", premises=(a, b))
        assert log.get(c).premises == [a, b]

    def test_premises_as_generator(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        b = log.add(question="Q", choice="B", category="dataset")
        c = log.add(question="Q", choice="C", category="hyperparam",
                    premises=(p for p in [a, b]))
        assert log.get(c).premises == [a, b]


# =============================================================
class TestAddErrors:
    def test_rejects_unknown_category(self):
        log = DecisionLog()
        with pytest.raises(ValueError, match="category"):
            log.add(question="Q", choice="C", category="bogus")

    def test_rejects_unknown_premise(self):
        log = DecisionLog()
        with pytest.raises(ValueError, match="does not exist"):
            log.add(question="Q", choice="C", category="model", premises=["nope"])

    def test_rejects_revoked_premise(self, chain):
        log, a, b, c, d = chain
        log.revoke(b)
        with pytest.raises(ValueError, match="active"):
            log.add(question="x", choice="y", category="hyperparam", premises=[b])

    def test_rejects_suspect_premise(self, chain):
        log, a, b, c, d = chain
        log.revoke(a)   # b becomes suspect
        with pytest.raises(ValueError, match="active"):
            log.add(question="x", choice="y", category="hyperparam", premises=[b])

    def test_rejects_duplicate_premises(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        with pytest.raises(ValueError, match="duplicate"):
            log.add(question="Q", choice="B", category="hyperparam", premises=[a, a])


# =============================================================
class TestUpdateHappy:
    def test_update_rationale(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        log.update(a, rationale="new reason")
        assert log.get(a).rationale == "new reason"

    def test_update_choice_and_question(self):
        log = DecisionLog()
        a = log.add(question="old?", choice="old", category="model")
        log.update(a, choice="new", question="new?")
        assert log.get(a).choice == "new"
        assert log.get(a).question == "new?"

    def test_update_premises_to_add_new_one(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        b = log.add(question="Q", choice="B", category="dataset")
        c = log.add(question="Q", choice="C", category="hyperparam", premises=[a])
        log.update(c, premises=[a, b])
        assert log.get(c).premises == [a, b]

    def test_update_alternatives(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        log.update(a, alternatives=["B", "C"])
        assert log.get(a).alternatives == ["B", "C"]


# =============================================================
class TestUpdateErrors:
    def test_rejects_unknown_field(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        with pytest.raises(ValueError):
            log.update(a, status="revoked")

    def test_rejects_category_change(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        with pytest.raises(ValueError):
            log.update(a, category="dataset")

    def test_rejects_nonexistent_premise(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        b = log.add(question="Q", choice="B", category="dataset", premises=[a])
        with pytest.raises(ValueError, match="exist"):
            log.update(b, premises=["nope"])

    def test_rejects_revoked_premise(self, chain):
        log, a, b, c, d = chain
        log.revoke(b)
        with pytest.raises(ValueError, match="active"):
            log.update(d, premises=[a, b])

    def test_rejects_duplicate_premises(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        b = log.add(question="Q", choice="B", category="hyperparam", premises=[a])
        with pytest.raises(ValueError, match="duplicate"):
            log.update(b, premises=[a, a])

    def test_rejects_premise_update_on_revoked_node(self, chain):
        log, a, b, c, d = chain
        log.revoke(a)
        # Rationale on revoked node is OK
        log.update(a, rationale="historical note")
        assert "historical note" in log.get(a).rationale
        # Premise update on revoked is rejected
        with pytest.raises(ValueError):
            log.update(a, premises=[])

    def test_rejects_premise_update_on_suspect_node(self, chain):
        log, a, b, c, d = chain
        log.revoke(a)
        with pytest.raises(ValueError):
            log.update(b, premises=[])


# =============================================================
class TestDeleteRemoved:
    def test_delete_method_is_gone(self):
        log = DecisionLog()
        assert not hasattr(log, "delete")


# =============================================================
class TestRevoke:
    def test_revoke_leaf_no_cascade(self, chain):
        log, a, b, c, d = chain
        suspects = log.revoke(c)
        assert suspects == []
        assert log.get(c).status == "revoked"
        assert log.get(c).revoked_root == c

    def test_revoke_root_full_cascade(self, chain):
        log, a, b, c, d = chain
        suspects = log.revoke(a)
        assert set(suspects) == {b, c, d}
        assert log.get(a).status == "revoked"
        for x in (b, c, d):
            assert log.get(x).status == "suspect"
            assert log.get(x).revoked_root == a

    def test_revoke_middle_partial_cascade(self, chain):
        log, a, b, c, d = chain
        suspects = log.revoke(b)
        assert set(suspects) == {c}
        assert log.get(a).status == "active"
        assert log.get(d).status == "active"
        assert log.get(c).status == "suspect"

    def test_revoke_twice_is_idempotent(self, chain):
        log, a, b, c, d = chain
        log.revoke(a)
        assert log.revoke(a) == []

    def test_revoke_suspect_promotes_to_revoked(self, chain):
        log, a, b, c, d = chain
        log.revoke(a)
        assert log.get(b).status == "suspect"
        log.revoke(b)
        assert log.get(b).status == "revoked"
        assert log.get(b).revoked_root == b   # now self-root
        # c was already suspect from cascade; remains suspect
        assert log.get(c).status == "suspect"

    def test_reason_appended_to_rationale(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model", rationale="initial")
        log.revoke(a, reason="moving on")
        assert "moving on" in log.get(a).rationale
        assert "initial" in log.get(a).rationale

    def test_revoke_leaves_siblings_alone(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        e = log.add(question="Q", choice="E", category="eval")
        f = log.add(question="Q", choice="F", category="dataset", premises=[e])
        log.revoke(a)
        assert log.get(e).status == "active"
        assert log.get(f).status == "active"


# =============================================================
class TestReconfirm:
    def test_reconfirm_with_new_premises(self, chain):
        log, a, b, c, d = chain
        log.revoke(a)
        a2 = log.add(question="Q", choice="TimeSformer", category="model")
        log.reconfirm(d, premises=[a2])
        assert log.get(d).status == "active"
        assert log.get(d).premises == [a2]
        assert log.get(d).revoked_root is None

    def test_reconfirm_drops_revoked_premises_when_premises_is_none(self, chain):
        log, a, b, c, d = chain
        log.revoke(a)
        log.reconfirm(b)
        assert log.get(b).status == "active"
        assert log.get(b).premises == []

    def test_rationale_appended(self, chain):
        log, a, b, c, d = chain
        log.revoke(a)
        log.reconfirm(b, rationale="model-agnostic")
        assert "model-agnostic" in log.get(b).rationale

    def test_rejects_active_node(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        with pytest.raises(ValueError, match="suspect"):
            log.reconfirm(a)

    def test_rejects_revoked_node(self, chain):
        log, a, b, c, d = chain
        log.revoke(a)
        with pytest.raises(ValueError, match="suspect"):
            log.reconfirm(a)

    def test_rejects_nonexistent_premise(self, chain):
        log, a, b, c, d = chain
        log.revoke(a)
        with pytest.raises(ValueError, match="exist"):
            log.reconfirm(b, premises=["nope"])

    def test_rejects_nonactive_premise(self, chain):
        log, a, b, c, d = chain
        log.revoke(a)   # b, c, d all suspect
        with pytest.raises(ValueError, match="active"):
            log.reconfirm(c, premises=[b])

    def test_rejects_cycle(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        b = log.add(question="Q", choice="B", category="method", premises=[a])
        c = log.add(question="Q", choice="C", category="hyperparam", premises=[b])
        log.revoke(a)
        with pytest.raises((CycleError, ValueError)):
            log.reconfirm(b, premises=[c])

    def test_bottom_up_sequence_after_deep_revoke(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        b = log.add(question="Q", choice="B", category="method", premises=[a])
        c = log.add(question="Q", choice="C", category="hyperparam", premises=[b])
        d = log.add(question="Q", choice="D", category="eval", premises=[c])
        log.revoke(a)
        assert all(log.get(x).status == "suspect" for x in (b, c, d))
        a2 = log.add(question="Q", choice="A2", category="model")
        log.reconfirm(b, premises=[a2])
        log.reconfirm(c)
        log.reconfirm(d)
        assert all(log.get(x).status == "active" for x in (b, c, d))
        assert log.get(c).premises == [b]


# =============================================================
class TestCycle:
    def test_self_cycle_rejected(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        with pytest.raises(CycleError):
            log.update(a, premises=[a])

    def test_two_cycle_rejected(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        b = log.add(question="Q", choice="B", category="method", premises=[a])
        with pytest.raises(CycleError):
            log.update(a, premises=[b])

    def test_three_cycle_rejected(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        b = log.add(question="Q", choice="B", category="method", premises=[a])
        c = log.add(question="Q", choice="C", category="hyperparam", premises=[b])
        with pytest.raises(CycleError):
            log.update(a, premises=[c])


# =============================================================
class TestRead:
    def test_get_raises_keyerror(self):
        log = DecisionLog()
        with pytest.raises(KeyError):
            log.get("nope")

    def test_find_empty_log(self):
        assert DecisionLog().find() == []

    def test_find_by_category(self):
        log = DecisionLog()
        log.add(question="Q", choice="m", category="model")
        log.add(question="Q", choice="h", category="hyperparam")
        res = log.find(category="model")
        assert len(res) == 1
        assert res[0].choice == "m"

    def test_find_query_matches_question_choice_rationale(self):
        log = DecisionLog()
        log.add(question="which encoder?", choice="x", category="model")
        log.add(question="Q", choice="VideoMAE", category="model")
        log.add(question="Q", choice="x", category="model", rationale="motion features")
        assert len(log.find(query="encoder")) == 1
        assert len(log.find(query="videomae")) == 1   # case-insensitive
        assert len(log.find(query="motion")) == 1

    def test_find_active_only_false_shows_all(self, chain):
        log, a, b, c, d = chain
        log.revoke(a)
        assert len(log.find(active_only=False)) == 4
        assert log.find() == []   # all four non-active

    def test_suspects_returns_only_suspect(self, chain):
        log, a, b, c, d = chain
        log.revoke(a)
        assert {n.id for n in log.suspects()} == {b, c, d}

    def test_subtree_of_leaf(self, chain):
        log, a, b, c, d = chain
        assert log.subtree(c) == []
        assert log.subtree(d) == []

    def test_subtree_of_root(self, chain):
        log, a, b, c, d = chain
        assert set(log.subtree(a)) == {b, c, d}

    def test_subtree_of_middle(self, chain):
        log, a, b, c, d = chain
        assert set(log.subtree(b)) == {c}

    def test_premises_of_direct(self, chain):
        log, a, b, c, d = chain
        assert log.premises_of(c) == [b]

    def test_premises_of_recursive_diamond_no_dup(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="a", category="model")
        b = log.add(question="Q", choice="b", category="method", premises=[a])
        c = log.add(question="Q", choice="c", category="method", premises=[a])
        d = log.add(question="Q", choice="d", category="hyperparam", premises=[b, c])
        rec = log.premises_of(d, recursive=True)
        assert sorted(rec) == sorted([a, b, c])


# =============================================================
class TestDAGShapes:
    def test_diamond_revoke_a(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="a", category="model")
        b = log.add(question="Q", choice="b", category="method", premises=[a])
        c = log.add(question="Q", choice="c", category="method", premises=[a])
        d = log.add(question="Q", choice="d", category="hyperparam", premises=[b, c])
        assert set(log.revoke(a)) == {b, c, d}

    def test_diamond_revoke_b(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="a", category="model")
        b = log.add(question="Q", choice="b", category="method", premises=[a])
        c = log.add(question="Q", choice="c", category="method", premises=[a])
        d = log.add(question="Q", choice="d", category="hyperparam", premises=[b, c])
        assert set(log.revoke(b)) == {d}
        assert log.get(c).status == "active"

    def test_deep_chain_revoke_top(self):
        log = DecisionLog()
        ids = []
        prev = None
        for i in range(6):
            kw = dict(question=f"q{i}", choice=f"c{i}", category="hyperparam")
            if prev is not None:
                kw["premises"] = [prev]
            ids.append(log.add(**kw))
            prev = ids[-1]
        assert set(log.revoke(ids[0])) == set(ids[1:])

    def test_multi_root_independent_dags(self):
        log = DecisionLog()
        a1 = log.add(question="Q", choice="a1", category="model")
        b1 = log.add(question="Q", choice="b1", category="method", premises=[a1])
        a2 = log.add(question="Q", choice="a2", category="dataset")
        b2 = log.add(question="Q", choice="b2", category="eval", premises=[a2])
        log.revoke(a1)
        assert log.get(a2).status == "active"
        assert log.get(b2).status == "active"


# =============================================================
class TestExport:
    def test_json_round_trip_structure(self, chain):
        log, a, b, c, d = chain
        log.revoke(b)
        payload = json.loads(log.export("json"))
        assert set(payload) == {a, b, c, d}
        assert payload[b]["status"] == "revoked"
        assert payload[c]["status"] == "suspect"

    def test_dot_per_status_color(self, chain):
        log, a, b, c, d = chain
        log.revoke(a)
        dot = log.export("dot")
        assert "digraph" in dot
        assert "color=red" in dot
        assert "color=orange" in dot

    def test_md_groups_by_node(self, chain):
        log, _, _, _, _ = chain
        assert log.export("md").count("## ") == 4

    def test_unknown_format_rejected(self):
        with pytest.raises(ValueError):
            DecisionLog().export("xml")


# =============================================================
class TestRobustness:
    def test_special_chars_sanitized_in_slug(self):
        log = DecisionLog()
        aid = log.add(question="Q", choice="VideoMAE-L (v2)!", category="model")
        assert all(c.isalnum() or c == "-" for c in aid)

    def test_long_choice_truncated(self):
        log = DecisionLog()
        aid = log.add(question="Q", choice="x" * 200, category="model")
        assert len(aid) <= 40

    def test_re_revoke_after_reconfirm(self, chain):
        log, a, b, c, d = chain
        log.revoke(a)
        a2 = log.add(question="Q", choice="A2", category="model")
        log.reconfirm(b, premises=[a2])
        log.reconfirm(c, premises=[b])
        log.reconfirm(d, premises=[a2])
        assert set(log.revoke(b)) == {c}


# =============================================================
class TestPersistence:
    def test_no_path_no_file(self):
        log = DecisionLog()
        log.add(question="Q", choice="A", category="model")
        # Doesn't crash; no file to check.

    def test_save_creates_file(self, tmp_path):
        path = tmp_path / "decisions.json"
        assert not path.exists()
        log = DecisionLog(path=path)
        log.add(question="Q", choice="A", category="model")
        assert path.exists()

    def test_save_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "decisions.json"
        log = DecisionLog(path=path)
        log.add(question="Q", choice="A", category="model")
        assert path.exists()

    def test_reload_preserves_graph(self, tmp_path):
        path = tmp_path / "decisions.json"
        log1 = DecisionLog(path=path)
        a = log1.add(question="Q", choice="A", category="model", rationale="r1")
        b = log1.add(question="Q", choice="B", category="hyperparam", premises=[a])
        log1.update(b, rationale="r2")

        log2 = DecisionLog(path=path)
        assert log2.get(a).choice == "A"
        assert log2.get(a).rationale == "r1"
        assert log2.get(b).rationale == "r2"
        assert log2.get(b).premises == [a]

    def test_reload_preserves_revoked_and_suspect(self, tmp_path):
        path = tmp_path / "decisions.json"
        log1 = DecisionLog(path=path)
        a = log1.add(question="Q", choice="A", category="model")
        b = log1.add(question="Q", choice="B", category="method", premises=[a])
        c = log1.add(question="Q", choice="C", category="hyperparam", premises=[b])
        log1.revoke(a, reason="moving on")
        log2 = DecisionLog(path=path)
        assert log2.get(a).status == "revoked"
        assert log2.get(b).status == "suspect"
        assert log2.get(c).status == "suspect"
        assert log2.get(b).revoked_root == a

    def test_reload_preserves_created_at(self, tmp_path):
        path = tmp_path / "decisions.json"
        log1 = DecisionLog(path=path)
        a = log1.add(question="Q", choice="A", category="model")
        ts1 = log1.get(a).created_at
        log2 = DecisionLog(path=path)
        assert log2.get(a).created_at == ts1
        assert ts1 != ""

    def test_file_contains_schema_version(self, tmp_path):
        path = tmp_path / "decisions.json"
        log = DecisionLog(path=path)
        log.add(question="Q", choice="A", category="model")
        data = json.loads(path.read_text())
        assert data["_schema_version"] == 1
        assert "nodes" in data

    def test_unsupported_schema_rejected(self, tmp_path):
        path = tmp_path / "decisions.json"
        path.write_text(json.dumps({"_schema_version": 99, "nodes": {}}))
        with pytest.raises(ValueError, match="schema"):
            DecisionLog(path=path)

    def test_revoke_persists(self, tmp_path):
        path = tmp_path / "decisions.json"
        log = DecisionLog(path=path)
        a = log.add(question="Q", choice="A", category="model")
        log.revoke(a)
        data = json.loads(path.read_text())
        assert data["nodes"][a]["status"] == "revoked"

    def test_reconfirm_persists(self, tmp_path):
        path = tmp_path / "decisions.json"
        log = DecisionLog(path=path)
        a = log.add(question="Q", choice="A", category="model")
        b = log.add(question="Q", choice="B", category="method", premises=[a])
        log.revoke(a)
        log.reconfirm(b)
        data = json.loads(path.read_text())
        assert data["nodes"][b]["status"] == "active"
        assert data["nodes"][b]["premises"] == []

    def test_atomic_save_leaves_no_tmp(self, tmp_path):
        path = tmp_path / "decisions.json"
        log = DecisionLog(path=path)
        log.add(question="Q", choice="A", category="model")
        log.add(question="Q", choice="B", category="dataset")
        files = sorted(p.name for p in tmp_path.iterdir())
        assert files == ["decisions.json"]

    def test_partial_tmp_does_not_corrupt(self, tmp_path):
        path = tmp_path / "decisions.json"
        log1 = DecisionLog(path=path)
        a = log1.add(question="Q", choice="A", category="model")
        # Simulate a crashed mid-write leaving an orphan .tmp
        (path.parent / "decisions.json.tmp").write_text("{ not valid json")
        log2 = DecisionLog(path=path)
        assert log2.get(a).choice == "A"

    def test_revoked_only_graph_round_trips(self, tmp_path):
        path = tmp_path / "decisions.json"
        log1 = DecisionLog(path=path)
        a = log1.add(question="Q", choice="A", category="model")
        log1.revoke(a, reason="rethinking")
        log2 = DecisionLog(path=path)
        assert log2.find() == []
        all_ = log2.find(active_only=False)
        assert len(all_) == 1
        assert all_[0].status == "revoked"

    def test_lists_round_trip(self, tmp_path):
        path = tmp_path / "decisions.json"
        log1 = DecisionLog(path=path)
        a = log1.add(question="Q", choice="A", category="model")
        b = log1.add(question="Q", choice="B", category="dataset")
        c = log1.add(question="Q", choice="C", category="hyperparam",
                     premises=[a, b], alternatives=["alt1", "alt2", "alt3"])
        log2 = DecisionLog(path=path)
        assert log2.get(c).premises == [a, b]
        assert log2.get(c).alternatives == ["alt1", "alt2", "alt3"]


# =============================================================
class TestSlugPolish:
    def test_collapses_consecutive_dashes(self):
        log = DecisionLog()
        aid = log.add(question="Q", choice="16 frames @ 4 fps", category="hyperparam")
        assert "--" not in aid

    def test_collapses_adjacent_special_runs(self):
        log = DecisionLog()
        aid = log.add(question="Q", choice="VideoMAE-L (v2)!", category="model")
        assert "--" not in aid

    def test_slug_only_alnum_and_single_dashes(self):
        log = DecisionLog()
        aid = log.add(question="Q", choice="x@@y!!z", category="model")
        assert all(c.isalnum() or c == "-" for c in aid)
        assert "--" not in aid

    def test_collision_after_collapse_still_suffixes(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="X Y Z", category="model")
        b = log.add(question="Q", choice="X--Y--Z", category="model")
        assert a != b
        assert b.endswith("-2")


# =============================================================
class TestObservations:
    def test_observe_creates_observation_node(self):
        log = DecisionLog()
        oid = log.observe(observation="Class imbalance is 4:1", category="data_property")
        n = log.get(oid)
        assert n.node_type == "observation"
        assert n.choice == "Class imbalance is 4:1"
        assert n.category == "data_property"
        assert n.status == "active"

    def test_add_creates_decision_node_by_default(self):
        log = DecisionLog()
        did = log.add(question="Q", choice="A", category="model")
        assert log.get(did).node_type == "decision"

    def test_observe_stores_source_as_rationale(self):
        log = DecisionLog()
        oid = log.observe(observation="73K notes after dedup",
                          category="data_property", source="train.csv inspection")
        assert log.get(oid).rationale == "train.csv inspection"

    def test_observation_can_be_about_a_decision(self):
        log = DecisionLog()
        ds = log.add(question="Dataset?", choice="MIMIC", category="dataset")
        oid = log.observe(observation="MIMIC has 73K notes",
                          category="data_property", about=[ds])
        assert log.get(oid).premises == [ds]

    def test_decision_can_premise_on_observation(self):
        log = DecisionLog()
        obs = log.observe(observation="Class imbalance 4:1", category="data_property")
        met = log.add(question="Metric?", choice="balanced acc",
                      category="eval", premises=[obs],
                      rationale="addresses observed imbalance")
        assert log.get(met).premises == [obs]

    def test_observe_rejects_unknown_category(self):
        log = DecisionLog()
        with pytest.raises(ValueError, match="observation category"):
            log.observe(observation="x", category="bogus")

    def test_observe_rejects_decision_category(self):
        # `dataset` is a decision category — not allowed for observations.
        log = DecisionLog()
        with pytest.raises(ValueError, match="observation category"):
            log.observe(observation="x", category="dataset")

    def test_add_rejects_observation_category(self):
        # `paper_finding` is an observation category — not allowed for decisions.
        log = DecisionLog()
        with pytest.raises(ValueError, match="decision category"):
            log.add(question="Q", choice="A", category="paper_finding")

    def test_observe_rejects_non_active_about(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="A", category="model")
        log.revoke(a)
        with pytest.raises(ValueError, match="active"):
            log.observe(observation="x", category="other", about=[a])

    def test_revoke_decision_cascades_to_dependent_observation(self):
        log = DecisionLog()
        ds = log.add(question="Dataset?", choice="MIMIC", category="dataset")
        obs = log.observe(observation="MIMIC has 73K notes",
                          category="data_property", about=[ds])
        suspects = log.revoke(ds, reason="switching")
        assert obs in suspects
        assert log.get(obs).status == "suspect"

    def test_revoke_observation_cascades_to_dependent_decision(self):
        log = DecisionLog()
        obs = log.observe(observation="Class imbalance 4:1", category="data_property")
        met = log.add(question="Metric?", choice="balanced acc",
                      category="eval", premises=[obs])
        suspects = log.revoke(obs, reason="misread")
        assert met in suspects
        assert log.get(met).status == "suspect"

    def test_find_filter_by_node_type(self):
        log = DecisionLog()
        log.add(question="Q", choice="A", category="model")
        log.add(question="Q", choice="B", category="dataset")
        log.observe(observation="X", category="paper_finding")
        log.observe(observation="Y", category="env_fact")
        assert len(log.find(node_type="decision")) == 2
        assert len(log.find(node_type="observation")) == 2
        assert len(log.find()) == 4

    def test_decisions_and_observations_helpers(self):
        log = DecisionLog()
        log.add(question="Q", choice="A", category="model")
        log.observe(observation="X", category="other")
        assert len(log.decisions()) == 1
        assert len(log.observations()) == 1

    def test_find_rejects_unknown_node_type(self):
        log = DecisionLog()
        with pytest.raises(ValueError, match="node_type"):
            log.find(node_type="bogus")

    def test_observation_round_trips_through_persistence(self, tmp_path):
        path = tmp_path / "decisions.json"
        log1 = DecisionLog(path=path)
        ds = log1.add(question="Q", choice="A", category="dataset")
        oid = log1.observe(observation="finding X", category="paper_finding",
                           about=[ds], source="paper:Table 2")
        log2 = DecisionLog(path=path)
        n = log2.get(oid)
        assert n.node_type == "observation"
        assert n.choice == "finding X"
        assert n.rationale == "paper:Table 2"
        assert n.premises == [ds]

    def test_mixed_dag_decision_obs_decision(self):
        log = DecisionLog()
        ds = log.add(question="Dataset?", choice="MIMIC", category="dataset")
        obs = log.observe(observation="73K class-imbalanced 4:1",
                          category="data_property", about=[ds])
        met = log.add(question="Metric?", choice="balanced acc",
                      category="eval", premises=[obs])
        suspects = log.revoke(ds)
        assert set(suspects) == {obs, met}

    def test_md_export_distinguishes_observations(self):
        log = DecisionLog()
        log.add(question="Q", choice="A", category="model")
        log.observe(observation="X", category="paper_finding")
        md = log.export("md")
        assert "OBSERVATION" in md
        assert "Observation: X" in md

    def test_dot_export_uses_different_shape(self):
        log = DecisionLog()
        log.add(question="Q", choice="A", category="model")
        log.observe(observation="X", category="paper_finding")
        dot = log.export("dot")
        assert "shape=box" in dot
        assert "shape=ellipse" in dot

    @pytest.mark.parametrize("cat", sorted(OBSERVATION_CATEGORIES))
    def test_each_valid_observation_category(self, cat):
        log = DecisionLog()
        log.observe(observation=f"sample {cat}", category=cat)
        assert len(log.observations()) == 1


# =============================================================
class TestTriageOrder:
    def test_empty_when_no_suspects(self):
        log = DecisionLog()
        log.add(question="Q", choice="A", category="model")
        assert log.triage_order() == []

    def test_single_suspect_after_middle_revoke(self, chain):
        log, a, b, c, d = chain
        log.revoke(b)
        assert log.triage_order() == [c]

    def test_topological_in_deep_chain(self):
        log = DecisionLog()
        ids = []
        prev = None
        for i in range(5):
            kw = dict(question=f"q{i}", choice=f"c{i}", category="hyperparam")
            if prev is not None:
                kw["premises"] = [prev]
            ids.append(log.add(**kw))
            prev = ids[-1]
        log.revoke(ids[0])
        assert log.triage_order() == ids[1:]

    def test_diamond_puts_merge_node_last(self):
        log = DecisionLog()
        a = log.add(question="Q", choice="a", category="model")
        b = log.add(question="Q", choice="b", category="method", premises=[a])
        c = log.add(question="Q", choice="c", category="method", premises=[a])
        d = log.add(question="Q", choice="d", category="hyperparam", premises=[b, c])
        log.revoke(a)
        order = log.triage_order()
        assert set(order) == {b, c, d}
        assert order.index(d) > order.index(b)
        assert order.index(d) > order.index(c)

    def test_deterministic_by_id(self):
        log = DecisionLog()
        a1 = log.add(question="Q", choice="z-first", category="model")
        a2 = log.add(question="Q", choice="a-second", category="dataset")
        b1 = log.add(question="Q", choice="b1", category="method", premises=[a1])
        b2 = log.add(question="Q", choice="b2", category="method", premises=[a2])
        log.revoke(a1)
        log.revoke(a2)
        order = log.triage_order()
        assert order == sorted([b1, b2])

    def test_shrinks_after_partial_reconfirm(self, chain):
        log, a, b, c, d = chain
        log.revoke(a)
        log.reconfirm(b)
        order = log.triage_order()
        assert set(order) == {c, d}
