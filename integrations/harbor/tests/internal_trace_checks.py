"""Private evidence survives cleanup independently of public publication."""

import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import sys

import pytest

import neurico_harbor_agent.agent as agent_module
from core.hitl_manager_history import HitlManagerHistory
from neurico_harbor_agent.artifacts import TraceRedactor, capture_workspace_baseline
from neurico_harbor_agent.internal_traces import InternalTraceArchive
from neurico_harbor_agent.runtime import CodexInferenceConnection, HarborAutoResearchTask
from neurico_harbor_agent.scratch import EphemeralRunScratch, PrivateOutputSpool


def _archive(tmp_path):
    return InternalTraceArchive.create(tmp_path / "archive", "run", TraceRedactor(("secret-value",)))


def test_private_text_keeps_manager_paths_but_sanitizes_credentials(tmp_path):
    archive = _archive(tmp_path)
    source = tmp_path / "history.jsonl"
    usage = {"input_tokens": 100, "cached_input_tokens": 50,
             "cache_write_input_tokens": 0, "reasoning_output_tokens": 10}
    source.write_text(json.dumps({"path": ".neurico/hitl/manager/context.jsonl",
                                  "input_tokens": 100, "api_key": "secret-value",
                                  "last_token_usage": usage, "thread_token_usage": usage,
                                  "turn_token_usage": usage, "time_to_first_token_ms": 12,
                                  "fallback_token_limit_override": None}) + "\n")
    archive.copy_file(source, Path("provider/history.jsonl"), "provider")
    record = json.loads((archive.directory / "provider/history.jsonl").read_text())
    assert record["path"] == ".neurico/hitl/manager/context.jsonl"
    assert record["input_tokens"] == 100
    assert "secret-value" not in str(record)
    assert archive.files["provider/history.jsonl"]["sanitized"]
    for field in ("last_token_usage", "thread_token_usage", "turn_token_usage"):
        assert record[field] == usage
    assert record["time_to_first_token_ms"] == 12
    assert record["fallback_token_limit_override"] is None
    assert not archive.gaps
    payload = (archive.directory / "provider/history.jsonl").read_bytes()
    assert archive.files["provider/history.jsonl"]["bytes"] == len(payload)
    assert archive.files["provider/history.jsonl"]["sha256"] == sha256(payload).hexdigest()


def test_native_sqlite_survives_and_redaction_does_not_change_live_history(tmp_path):
    archive = _archive(tmp_path)
    manager = tmp_path / "manager"
    history = HitlManagerHistory(manager)
    with sqlite3.connect(history.path) as database:
        database.execute("INSERT INTO conversation_records "
                         "(record_id, record_type, speaker, content, created_at) "
                         "VALUES ('r1', 'message', 'manager', 'secret-value', 'now')")
        database.execute("INSERT INTO conversation_chunks_fts(content) VALUES ('secret-value')")
    with HitlManagerHistory.snapshot_lock(manager):
        archive.copy_file(history.path, Path(".neurico/hitl/manager/history.sqlite"), "research")
    assert not archive.gaps
    copy = archive.directory / ".neurico/hitl/manager/history.sqlite"
    with sqlite3.connect(copy) as database:
        assert database.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert "secret-value" not in database.execute(
            "SELECT content FROM conversation_records").fetchone()[0]
    assert b"secret-value" not in copy.read_bytes()
    with sqlite3.connect(history.path) as database:
        assert database.execute("SELECT content FROM conversation_records").fetchone()[0] == "secret-value"


