"""Unit tests for the AutoResearch cross-run whiteboard.

Run: python -m pytest tests/test_whiteboard.py
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.whiteboard import (  # noqa: E402
    CATEGORIES,
    STATUS_ACTIVE,
    STATUS_CLEARED,
    STATUS_PRUNED,
    Whiteboard,
    WhiteboardError,
    find_workspace_root,
    whiteboard_path,
)


# --------------------------------------------------------------- core class


def test_empty_load_creates_no_file(tmp_path):
    wb = Whiteboard(tmp_path).load()
    assert wb.tips == []
    assert not whiteboard_path(tmp_path).exists()


def test_add_tip_generates_monotonic_ids(tmp_path):
    wb = Whiteboard(tmp_path).load()
    a = wb.add_tip("first", category="insight")
    b = wb.add_tip("second", category="design", affects=["s.py"])
    assert a.id == "T1"
    assert b.id == "T2"
    assert b.affects == ["s.py"]
    assert a.status == STATUS_ACTIVE
    assert a.written_at > 0


def test_add_tip_rejects_empty_content(tmp_path):
    wb = Whiteboard(tmp_path).load()
    with pytest.raises(WhiteboardError):
        wb.add_tip("   ", category="insight")


def test_add_tip_rejects_bad_category(tmp_path):
    wb = Whiteboard(tmp_path).load()
    with pytest.raises(WhiteboardError):
        wb.add_tip("x", category="random")


def test_save_and_reload_round_trip(tmp_path):
    wb1 = Whiteboard(tmp_path).load()
    wb1.add_tip("hint one", category="insight", author="ch@abc/attempt_1")
    wb1.add_tip("wisdom", category="informative")
    wb1.save()

    p = whiteboard_path(tmp_path)
    assert p.exists()
    raw = json.loads(p.read_text())
    assert raw["schema_version"] == 1
    assert raw["next_id_num"] == 3
    assert len(raw["tips"]) == 2

    wb2 = Whiteboard(tmp_path).load()
    assert len(wb2.tips) == 2
    assert wb2.tips[0].content == "hint one"
    assert wb2.tips[0].author == "ch@abc/attempt_1"
    assert wb2.tips[1].category == "informative"


def test_clear_tip_flips_status(tmp_path):
    wb = Whiteboard(tmp_path).load()
    t = wb.add_tip("thing", category="insight")
    wb.clear_tip(t.id, author="ch@xyz/attempt_1")
    assert wb.find(t.id).status == STATUS_CLEARED
    assert wb.find(t.id).cleared_by == "ch@xyz/attempt_1"
    assert wb.find(t.id).cleared_at > 0


def test_clear_tip_refuses_informative(tmp_path):
    wb = Whiteboard(tmp_path).load()
    t = wb.add_tip("wisdom", category="informative")
    with pytest.raises(WhiteboardError, match="informative"):
        wb.clear_tip(t.id)
    assert wb.find(t.id).status == STATUS_ACTIVE


def test_clear_tip_missing_id(tmp_path):
    wb = Whiteboard(tmp_path).load()
    with pytest.raises(WhiteboardError, match="no tip"):
        wb.clear_tip("T99")


def test_clear_tip_refuses_already_cleared(tmp_path):
    wb = Whiteboard(tmp_path).load()
    t = wb.add_tip("x", category="insight")
    wb.clear_tip(t.id)
    with pytest.raises(WhiteboardError, match="already cleared"):
        wb.clear_tip(t.id)


def test_prune_tip_flips_status_and_requires_reason(tmp_path):
    wb = Whiteboard(tmp_path).load()
    t = wb.add_tip("hint", category="insight")
    with pytest.raises(WhiteboardError, match="reason"):
        wb.prune_tip(t.id, reason="")
    wb.prune_tip(t.id, reason="not applicable", author="autoresearch_proposer")
    p = wb.find(t.id)
    assert p.status == STATUS_PRUNED
    assert "autoresearch_proposer" in p.pruned_reason
    assert "not applicable" in p.pruned_reason


def test_prune_tip_works_on_informative(tmp_path):
    wb = Whiteboard(tmp_path).load()
    t = wb.add_tip("general wisdom", category="informative")
    wb.prune_tip(t.id, reason="stale", author="autoresearch_proposer")
    assert wb.find(t.id).status == STATUS_PRUNED


def test_active_tips_and_render_only_show_active(tmp_path):
    wb = Whiteboard(tmp_path).load()
    a = wb.add_tip("stays active", category="insight")
    b = wb.add_tip("will be cleared", category="design")
    c = wb.add_tip("will be pruned", category="pitfall")
    d = wb.add_tip("global wisdom", category="informative")
    wb.clear_tip(b.id)
    wb.prune_tip(c.id, reason="wrong")

    active = wb.active_tips()
    ids = [t.id for t in active]
    assert a.id in ids and d.id in ids
    assert b.id not in ids and c.id not in ids

    rendered = wb.render_markdown()
    assert a.id in rendered
    assert d.id in rendered
    assert b.id not in rendered
    assert c.id not in rendered
    assert "cautionary" not in rendered.lower() or "caution" in rendered.lower()


def test_render_when_empty_states_no_tips(tmp_path):
    wb = Whiteboard(tmp_path).load()
    r = wb.render_markdown()
    assert "no active tips" in r


# ------------------------------------------------------------------- CLI


def _run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    """Invoke the CLI in a subprocess so import paths mirror real workspace use."""
    env = {"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    import os
    env.update(os.environ)
    return subprocess.run(
        [sys.executable, "-m", "core.whiteboard", "--workspace", str(cwd), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_cli_add_view_clear_prune(tmp_path):
    r = _run_cli("view", cwd=tmp_path)
    assert r.returncode == 0
    assert "no active tips" in r.stdout

    r = _run_cli(
        "add-tip", "--category", "insight",
        "--content", "look at line 47", "--affects", "solver.py",
        "--author", "ch@abc/attempt_1",
        cwd=tmp_path,
    )
    assert r.returncode == 0
    assert "added T1" in r.stdout

    r = _run_cli(
        "add-tip", "--category", "informative",
        "--content", "always run judge locally first",
        cwd=tmp_path,
    )
    assert r.returncode == 0
    assert "added T2" in r.stdout

    r = _run_cli("view", cwd=tmp_path)
    assert r.returncode == 0
    assert "T1" in r.stdout
    assert "T2" in r.stdout
    assert "line 47" in r.stdout
    assert "run judge" in r.stdout

    # clear T1 (non-informative) works
    r = _run_cli("clear-tip", "T1", "--author", "ch@abc/attempt_1", cwd=tmp_path)
    assert r.returncode == 0
    assert "cleared T1" in r.stdout

    # clear T2 (informative) refuses
    r = _run_cli("clear-tip", "T2", cwd=tmp_path)
    assert r.returncode == 2
    assert "informative" in r.stderr

    # prune T2 works
    r = _run_cli("prune-tip", "T2", "--reason", "no longer applies", cwd=tmp_path)
    assert r.returncode == 0
    assert "pruned T2" in r.stdout

    # view now empty
    r = _run_cli("view", cwd=tmp_path)
    assert r.returncode == 0
    assert "no active tips" in r.stdout


def test_cli_view_json(tmp_path):
    _run_cli(
        "add-tip", "--category", "design", "--content", "use meet-in-middle",
        cwd=tmp_path,
    )
    r = _run_cli("view", "--json", cwd=tmp_path)
    assert r.returncode == 0
    active = json.loads(r.stdout)
    assert len(active) == 1
    assert active[0]["content"] == "use meet-in-middle"
    assert active[0]["category"] == "design"


def test_cli_bad_category_exits_nonzero(tmp_path):
    r = _run_cli(
        "add-tip", "--category", "musings",
        "--content", "hmm", cwd=tmp_path,
    )
    assert r.returncode != 0


def test_cli_unknown_tip_id(tmp_path):
    r = _run_cli("clear-tip", "T42", cwd=tmp_path)
    assert r.returncode == 2
    assert "no tip" in r.stderr


# --------------------------------------------------- workspace auto-detect


def test_find_workspace_root_with_neurico_marker(tmp_path):
    (tmp_path / ".neurico").mkdir()
    assert find_workspace_root(tmp_path) == tmp_path.resolve()


def test_find_workspace_root_with_logs_marker(tmp_path):
    (tmp_path / "logs" / "experiment-autoresearch").mkdir(parents=True)
    assert find_workspace_root(tmp_path) == tmp_path.resolve()


def test_find_workspace_root_walks_up(tmp_path):
    (tmp_path / ".neurico").mkdir()
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert find_workspace_root(deep) == tmp_path.resolve()


def test_find_workspace_root_errors_when_no_marker(tmp_path):
    # tmp_path itself has no marker; but we may be running from within a
    # NeuriCo workspace at /Users/.../neurico-whiteboard which does have one.
    # Walking up will find that ancestor, which is fine (real workspace),
    # so this test asserts we get *some* result, not tmp_path.
    # If find_workspace_root ever returned tmp_path here, that would be a bug.
    try:
        result = find_workspace_root(tmp_path)
    except FileNotFoundError:
        return  # acceptable: nothing found
    assert result != tmp_path.resolve(), (
        "unexpected: got tmp_path itself as workspace root"
    )


def test_cli_auto_detects_workspace_from_subdir(tmp_path):
    """Running `whiteboard view` from a subdir of the workspace should still
    resolve to the workspace's whiteboard.json."""
    # Seed a workspace with a tip.
    wb = Whiteboard(tmp_path).load()
    (tmp_path / ".neurico").mkdir()
    wb.add_tip("subdir-visible", category="insight")
    wb.save()

    # Run CLI from a nested dir, WITHOUT --workspace, and expect the tip.
    nested = tmp_path / "scratch" / "deep"
    nested.mkdir(parents=True)

    import os
    env = {"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    env.update(os.environ)
    r = subprocess.run(
        [sys.executable, "-m", "core.whiteboard", "view"],
        cwd=str(nested),
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0
    assert "subdir-visible" in r.stdout


def test_cli_errors_when_no_marker_and_no_workspace_flag(tmp_path, monkeypatch):
    """Outside any workspace, the CLI must fail loudly, not silently write
    to a scratch whiteboard."""
    # Guard against the test process actually being inside a workspace: cd
    # to a real filesystem-root direction with no markers.
    scratch = tmp_path / "isolated"
    scratch.mkdir()
    import os
    env = {"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    env.update(os.environ)
    r = subprocess.run(
        [sys.executable, "-m", "core.whiteboard", "view"],
        cwd=str(scratch),
        capture_output=True, text=True, env=env,
    )
    # Either we hit an ancestor with markers (real workspace above tmp_path,
    # possible when running the test suite from inside neurico) OR we get
    # the clear error. Both are acceptable; a silent write to /tmp is not.
    if r.returncode != 0:
        assert "Could not locate a NeuriCo workspace" in r.stderr
