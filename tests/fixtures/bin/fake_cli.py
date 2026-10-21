#!/usr/bin/env python3
"""Fake ``claude`` / ``codex`` / ``gemini`` / ``scribe`` CLI for tests.

NeuriCo launches coding agents as subprocesses with the prompt on stdin. Tests
cannot reach the real CLIs (network, login, cost), so this script stands in for
them: it is installed first on ``PATH`` by the ``fake_cli`` fixture in
``tests/conftest.py`` and behaves like the real transport without doing any work.

Behaviour is driven by environment variables so launch code needs no test hooks:

    NEURICO_FAKE_CLI_CAPTURE      JSONL file; one record per invocation (argv, cwd,
                                  prompt, env keys, non-secret env values, pids)
    NEURICO_FAKE_CLI_EXIT         exit code (default 0), or a JSON list indexed by launch
    NEURICO_FAKE_CLI_SLEEP        seconds to sleep before the final result line
    NEURICO_FAKE_CLI_FILES        JSON object {relative path: content} written to cwd,
                                  or a JSON list of such objects indexed by launch
    NEURICO_FAKE_CLI_TOUCH        os.pathsep-separated relative paths to create empty
    NEURICO_FAKE_CLI_SPAWN_CHILD  "1": spawn a sleeping child (process-group tests)
    NEURICO_FAKE_CLI_RESULT_TEXT  final assistant text in the canned transcript
    NEURICO_FAKE_CLI_STRUCTURED   JSON for Claude's ``structured_output``

The transcript emitted on stdout mirrors each provider's real stream format
closely enough for NeuriCo's parsers: Claude ``stream-json`` ending in a
``result`` line (usage, total_cost_usd, session_id), Codex ``--json`` JSONL
(``thread.started`` ... ``turn.completed`` with usage) and Gemini
``stream-json``. One line of stderr noise is always emitted so tests can check
whether stderr is kept out of a provider's JSONL transcript.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SECRET_NAME = re.compile(r"(API_KEY|_KEY$|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)


def _provider() -> str:
    name = os.environ.get("NEURICO_FAKE_CLI_NAME") or Path(sys.argv[0]).name
    if name == "scribe" and len(sys.argv) > 1:
        return sys.argv[1]
    return name


def _invocation_index() -> int:
    """How many launches the capture file already holds: lets a test vary behaviour per attempt."""
    capture = os.environ.get("NEURICO_FAKE_CLI_CAPTURE")
    if not capture or not Path(capture).exists():
        return 0
    return sum(1 for line in Path(capture).read_text(encoding="utf-8").splitlines() if line.strip())


def _per_attempt(value):
    """A JSON list is indexed by invocation (last entry repeats); anything else applies to every launch."""
    if isinstance(value, list):
        return value[min(_invocation_index(), len(value) - 1)] if value else None
    return value


def _write_requested_files() -> None:
    files = _per_attempt(json.loads(os.environ.get("NEURICO_FAKE_CLI_FILES") or "{}")) or {}
    for rel, content in files.items():
        path = Path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    touch = os.environ.get("NEURICO_FAKE_CLI_TOUCH") or ""
    for rel in filter(None, touch.split(os.pathsep)):
        Path(rel).parent.mkdir(parents=True, exist_ok=True)
        Path(rel).touch()


def _record(prompt: str, child_pid) -> None:
    capture = os.environ.get("NEURICO_FAKE_CLI_CAPTURE")
    if not capture:
        return
    env = os.environ
    name = os.environ.get("NEURICO_FAKE_CLI_NAME") or Path(sys.argv[0]).name
    record = {
        "provider": _provider(),
        "argv": [name] + sys.argv[1:],
        "cwd": os.getcwd(),
        "prompt": prompt,
        "env_keys": sorted(env),
        "env": {k: v for k, v in env.items() if not SECRET_NAME.search(k)},
        "blank_keys": sorted(k for k, v in env.items() if v == ""),
        "pid": os.getpid(),
        "child_pid": child_pid,
    }
    with open(capture, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _emit(obj) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _streaming_requested() -> bool:
    """Only `--output-format stream-json` / `--json` launches get an event stream, as with the real CLIs."""
    return "--json" in sys.argv or "stream-json" in sys.argv


def _transcript(provider: str, text: str) -> None:
    structured = os.environ.get("NEURICO_FAKE_CLI_STRUCTURED")
    sleep = float(os.environ.get("NEURICO_FAKE_CLI_SLEEP") or 0)
    if not _streaming_requested():
        time.sleep(sleep)
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    elif provider == "claude":
        _emit({"type": "system", "subtype": "init", "session_id": "fake-session-1234",
               "model": "claude-sonnet-4-6", "tools": [], "cwd": os.getcwd()})
        _emit({"type": "assistant", "message": {"role": "assistant",
               "content": [{"type": "text", "text": text}]}, "session_id": "fake-session-1234"})
        time.sleep(sleep)
        result = {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 1234,
                  "duration_api_ms": 1000, "num_turns": 3, "result": text,
                  "session_id": "fake-session-1234", "total_cost_usd": 0.0123,
                  "usage": {"input_tokens": 120, "cache_creation_input_tokens": 30,
                            "cache_read_input_tokens": 400, "output_tokens": 45},
                  "modelUsage": {"claude-sonnet-4-6": {"inputTokens": 120, "outputTokens": 45,
                                 "cacheReadInputTokens": 400, "cacheCreationInputTokens": 30,
                                 "costUSD": 0.0123}}}
        if structured:
            result["structured_output"] = json.loads(structured)
        _emit(result)
    elif provider == "codex":
        _emit({"type": "thread.started", "thread_id": "fake-thread-1234"})
        _emit({"type": "turn.started"})
        _emit({"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": text}})
        time.sleep(sleep)
        _emit({"type": "turn.completed", "usage": {"input_tokens": 200, "cached_input_tokens": 150,
                                                   "output_tokens": 60}})
    else:
        _emit({"type": "init", "session_id": "fake-gemini-1234", "model": "gemini-2.5-pro"})
        _emit({"type": "message", "role": "assistant", "content": text})
        time.sleep(sleep)
        _emit({"type": "result", "status": "success",
               "stats": {"total_tokens": 300, "input_tokens": 250, "output_tokens": 50,
                         "cached": 100, "duration_ms": 900}})


def main() -> int:
    prompt = "" if sys.stdin.isatty() else sys.stdin.read()
    exit_code = int(_per_attempt(json.loads(os.environ.get("NEURICO_FAKE_CLI_EXIT") or "0")))
    _write_requested_files()
    child_pid = None
    if os.environ.get("NEURICO_FAKE_CLI_SPAWN_CHILD") == "1":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        child_pid = child.pid
    _record(prompt, child_pid)
    sys.stderr.write("fake-cli: stderr noise\n")
    sys.stderr.flush()
    _transcript(_provider(), os.environ.get("NEURICO_FAKE_CLI_RESULT_TEXT") or "fake agent reply")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