def test_binary_outputs_and_all_log_roles_are_retained(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    baseline = capture_workspace_baseline(workspace, redactor=TraceRedactor())
    for name in ["manager", "resource_finder", "experiment_runner", "unclassified"]:
        path = workspace / "logs" / f"{name}.jsonl"
        path.parent.mkdir(exist_ok=True)
        path.write_text('{"text":"evidence"}\n')
    binary = b"\x00\x01\xffanalysis output"
    (workspace / "solution.bin").write_bytes(binary)
    (workspace / "logs/auth.json").write_text('{"access_token":"secret-value"}')
    archive = _archive(tmp_path)
    archive.workspace(workspace, baseline)
    assert not archive.gaps
    assert (archive.directory / "solution.bin").read_bytes() == binary
    assert len(list((archive.directory / "logs").glob("*.jsonl"))) == 4
    assert not (archive.directory / "logs/auth.json").exists()


def test_full_spool_ignores_prefix_limit_and_sanitizes_across_read_chunks(tmp_path):
    archive = _archive(tmp_path)
    spool = PrivateOutputSpool.create(max_bytes=None)
    try:
        spool.append_output(b"header .neurico/hitl/manager/context.jsonl\nsecret-")
        spool.append_output(b"value\n-----BEGIN PRIVATE KEY-----\nsecret body\n")
        spool.append_output(b"-----END PRIVATE KEY-----\ntail\n")
        archive.stream(spool)
        text = (archive.directory / "streams/stdout-stderr.log").read_text()
        assert "secret-value" not in text
        assert "secret body" not in text
        assert ".neurico/hitl/manager/context.jsonl" in text
        assert text.endswith("tail\n")
        assert not archive.gaps
    finally:
        spool.close()


def test_spool_can_retain_more_than_old_limit(tmp_path):
    from neurico_harbor_agent.scratch import SCRATCH_MAX_FILE_BYTES
    spool = PrivateOutputSpool.create(max_bytes=None)
    try:
        chunk = (b"x" * 1023 + b"\n") * 1024
        for _ in range(SCRATCH_MAX_FILE_BYTES // len(chunk) + 1):
            assert spool.append_output(chunk)
        assert spool.retained_bytes > SCRATCH_MAX_FILE_BYTES
        assert not spool.truncated
        archive = _archive(tmp_path)
        archive.stream(spool)
        assert not archive.gaps
        assert (archive.directory / "streams/stdout-stderr.log").stat().st_size == spool.retained_bytes
    finally:
        spool.close()


def test_stream_failure_keeps_already_sanitized_prefix(tmp_path, monkeypatch):
    import neurico_harbor_agent.internal_traces as module

    archive = _archive(tmp_path)
    spool = PrivateOutputSpool.create(max_bytes=None)
    try:
        spool.append_output(b"available output\n")

        def interrupted_lines(lines, redactor):
            yield "sanitized prefix\n"
            raise OSError("interrupted read")

        monkeypatch.setattr(module, "_sanitize_free_text_lines", interrupted_lines)
        archive.stream(spool)
        assert (archive.directory / "streams/stdout-stderr.log").read_text() == "sanitized prefix\n"
        assert archive.gaps == [{"source": "streams/stdout-stderr.log", "reason": "OSError"}]
    finally:
        spool.close()


@pytest.mark.parametrize("recover_source", [False, True])
def test_scratch_only_prefix_is_retained_or_recovered(tmp_path, recover_source):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    scratch = EphemeralRunScratch.create(root=tmp_path / "scratch", run_id="run")
    scratch.preserve_workspace_file(Path("analysis.bin"), b"\x00prefix", source_truncated=True)
    scratch.finalize()
    if recover_source:
        (workspace / "analysis.bin").write_bytes(b"\x00prefix-complete")
    archive = _archive(tmp_path)
    archive.scratch(scratch, workspace)
    expected = b"\x00prefix-complete" if recover_source else b"\x00prefix"
    assert (archive.directory / "analysis.bin").read_bytes() == expected
    assert bool(archive.gaps) is not recover_source
    assert (archive.directory / "scratch.json").is_file()


@pytest.mark.parametrize("public_failure", [None, "store", "export"])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_private_collection_survives_public_failure_and_temporary_cleanup(
    tmp_path, monkeypatch, public_failure, exit_code
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    private_root = tmp_path / "internal"
    monkeypatch.setattr(agent_module, "DEFAULT_INTERNAL_TRACE_ROOT", private_root)
    monkeypatch.setattr(agent_module, "DEFAULT_HARBOR_ARTIFACT_ROOT", tmp_path / "public")
    monkeypatch.setattr(agent_module, "DEFAULT_HARBOR_SCRATCH_ROOT", tmp_path / "scratch")
    original_create = asyncio.create_subprocess_exec
    captured = {}

    def fail(*args, **kwargs):
        raise OSError("public export unavailable")

    if public_failure == "store":
        monkeypatch.setattr(agent_module.HarborArtifactStore, "open", fail)
    elif public_failure == "export":
        monkeypatch.setattr(agent_module, "export_harbor_research_artifacts", fail)

    async def create(*args, **kwargs):
        instruction = Path(args[args.index("--instruction-file") + 1])
        captured["control"] = instruction.parent
        assert (private_root / "run").is_dir()  # Created before research starts.
        code = '''
import json, os
from pathlib import Path
ideas = Path(os.environ['NEURICO_IDEAS']) / 'submitted'
ideas.mkdir(parents=True)
(ideas / 'task.yaml').write_text('idea: complete the task\\n')
sessions = Path(os.environ['CODEX_HOME']) / 'sessions'
sessions.mkdir()
events = [
 {'type':'session_meta','payload':{'id':'native-session','cli_version':'0.167.1'}},
 {'type':'turn_context','payload':{'model':'gpt-6-astra','effort':'high'}},
 {'type':'response_item','payload':{'text':'raw provider response'}}]
(sessions / 'run.jsonl').write_text(''.join(json.dumps(e)+'\\n' for e in events))
logs=Path('logs'); logs.mkdir()
(logs/'manager.log').write_text('manager decision\\n')
Path('answer.bin').write_bytes(b'\\x00result')
print('child output secret-value', flush=True)
'''
        return await original_create(sys.executable, "-c", code + f"\nraise SystemExit({exit_code})",
                                     **kwargs)

    monkeypatch.setattr(agent_module.asyncio, "create_subprocess_exec", create)
    auth = tmp_path / "auth.json"
    auth.write_text('{"tokens":{"access_token":"secret-value"}}')
    result = asyncio.run(agent_module.run_autoresearch_process(
        task=HarborAutoResearchTask("Exact task\nFrame\n", workspace),
        connection=CodexInferenceConnection("openai/gpt-6-astra", "chatgpt", auth_file=auth),
        base_environment={**os.environ, "NEURICO_HARBOR_PRESERVE_INTERNAL_TRACES": "1"},
        workflow="focused-managed-ordinary", reasoning_effort="high", iterations=None,
        time_limit_seconds=None, run_id="run", emit=lambda text: asyncio.sleep(0),
        register_process=lambda process: False,
    ))
    assert result == exit_code
    assert not captured["control"].exists()
    archive = private_root / "run"
    manifest = json.loads((archive / "manifest.json").read_text())
    assert manifest["collection_status"] == ("partial" if exit_code == 0 else "complete")
    if exit_code == 0:
        assert manifest["gaps"] == [{"source": "invocations", "reason": "successful_workflow_records_missing"}]
    assert manifest["outcome"] == ("success" if exit_code == 0 else "failed")
    assert (archive / "instruction.txt").read_text() == "Exact task\nFrame\n"
    assert (archive / "idea_registry/submitted/task.yaml").is_file()
    assert (archive / "provider/sessions/run.jsonl").is_file()
    assert (archive / "logs/manager.log").read_text() == "manager decision\n"
    assert (archive / "answer.bin").read_bytes() == b"\x00result"
    assert any(event.get("model") == "gpt-6-astra" for event in manifest["observed_provider_settings"])
    for record in manifest["files"]:
        payload = (archive / record["path"]).read_bytes()
        assert sha256(payload).hexdigest() == record["sha256"]
        assert b"secret-value" not in payload
    assert not (archive / "provider/auth.json").exists()


def test_failed_finalization_leaves_prior_records_intact(tmp_path, monkeypatch):
    archive = _archive(tmp_path)
    source = tmp_path / "plan.md"
    source.write_text("retained plan\n")
    archive.copy_file(source, Path("plans/plan.md"), "research")

    def fail(*args, **kwargs):
        raise OSError("storage unavailable")

    import neurico_harbor_agent.internal_traces as module
    monkeypatch.setattr(module, "_write_json", fail)
    with pytest.raises(OSError):
        archive.finalize(run_id="run", run_configuration={}, outcome="failed", return_code=7)
    assert (archive.directory / "plans/plan.md").read_text() == "retained plan\n"


@pytest.mark.parametrize("failure", ["cancel", "timeout", "stream", "spawn"])
def test_error_paths_stop_and_collect_before_removing_control_sources(tmp_path, monkeypatch, failure):
    from types import SimpleNamespace

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    private_root = tmp_path / "internal"
    monkeypatch.setattr(agent_module, "DEFAULT_INTERNAL_TRACE_ROOT", private_root)
    monkeypatch.setattr(agent_module, "DEFAULT_HARBOR_ARTIFACT_ROOT", tmp_path / "public")
    monkeypatch.setattr(agent_module, "DEFAULT_HARBOR_SCRATCH_ROOT", tmp_path / "scratch")
    monkeypatch.setattr(agent_module, "_COOPERATIVE_SHUTDOWN_GRACE_SECONDS", 0)
    process = SimpleNamespace(returncode=None)
    events = []
    control = None

    async def create(*args, **kwargs):
        nonlocal control
        control = Path(args[args.index("--instruction-file") + 1]).parent
        if failure == "spawn":
            raise OSError("spawn failed")
        return process

    async def drain(target, spool):
        spool.append_output(b"available before failure\n")
        if failure == "stream":
            raise OSError("stream failed")
        while target.returncode is None:
            await asyncio.sleep(0.001)
        return target.returncode

    async def terminate(target, **kwargs):
        assert control.is_dir()
        events.append("stopped")
        target.returncode = 7

    original_collect = InternalTraceArchive.collect

    def collect(archive, **kwargs):
        assert control.is_dir()
        assert failure == "spawn" or process.returncode is not None
        events.append("collected")
        original_collect(archive, **kwargs)

    monkeypatch.setattr(agent_module.asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr(agent_module, "_stream_process_output", drain)
    monkeypatch.setattr(agent_module, "_terminate_process_tree", terminate)
    monkeypatch.setattr(InternalTraceArchive, "collect", collect)

    async def exercise():
        return await agent_module.run_autoresearch_process(
            task=HarborAutoResearchTask("Original instruction", workspace),
            connection=CodexInferenceConnection("test-model", "chatgpt"),
            base_environment={**os.environ, "NEURICO_HARBOR_PRESERVE_INTERNAL_TRACES": "1"},
            iterations=1, time_limit_seconds=0.01 if failure == "timeout" else None,
            run_id="run", emit=lambda text: asyncio.sleep(0),
            register_process=lambda process: failure == "cancel",
        )

    if failure in {"spawn", "stream"}:
        with pytest.raises(OSError):
            asyncio.run(exercise())
    else:
        asyncio.run(exercise())
    assert events == (["collected"] if failure == "spawn" else ["stopped", "collected"])
    assert not control.exists()
    archive = private_root / "run"
    assert (archive / "instruction.txt").read_text() == "Original instruction"
    manifest = json.loads((archive / "manifest.json").read_text())
    assert manifest["finalized"] is True
    if failure != "spawn":
        assert (archive / "streams/stdout-stderr.log").read_text() == "available before failure\n"


def test_private_retention_does_not_treat_harbor_auth_policy_as_credential():
    from neurico_harbor_agent.internal_traces import private_trace_redactor
    environment = {"HARBOR_ACP_AUTH_POLICY": "auto", "OPENAI_API_KEY": "test-secret-value"}
    private = private_trace_redactor(environment)
    assert private.sanitize("autoresearch test-secret-value") == "autoresearch [REDACTED_CONFIGURED_SECRET]"
    # The existing public exporter contract remains unchanged.
    assert "autoresearch" not in TraceRedactor.from_sources(environment).sanitize("autoresearch")
    # A real credential with the same literal value must still be redacted.
    assert private_trace_redactor({**environment, "OPENAI_API_KEY": "auto"}).sanitize("auto").startswith("[REDACTED")


def test_rejected_text_records_check_without_payload(tmp_path, monkeypatch):
    import neurico_harbor_agent.internal_traces as module

    archive = _archive(tmp_path)
    source = tmp_path / "context.jsonl"
    source.write_text('{"content":"private research"}\n')
    monkeypatch.setattr(module, "_safe_text_payload", lambda *a, **k: None)
    monkeypatch.setattr(module, "_sanitize_trace_text", lambda *a, **k: "secret-value")
    archive.copy_file(source, Path("context.jsonl"), "research")
    assert archive.gaps == [{"source": "context.jsonl", "reason":
                             "text_sanitization_rejected:secret_value_remaining"},
                            {"source": "context.jsonl", "reason":
                             "secret_value_remaining@sanitized-line-1"}]
    assert "secret-value" not in json.dumps(archive.gaps)
    assert not (archive.directory / "context.jsonl").exists()


def test_binary_rejection_has_specific_safe_reason(tmp_path):
    archive = _archive(tmp_path)
    source = tmp_path / "output.bin"
    source.write_bytes(b"\x00secret-value")
    archive.copy_file(source, Path("output.bin"), "research")
    assert archive.gaps == [{"source": "output.bin", "reason": "binary_credential_detected"}]
    assert not (archive.directory / "output.bin").exists()


def test_rejection_locations_do_not_disclose_keys_or_values():
    from neurico_harbor_agent.internal_traces import _rejection_locations
    text = '{}\n' + json.dumps({"private-key-name": ["fine", "secret-value"]})
    locations = _rejection_locations(text, lambda value: "secret-value" in value)
    assert locations == ["sanitized-line-2/member-0/value/item-1"]
    assert "private-key-name" not in str(locations)
    assert "secret-value" not in str(locations)


def test_nested_manager_code_result_is_retained(tmp_path):
    archive = _archive(tmp_path)
    source = tmp_path / 'context.jsonl'
    record = {'output': {'content': json.dumps({'content':
        '    15\ttokens = re.findall(pattern, text)\n    16\tassert tokens'})}}
    source.write_text(json.dumps(record) + '\n' + json.dumps({'input_tokens': 123}) + '\n')
    archive.copy_file(source, Path('context.jsonl'), 'research')
    records = [json.loads(line) for line in (archive.directory / 'context.jsonl').read_text().splitlines()]
    content = json.loads(records[0]['output']['content'])['content']
    assert 'assert tokens' in content
    assert '[REDACTED_SECRET_FIELD]' in content
    assert records[1]['input_tokens'] == 123
    assert not archive.gaps


@pytest.mark.parametrize('payload', [
    {'content': '    15\taccess_token = opaque-example-credential\n'},
    {'access_token': 'opaque-example-credential'},
    {'content': 'Known credential: secret-value'},
    {'content': 'Authorization: Bearer opaque-example-credential'},
])
def test_nested_manager_credentials_are_removed(tmp_path, payload):
    archive = _archive(tmp_path)
    source = tmp_path / 'context.jsonl'
    source.write_text(json.dumps({'content': json.dumps({'result': json.dumps(payload)})}) + '\n')
    archive.copy_file(source, Path('context.jsonl'), 'research')
    retained = (archive.directory / 'context.jsonl').read_text()
    assert 'opaque-example-credential' not in retained
    assert 'secret-value' not in retained
    assert not archive.gaps


def test_nested_credential_left_by_sanitizer_is_rejected(tmp_path, monkeypatch):
    from neurico_harbor_agent import artifacts
    from neurico_harbor_agent import internal_traces
    archive = _archive(tmp_path)
    source = tmp_path / 'context.jsonl'
    source.write_text(json.dumps({'content': json.dumps({'access_token': 'opaque-example-credential'})}) + '\n')
    monkeypatch.setattr(artifacts, '_sanitize_trace_text', lambda text, *args, **kwargs: text)
    monkeypatch.setattr(internal_traces, '_sanitize_trace_text', lambda text, *args, **kwargs: text)
    archive.copy_file(source, Path('context.jsonl'), 'research')
    assert not (archive.directory / 'context.jsonl').exists()
    assert any('sensitive_material_remaining' in gap['reason'] for gap in archive.gaps)
    assert 'opaque-example-credential' not in json.dumps(archive.gaps)


@pytest.mark.parametrize('text', ['ordinary text', '{invalid JSON', 'startup notice\n{"input_tokens": 10}\n'])
def test_non_json_strings_keep_existing_fallback(text):
    from neurico_harbor_agent import artifacts
    redactor = TraceRedactor(('secret-value',))
    assert artifacts._sanitize_serializable(text, redactor=redactor) == artifacts._sanitize_free_text(text, redactor)
