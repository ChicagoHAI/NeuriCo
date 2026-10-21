"""Step 2 of docs/AGENT_FACTORY_ASSESSMENT.md: the raw ``Popen`` sites now launch
through ``AgentFactory.run``.

The old loops read stdout to EOF before ``wait(timeout=...)``, so their timeout
never fired while the agent was alive and nothing cleaned up children. Each test
here drives the real call site against a fake CLI that keeps streaming past the
deadline and spawns a child, and proves three things: the timeout fires while
the agent is still running, the whole process group is reaped, and the ledger
has a line for the launch.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from core import agent_auth  # noqa: E402
from core.run_ledger import RunLedger  # noqa: E402
from test_agent_characterisation import LANE_VARS  # noqa: E402

TIMEOUT_S = 1
MAX_WALL_S = 15  # generous: SIGTERM, 5 s grace, SIGKILL, reader join


@pytest.fixture
def oauth(monkeypatch):
    for name in LANE_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("NEURICO_AGENT_PROVIDER", raising=False)
    monkeypatch.setattr(agent_auth, "patched_codex_catalog", lambda env=None: None)


@pytest.fixture
def hanging_cli(fake_cli):
    """A provider that streams, then sleeps far past the deadline with a live child."""
    fake_cli.configure(sleep=30, spawn_child=True)
    return fake_cli


def assert_reaped(child_pid: int) -> None:
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    pytest.fail(f"child process {child_pid} survived the timeout")


def ledger_entry(ledger_root: Path, role: str) -> dict:
    entries = [e for e in RunLedger.read(ledger_root / ".neurico" / "agent_runs.jsonl") if e["gen_ai.agent.name"] == role]
    assert len(entries) == 1, f"expected one {role} ledger line, got {entries}"
    return entries[0]


def workspace(tmp_path: Path) -> Path:
    work = tmp_path / "ws"
    work.mkdir()
    return work


# -- 1 resource finder, marker mode ----------------------------------------------------------------------------

def test_resource_finder_marker_mode_times_out(hanging_cli, tmp_path, oauth):
    from agents.resource_finder import run_resource_finder

    work = workspace(tmp_path)
    started = time.time()
    result = run_resource_finder({}, work, provider="claude", prompt_override="p", timeout=TIMEOUT_S)
    assert time.time() - started < MAX_WALL_S
    assert result["success"] is False and result["completion_marker"] is None
    assert_reaped(hanging_cli.last()["child_pid"])
    entry = ledger_entry(work, "resource_finder")
    assert entry["status"] == "timeout" and entry["log_file"] == str(work / "logs" / "resource_finder_claude.log")


# -- 3 bootstrap rule maker -----------------------------------------------------------------------------------------

def test_rule_maker_bootstrap_times_out(hanging_cli, tmp_path, oauth, monkeypatch):
    from agents import rule_maker_bootstrap

    monkeypatch.setattr(rule_maker_bootstrap, "generate_bootstrap_rule_maker_prompt", lambda **kw: "p")
    work = workspace(tmp_path)
    started = time.time()
    result = rule_maker_bootstrap.run_bootstrap_rule_maker({}, work, provider="codex", timeout=TIMEOUT_S,
                                                           log_dir=tmp_path / "bootstrap-logs")
    assert time.time() - started < MAX_WALL_S
    assert result["success"] is False and "timed out" in result["error"]
    assert_reaped(hanging_cli.last()["child_pid"])
    assert ledger_entry(work, "rule_maker_bootstrap")["status"] == "timeout"
