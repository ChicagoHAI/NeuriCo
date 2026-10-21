"""Shared fixtures: a fake provider CLI so launch paths run end to end offline.

``fake_cli`` installs ``claude``, ``codex``, ``gemini`` and ``scribe`` wrappers
first on ``PATH``; each runs ``tests/fixtures/bin/fake_cli.py`` under the test
interpreter (``-I`` keeps the host's ``PYTHON*`` variables and site-packages out
of it). The wrappers record every invocation to a JSONL capture file, which is
how characterisation tests read the exact argv, cwd, prompt and environment a
call site produced without ever launching a real agent.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

FAKE_CLI = Path(__file__).resolve().parent / "fixtures" / "bin" / "fake_cli.py"
FAKE_CLI_NAMES = ("claude", "codex", "gemini", "scribe")
CONTROL_VARS = ("NEURICO_FAKE_CLI_EXIT", "NEURICO_FAKE_CLI_SLEEP", "NEURICO_FAKE_CLI_FILES",
                "NEURICO_FAKE_CLI_TOUCH", "NEURICO_FAKE_CLI_SPAWN_CHILD",
                "NEURICO_FAKE_CLI_RESULT_TEXT", "NEURICO_FAKE_CLI_STRUCTURED")


@dataclass
class FakeCli:
    """Handle on the fake CLIs: configure behaviour, read back what was launched."""

    bin_dir: Path
    capture: Path
    monkeypatch: pytest.MonkeyPatch

    def configure(self, *, exit_code: Any = None, sleep: Optional[float] = None,
                  files: Any = None, touch: Optional[List[str]] = None,
                  spawn_child: bool = False, result_text: Optional[str] = None,
                  structured: Any = None) -> None:
        """Set the control variables for the next launches (unset ones are cleared).

        ``exit_code`` and ``files`` may be lists to vary behaviour per launch.
        """
        values = {
            "NEURICO_FAKE_CLI_EXIT": None if exit_code is None else json.dumps(exit_code),
            "NEURICO_FAKE_CLI_SLEEP": None if sleep is None else str(sleep),
            "NEURICO_FAKE_CLI_FILES": json.dumps(files) if files else None,
            "NEURICO_FAKE_CLI_TOUCH": os.pathsep.join(touch) if touch else None,
            "NEURICO_FAKE_CLI_SPAWN_CHILD": "1" if spawn_child else None,
            "NEURICO_FAKE_CLI_RESULT_TEXT": result_text,
            "NEURICO_FAKE_CLI_STRUCTURED": json.dumps(structured) if structured is not None else None,
        }
        for name, value in values.items():
            if value is None:
                self.monkeypatch.delenv(name, raising=False)
            else:
                self.monkeypatch.setenv(name, value)

    def records(self) -> List[Dict[str, Any]]:
        if not self.capture.exists():
            return []
        return [json.loads(line) for line in self.capture.read_text(encoding="utf-8").splitlines() if line]

    def last(self) -> Dict[str, Any]:
        records = self.records()
        assert records, "the fake CLI was never launched"
        return records[-1]

    @staticmethod
    def added_env_keys(record: Dict[str, Any]) -> set:
        """Keys the launch added relative to the test process environment."""
        return set(record["env_keys"]) - set(os.environ) - {"NEURICO_FAKE_CLI_NAME"}

    @staticmethod
    def removed_env_keys(record: Dict[str, Any]) -> set:
        """Keys the launch dropped (exported shell functions are dropped by ``sh`` itself)."""
        return {k for k in set(os.environ) - set(record["env_keys"]) if not k.startswith("BASH_FUNC_")}


@pytest.fixture(autouse=True)
def _agent_ledger_in_tmp(tmp_path, monkeypatch):
    """Call sites now go through AgentFactory, which also appends to the project-wide
    ledger (logs/agent_runs.jsonl); tests must never write there. The price table
    (config/prices.yaml) is data that changes with the invoices, so tests see none
    unless they pass a path to ``price_usage`` themselves."""
    monkeypatch.setenv("NEURICO_AGENT_LEDGER", str(tmp_path / "agent_runs.global.jsonl"))
    src = str(FAKE_CLI.parents[3] / "src")
    if src not in sys.path:  # test modules add it themselves; a lone module may not have yet
        sys.path.insert(0, src)
    import core.agent_factory as agent_factory
    monkeypatch.setattr(agent_factory, "PRICES_PATH", tmp_path / "no-prices.yaml")


@pytest.fixture
def fake_cli(tmp_path, monkeypatch) -> FakeCli:
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    for name in FAKE_CLI_NAMES:
        wrapper = bin_dir / name
        wrapper.write_text(
            "#!/bin/sh\n"
            f"NEURICO_FAKE_CLI_NAME={name} exec \"{sys.executable}\" -I \"{FAKE_CLI}\" \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    capture = tmp_path / "fake-cli-capture.jsonl"
    monkeypatch.setenv("NEURICO_FAKE_CLI_CAPTURE", str(capture))
    for name in CONTROL_VARS:
        monkeypatch.delenv(name, raising=False)
    return FakeCli(bin_dir=bin_dir, capture=capture, monkeypatch=monkeypatch)
