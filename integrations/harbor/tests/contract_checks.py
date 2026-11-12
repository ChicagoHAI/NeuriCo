import asyncio
from hashlib import sha256
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import neurico_harbor_agent.agent as agent_module
import neurico_harbor_agent.artifacts as artifacts_module
import neurico_harbor_agent.run_autoresearch as runner_module
import pytest
from acp import PROTOCOL_VERSION, RequestError, spawn_agent_process
from acp.interfaces import Client
from neurico_harbor_agent.agent import (
    NeuricoHarborAgent,
    _autoresearch_iterations,
    _autoresearch_time_limit,
    run_autoresearch_process,
    _stream_process_output,
    _terminate_process_tree,
    _text_from_prompt,
)
from neurico_harbor_agent.run_autoresearch import execute_autoresearch
from neurico_harbor_agent.artifacts import (
    HarborArtifactStore,
    TraceRedactor,
    capture_workspace_baseline,
    capture_workspace_snapshot,
    export_harbor_research_artifacts,
)
from neurico_harbor_agent.runtime import (
    CodexInferenceConnection,
    HarborAutoResearchTask,
    build_autoresearch_environment,
    build_harbor_idea,
)
from neurico_harbor_agent.scratch import EphemeralRunScratch


@pytest.fixture(autouse=True)
def _isolate_private_trace_scratch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        agent_module,
        "DEFAULT_HARBOR_SCRATCH_ROOT",
        tmp_path / "private-trace-scratch",
    )


def test_prompt_text_is_preserved_verbatim() -> None:
    instruction = "First line\n\n  indented line with : and #\n"
    assert _text_from_prompt([{"type": "text", "text": instruction}]) == instruction


def test_trace_runs_get_exclusive_directories(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    store = HarborArtifactStore.open(root)
    first_transaction = store.begin("session-a-run-1")
    assert not first_transaction.final_dir.exists()
    assert list(root.iterdir()) == []
    assert first_transaction.staging_dir.parent == tmp_path / ".artifacts.transactions"
    assert first_transaction.staging_dir.is_dir()
    (first_transaction.staging_dir / "partial.txt").write_text(
        "not yet published\n",
        encoding="utf-8",
    )
    assert list(root.iterdir()) == []
    first = first_transaction.commit()
    second = store.begin("session-a-run-2").commit()

    assert first != second
    assert first.parent == second.parent == root
    assert sorted(path.name for path in root.iterdir()) == [
        "session-a-run-1",
        "session-a-run-2",
    ]
    assert first.stat().st_mode & 0o777 == 0o700
    pending = store.begin("session-a-run-3")
    assert sorted(path.name for path in root.iterdir()) == [
        "session-a-run-1",
        "session-a-run-2",
    ]
    with pytest.raises(FileExistsError):
        store.begin("session-a-run-3")
    pending.abort()
    with pytest.raises(FileExistsError):
        store.begin("session-a-run-1")
    with pytest.raises(ValueError):
        store.begin("../escape")
    store.close()
    transaction_root = tmp_path / ".artifacts.transactions"
    assert transaction_root.is_dir()
    assert list(transaction_root.iterdir()) == []


def test_closing_one_trace_store_does_not_break_a_concurrent_store(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    first_store = HarborArtifactStore.open(root)
    second_store = HarborArtifactStore.open(root)

    first_store.close()
    published = second_store.begin("parallel-run").commit()
    second_store.close()

    assert published.is_dir()
    assert (tmp_path / ".artifacts.transactions").is_dir()


def test_trace_store_rejects_symlinked_storage_roots(tmp_path: Path) -> None:
    redirected = tmp_path / "redirected"
    redirected.mkdir()
    root = tmp_path / "artifacts"
    root.symlink_to(redirected, target_is_directory=True)

    with pytest.raises(OSError):
        HarborArtifactStore.open(root)
    assert list(redirected.iterdir()) == []

    root.unlink()
    root.mkdir()
    transaction_root = tmp_path / ".artifacts.transactions"
    transaction_root.symlink_to(redirected, target_is_directory=True)
    with pytest.raises(OSError):
        HarborArtifactStore.open(root)
    assert list(redirected.iterdir()) == []


def test_trace_store_rejects_root_replaced_during_child_run(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    store = HarborArtifactStore.open(root)
    original_root = tmp_path / "original-artifacts"
    redirected = tmp_path / "redirected"
    redirected.mkdir()
    root.rename(original_root)
    root.symlink_to(redirected, target_is_directory=True)

    with pytest.raises(OSError, match="changed|replaced"):
        store.begin("probe-run")
    assert not (redirected / "probe-run").exists()
    store.close()


def test_artifact_file_write_never_replaces_complete_file_with_partial_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "metadata.json"
    destination.write_text("previous-complete-record\n", encoding="utf-8")

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("simulated publish failure")

    monkeypatch.setattr(artifacts_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated publish failure"):
        artifacts_module._write_sanitized_text(
            destination,
            '{"new": "complete record"}\n',
            redactor=TraceRedactor(),
            suffix=".json",
        )

    assert destination.read_text(encoding="utf-8") == "previous-complete-record\n"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["metadata.json"]


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ("unattested file\n", "unexpected artifact"),
        ("configured-secret=abc123\n", "changed after sanitization"),
        ("harmless-looking replacement\n", "parent write ledger"),
    ],
)
def test_manifest_rejects_unowned_or_post_sanitization_payloads(
    tmp_path: Path,
    payload: str,
    error: str,
) -> None:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    redactor = TraceRedactor.from_sources({"SHORT_API_KEY": "abc123"})
    (artifact_dir / "run.json").write_text("{}\n", encoding="utf-8")
    if "unattested" in payload:
        (artifact_dir / "injected.txt").write_text(payload, encoding="utf-8")
    else:
        (artifact_dir / "run.json").write_text(payload, encoding="utf-8")

    with pytest.raises((OSError, ValueError), match=error):
        artifacts_module._write_manifest(
            artifact_dir,
            run_id="test-run",
            redactor=redactor,
            collection_status="scope_complete",
            expected_hashes={"run.json": sha256(b"{}\n").hexdigest()},
        )


def test_manifest_rejects_missing_expected_artifacts(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "run.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(OSError, match="missing an expected artifact"):
        artifacts_module._write_manifest(
            artifact_dir,
            run_id="test-run",
            redactor=TraceRedactor(),
            collection_status="scope_complete",
            expected_hashes={
                "run.json": sha256(b"{}\n").hexdigest(),
                "missing.json": sha256(b"{}\n").hexdigest(),
            },
        )


def test_trace_redactor_covers_unlabelled_secret_forms() -> None:
    database_url = "postgresql://alice:opaque-db-password@example.invalid/research"
    web_url = "https://bob:opaque-web-password@example.invalid/private"
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ."
        "opaque-signature-material"
    )
    redactor = TraceRedactor.from_sources({"DATABASE_URL": database_url})
    safe_payload = artifacts_module._safe_text_payload(
        f"database={database_url}\nfetch={web_url}\nidentity={jwt}\n".encode(),
        ".log",
        redactor,
    )

    assert database_url in redactor.exact_values
    assert safe_payload is not None
    rendered = safe_payload[0].decode()
    assert database_url not in rendered
    assert "opaque-db-password" not in rendered
    assert "opaque-web-password" not in rendered
    assert jwt not in rendered
    assert "REDACTED_CONFIGURED_SECRET" in rendered
    assert "REDACTED_URI_CREDENTIALS" in rendered
    assert "REDACTED_JSON_WEB_TOKEN" in rendered


@pytest.mark.parametrize(
    ("payload", "suffix", "secret"),
    [
        ('{"apiKey":"opaque-camel-api-value"}\n', ".json", "opaque-camel-api-value"),
        (
            '{"accessToken":"opaque-camel-access-value"}\n',
            ".jsonl",
            "opaque-camel-access-value",
        ),
        ("clientSecret: opaque-camel-client-value\n", ".yaml", "opaque-camel-client-value"),
        (
            "AWSSecretAccessKey=opaque-pascal-aws-value\n",
            ".log",
            "opaque-pascal-aws-value",
        ),
        ('{"apikey":"opaque-compact-api-value"}\n', ".json", "opaque-compact-api-value"),
        (
            '{"accesstoken":"opaque-compact-access-value"}\n',
            ".jsonl",
            "opaque-compact-access-value",
        ),
        (
            "clientsecret: opaque-compact-client-value\n",
            ".yaml",
            "opaque-compact-client-value",
        ),
        (
            "privatekey=opaque-compact-private-value\n",
            ".log",
            "opaque-compact-private-value",
        ),
        (
            '{"openaiapikey":"opaque-prefixed-api-value"}\n',
            ".json",
            "opaque-prefixed-api-value",
        ),
        (
            "openai_apikey=opaque-prefixed-token-value\n",
            ".log",
            "opaque-prefixed-token-value",
        ),
        (
            "apikey_primary: opaque-suffixed-api-value\n",
            ".yaml",
            "opaque-suffixed-api-value",
        ),
        (
            '{"openaiApiKeyCount":"opaque-credential-metadata-value"}\n',
            ".json",
            "opaque-credential-metadata-value",
        ),
        (
            '{"github_token_count":"opaque-prefixed-token-count-value"}\n',
            ".json",
            "opaque-prefixed-token-count-value",
        ),
        ('{"dbpassword":"opaque-db-password"}\n', ".json", "opaque-db-password"),
        (
            "servicecredential: opaque-service-credential\n",
            ".yaml",
            "opaque-service-credential",
        ),
        ("appsecret=opaque-app-secret\n", ".log", "opaque-app-secret"),
        ('{"githubtoken":"opaque-github-token"}\n', ".json", "opaque-github-token"),
        ("sessioncookie: opaque-session-cookie\n", ".yaml", "opaque-session-cookie"),
        (
            "requestauthorization=opaque-request-authorization\n",
            ".log",
            "opaque-request-authorization",
        ),
    ],
)
def test_trace_redactor_covers_common_sensitive_field_styles(
    payload: str,
    suffix: str,
    secret: str,
) -> None:
    safe_payload = artifacts_module._safe_text_payload(
        payload.encode("utf-8"),
        suffix,
        TraceRedactor(),
    )

    assert safe_payload is not None
    rendered = safe_payload[0].decode("utf-8")
    assert secret not in rendered
    assert "REDACTED_SECRET_FIELD" in rendered


def test_harmless_metadata_fields_remain_public() -> None:
    payload = (
        '{"tokenCount":17,"tokenBudget":100,"tokencount":23,'
        '"api_request_count":29,"monkeyCount":31,"secretary_count":37,'
        '"input_tokens_used":41,"passwordless":true,"credentialing":"active",'
        '"cookiecutter":"template","author":"Ada","compat":"ok"}\n'
    )
    safe_payload = artifacts_module._safe_text_payload(
        payload.encode("utf-8"),
        ".json",
        TraceRedactor(),
    )

    assert safe_payload is not None
    rendered = json.loads(safe_payload[0])
    assert rendered == {
        "api_request_count": 29,
        "author": "Ada",
        "compat": "ok",
        "cookiecutter": "template",
        "credentialing": "active",
        "input_tokens_used": 41,
        "monkeyCount": 31,
        "passwordless": True,
        "secretary_count": 37,
        "tokenBudget": 100,
        "tokenCount": 17,
        "tokencount": 23,
    }


def test_trace_redactor_covers_short_configured_secrets_and_fails_closed_below_limit() -> None:
    redactor = TraceRedactor.from_sources(
        {"SHORT_API_KEY": "abc123"},
        additional_values=("tok456",),
    )
    rendered = redactor.sanitize("first=abc123 second=tok456 public=ok")

    assert "abc123" not in rendered
    assert "tok456" not in rendered
    assert "public=ok" in rendered
    with pytest.raises(ValueError, match="too short"):
        TraceRedactor.from_sources({"SHORT_API_KEY": "xyz"})


def test_trace_redactor_covers_values_nested_beneath_credential_containers(
    tmp_path: Path,
) -> None:
    credential_file = tmp_path / "auth.json"
    credential_file.write_text(
        json.dumps({"tokens": {"default": "opaque-nested-credential"}}),
        encoding="utf-8",
    )

    redactor = TraceRedactor.from_sources({}, credential_file=credential_file)

    assert "opaque-nested-credential" in redactor.exact_values
    assert "opaque-nested-credential" not in redactor.sanitize(
        "unlabelled=opaque-nested-credential"
    )


def test_trace_redactor_withholds_sensitive_path_references() -> None:
    redactor = TraceRedactor()
    payload = {
        "command": "find . -type f",
        "./data/.test/secret-index.json": "sealed-name-metadata",
        "aggregated_output": "\n".join(
            (
                "./.env",
                "./.envrc",
                "./.direnv/environment",
                "./.neurico/pipeline_state.json",
                "./data/.test/answers.txt",
                "./scoring/eval.py",
                "./README.md",
                "./logs/resource_finder_codex.log",
            )
        ),
    }
    safe_payload = artifacts_module._safe_text_payload(
        (json.dumps(payload) + "\n").encode(),
        ".jsonl",
        redactor,
    )

    assert safe_payload is not None
    rendered = safe_payload[0].decode()
    for sensitive_path in (
        ".env",
        ".envrc",
        ".direnv",
        ".neurico",
        "data/.test",
        "scoring/eval.py",
        "secret-index.json",
        "sealed-name-metadata",
    ):
        assert sensitive_path not in rendered
    assert rendered.count("REDACTED_SENSITIVE_PATH") == 6
    assert "./README.md" in rendered
    assert "./logs/resource_finder_codex.log" in rendered


def test_harbor_instruction_uses_neurico_idea_contract(tmp_path: Path) -> None:
    instruction = "# Compare cache policies\n\nTest LRU and LFU on the supplied workload.\n"
    task = HarborAutoResearchTask(instruction=instruction, workspace=tmp_path)
    result = build_harbor_idea(task)
    idea = result["idea"]

    assert idea["title"] == "Compare cache policies"
    assert idea["background"]["description"] == instruction
    assert idea["hypothesis"].startswith("# Compare cache policies")
    assert idea["metadata"]["source"] == "harbor"
    assert idea["metadata"]["local_workspace"] == str(tmp_path)
    assert len(idea["metadata"]["instruction_sha256"]) == 64


def test_hosted_gateway_uses_neutral_credential_and_full_model(tmp_path: Path) -> None:
    connection = CodexInferenceConnection.from_environment(
        {
            "HOSTED_INFERENCE_TOKEN": "secret",
            "HOSTED_INFERENCE_URL": "https://gateway.example/v1",
        },
        requested_model="openrouter/example/model",
    )
    assert connection.backend_model == "openrouter/example/model"
    environment = connection.prepare_codex_home(tmp_path / "codex-home")
    config = (tmp_path / "codex-home" / "config.toml").read_text()
    assert environment["HOSTED_INFERENCE_TOKEN"] == "secret"
    assert 'model = "openrouter/example/model"' in config
    assert 'base_url = "https://gateway.example/v1"' in config
    assert 'env_key = "HOSTED_INFERENCE_TOKEN"' in config
    assert "secret" not in config


def test_chatgpt_auth_mode_strips_openai_provider_prefix(tmp_path: Path) -> None:
    auth_file = tmp_path / "mounted-auth.json"
    auth_file.write_text('{"tokens": {}}')
    connection = CodexInferenceConnection.from_environment(
        {"NEURICO_CODEX_AUTH_FILE": str(auth_file)},
        requested_model="openai/gpt-5.6-sol",
    )
    assert connection.mode == "chatgpt"
    assert connection.backend_model == "gpt-5.6-sol"


def test_direct_non_openai_model_is_rejected(tmp_path: Path) -> None:
    auth_file = tmp_path / "mounted-auth.json"
    auth_file.write_text('{"tokens": {}}')
    with pytest.raises(ValueError, match="requires an OpenAI model"):
        CodexInferenceConnection.from_environment(
            {"NEURICO_CODEX_AUTH_FILE": str(auth_file)},
            requested_model="anthropic/claude-sonnet-5",
        )


def test_environment_exposes_locked_codex_and_isolated_home(tmp_path: Path) -> None:
    auth_file = tmp_path / "mounted-auth.json"
    auth_file.write_text('{"tokens": {}}')
    connection = CodexInferenceConnection(
        requested_model="openai/test-model",
        mode="chatgpt",
        auth_file=auth_file,
    )
    ideas_dir = tmp_path / "control" / "ideas"
    codex_home = tmp_path / "control" / "codex-home"
    environment = build_autoresearch_environment(
        {"PATH": "/usr/bin"},
        connection,
        ideas_dir=ideas_dir,
        codex_home=codex_home,
    )
    assert environment["NEURICO_IDEAS"] == str(ideas_dir)
    assert environment["CODEX_HOME"] == str(codex_home)
    assert (codex_home / "auth.json").read_text() == '{"tokens": {}}'
    assert 'model = "test-model"' in (codex_home / "config.toml").read_text()
    first_path = Path(environment["PATH"].split(os.pathsep)[0])
    assert (first_path / "codex").is_file()


def test_iteration_override_must_be_positive() -> None:
    assert _autoresearch_iterations({}) == 1
    assert _autoresearch_iterations({"NEURICO_HARBOR_AUTORESEARCH_ITERATIONS": "3"}) == 3
    with pytest.raises(ValueError, match="at least 1"):
        _autoresearch_iterations({"NEURICO_HARBOR_AUTORESEARCH_ITERATIONS": "0"})


def test_time_limit_override_is_optional_and_positive() -> None:
    assert _autoresearch_time_limit({}) is None
    assert _autoresearch_time_limit({"NEURICO_HARBOR_TIME_LIMIT_SECONDS": "1740"}) == 1740
    with pytest.raises(ValueError, match="positive integer"):
        _autoresearch_time_limit({"NEURICO_HARBOR_TIME_LIMIT_SECONDS": "0"})
    with pytest.raises(ValueError, match="positive integer"):
        _autoresearch_time_limit({"NEURICO_HARBOR_TIME_LIMIT_SECONDS": "1.5"})
    with pytest.raises(ValueError, match="positive integer"):
        _autoresearch_time_limit({"NEURICO_HARBOR_TIME_LIMIT_SECONDS": "later"})


def test_cancellation_requests_native_stop_and_terminates_detached_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        child_pid_file = tmp_path / "provider.pid"
        stop_file = tmp_path / "native-stop-requested"
        script = tmp_path / "process_tree.py"
        script.write_text(
            "\n".join(
                [
                    "import signal",
                    "import subprocess",
                    "import sys",
                    "import time",
                    "from pathlib import Path",
                    f"child_pid_file = Path({str(child_pid_file)!r})",
                    f"stop_file = Path({str(stop_file)!r})",
                    "provider = subprocess.Popen(",
                    "    [sys.executable, '-c', 'import time; time.sleep(30)'],",
                    "    start_new_session=True,",
                    ")",
                    "child_pid_file.write_text(str(provider.pid))",
                    "signal.signal(signal.SIGINT, lambda *_args: stop_file.write_text('yes'))",
                    "while True:",
                    "    time.sleep(1)",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(script),
            start_new_session=True,
        )
        deadline = time.monotonic() + 5
        while not child_pid_file.is_file():
            if time.monotonic() >= deadline:
                process.kill()
                await process.wait()
                raise AssertionError("Detached provider did not start")
            await asyncio.sleep(0.01)
        provider_pid = int(child_pid_file.read_text())

        monkeypatch.setattr(agent_module, "_CANCELLATION_GRACE_SECONDS", 0.1)
        monkeypatch.setattr(agent_module, "_FORCED_TERMINATION_GRACE_SECONDS", 0.1)
        await _terminate_process_tree(process, request_cooperative_stop=True)

        assert process.returncode is not None
        assert stop_file.read_text() == "yes"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = subprocess.run(
                ["ps", "-p", str(provider_pid), "-o", "stat="],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            if not status or status.startswith("Z"):
                break
            await asyncio.sleep(0.05)
        else:
            os.killpg(provider_pid, 9)
            raise AssertionError("Detached provider survived Harbor cancellation")

    asyncio.run(exercise())


@pytest.mark.skipif(sys.platform != "linux", reason="child subreapers are Linux-specific")
@pytest.mark.parametrize("shutdown", ["cooperative", "forced", "hard_timeout"])
def test_cancellation_retains_provider_started_during_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shutdown: str
) -> None:
    async def exercise() -> None:
        ready_file = tmp_path / "worker.ready"
        provider_pid_file = tmp_path / "provider.pid"
        worker_script = tmp_path / "worker.py"
        worker_script.write_text(
            "\n".join(
                [
                    "import os, signal, subprocess, sys, time",
                    "from pathlib import Path",
                    f"ready_file = Path({str(ready_file)!r})",
                    f"provider_pid_file = Path({str(provider_pid_file)!r})",
                    f"shutdown = {shutdown!r}",
                    "def launch_provider():",
                    "    provider = subprocess.Popen(",
                    "        [sys.executable, '-c',",
                    "         'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'],",
                    "        start_new_session=True,",
                    "        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,",
                    "    )",
                    "    provider_pid_file.write_text(str(provider.pid))",
                    "def interrupt(*_args):",
                    "    launch_provider()",
                    "    if shutdown == 'cooperative':",
                    "        os._exit(0)",
                    "    signal.signal(signal.SIGTERM, signal.SIG_IGN)",
                    "def terminate(*_args):",
                    "    launch_provider()",
                    "    os._exit(0)",
                    "signal.signal(signal.SIGINT, interrupt)",
                    "signal.signal(signal.SIGTERM, terminate)",
                    "ready_file.write_text('yes')",
                    "while True: time.sleep(0.01)",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "neurico_harbor_agent.process_control",
            sys.executable,
            str(worker_script),
            start_new_session=True,
        )
        provider_pid = None
        try:
            deadline = time.monotonic() + 5
            while not ready_file.is_file():
                assert process.returncode is None, "Supervisor exited before worker startup"
                if time.monotonic() >= deadline:
                    raise AssertionError("Worker did not become ready")
                await asyncio.sleep(0.01)
            # Every provider starts in a signal handler, after the adapter's
            # initial ownership snapshot. The cooperative case immediately
            # exits its parent; the forced case keeps the manager stuck alive.
            monkeypatch.setattr(agent_module, "_CANCELLATION_GRACE_SECONDS", 0.2)
            await asyncio.wait_for(
                _terminate_process_tree(
                    process,
                    request_cooperative_stop=shutdown != "hard_timeout",
                ),
                timeout=10,
            )
            assert process.returncode is not None
            provider_pid = int(provider_pid_file.read_text())
            with pytest.raises(ProcessLookupError):
                os.kill(provider_pid, 0)
        finally:
            if process.returncode is None:
                await _terminate_process_tree(process)
            if provider_pid_file.is_file():
                provider_pid = int(provider_pid_file.read_text())
                try:
                    os.killpg(provider_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    asyncio.run(exercise())


@pytest.mark.skipif(sys.platform != "linux", reason="child subreapers are Linux-specific")
@pytest.mark.parametrize("exit_code", [1, 10])
def test_supervisor_preserves_manager_failure_and_reaps_orphans(
    tmp_path: Path, exit_code: int
) -> None:
    provider_pid_file = tmp_path / "provider.pid"
    code = (
        "import os, subprocess, sys; from pathlib import Path; "
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], "
        "start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        f"Path({str(provider_pid_file)!r}).write_text(str(p.pid)); os._exit({exit_code})"
    )
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "neurico_harbor_agent.process_control",
                sys.executable,
                "-c",
                code,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == exit_code, result.stderr
        provider_pid = int(provider_pid_file.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(provider_pid, 0)
    finally:
        if provider_pid_file.is_file():
            try:
                os.killpg(int(provider_pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.skipif(sys.platform != "linux", reason="child subreapers are Linux-specific")
@pytest.mark.parametrize("exit_code", [0, 124])
def test_supervisor_preserves_task_service_after_success(tmp_path: Path, exit_code: int) -> None:
    service_pid_file = tmp_path / "service.pid"
    code = (
        "import os, subprocess, sys; from pathlib import Path; "
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], "
        "start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        f"Path({str(service_pid_file)!r}).write_text(str(p.pid)); os._exit({exit_code})"
    )
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "neurico_harbor_agent.process_control",
                sys.executable,
                "-c",
                code,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == exit_code, result.stderr
        service_pid = int(service_pid_file.read_text())
        os.kill(service_pid, 0)
    finally:
        if service_pid_file.is_file():
            try:
                os.killpg(int(service_pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_cancellation_during_child_spawn_is_honored_after_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        monkeypatch.setattr(
            agent_module,
            "DEFAULT_HARBOR_ARTIFACT_ROOT",
            tmp_path / "artifacts",
        )
        auth_file = tmp_path / "auth.json"
        auth_file.write_text('{"tokens": {}}')
        spawn_started = asyncio.Event()
        allow_spawn = asyncio.Event()
        spawned_process: asyncio.subprocess.Process | None = None
        create_subprocess_exec = asyncio.create_subprocess_exec

        async def delayed_create_subprocess_exec(*_args: Any, **kwargs: Any):
            nonlocal spawned_process
            spawn_started.set()
            await allow_spawn.wait()
            spawned_process = await create_subprocess_exec(
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
                cwd=kwargs["cwd"],
                env=kwargs["env"],
                stdout=kwargs["stdout"],
                stderr=kwargs["stderr"],
                start_new_session=kwargs["start_new_session"],
            )
            return spawned_process

        monkeypatch.setattr(
            agent_module.asyncio,
            "create_subprocess_exec",
            delayed_create_subprocess_exec,
        )
        agent = NeuricoHarborAgent(
            {
                "NEURICO_MODEL": "openai/test-model",
                "NEURICO_CODEX_AUTH_FILE": str(auth_file),
            }
        )
        session = await agent.new_session(cwd=str(tmp_path), mcp_servers=[])
        prompt_task = asyncio.create_task(
            agent.prompt(
                session_id=session.session_id,
                prompt=[{"type": "text", "text": "Run this benchmark"}],
            )
        )

        await asyncio.wait_for(spawn_started.wait(), timeout=5)
        assert (tmp_path / "artifacts").is_dir()
        assert list((tmp_path / "artifacts").iterdir()) == []
        await agent.cancel(session.session_id)
        allow_spawn.set()
        response = await asyncio.wait_for(prompt_task, timeout=5)

        assert response.stop_reason == "cancelled"
        assert spawned_process is not None
        assert spawned_process.returncode is not None
        run_directories = list((tmp_path / "artifacts").iterdir())
        assert len(run_directories) == 1
        run_record = json.loads((run_directories[0] / "run.json").read_text())
        assert run_record["outcome"] == "cancelled"

    asyncio.run(exercise())


def test_child_output_stream_drains_large_events_without_forwarding_payload() -> None:
    async def exercise() -> None:
        payload_size = 200_000
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            f"import sys; sys.stdout.write('x' * {payload_size})",
            stdout=asyncio.subprocess.PIPE,
        )
        return_code = await _stream_process_output(process)
        assert return_code == 0

    asyncio.run(exercise())


def test_private_scratch_failure_cannot_interrupt_child_output_drain() -> None:
    class FailingOutputSpool:
        def append_output(self, _payload: bytes) -> None:
            raise OSError("scratch unavailable")

    async def exercise() -> None:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('research output'); raise SystemExit(7)",
            stdout=asyncio.subprocess.PIPE,
        )
        return_code = await _stream_process_output(  # type: ignore[arg-type]
            process,
            FailingOutputSpool(),
        )
        assert return_code == 7

    asyncio.run(exercise())


def test_child_entrypoint_invokes_manager_driven_auto_hitl_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class FakeManager:
        def __init__(self, ideas_dir: Path):
            captured["ideas_dir"] = ideas_dir

        def submit_idea(self, idea: dict[str, Any], validate: bool) -> str:
            captured["idea"] = idea
            captured["validate"] = validate
            return "harbor-idea"

    class FakeRunner:
        def __init__(self, *, use_github: bool):
            captured["use_github"] = use_github

        def run_research(self, **kwargs: Any) -> dict[str, Any]:
            captured["run"] = kwargs
            return {"success": True, "work_dir": str(tmp_path)}

    monkeypatch.setattr(runner_module, "IdeaManager", FakeManager)
    monkeypatch.setattr(runner_module, "ResearchRunner", FakeRunner)

    result = execute_autoresearch(
        instruction="Investigate whether the supplied cache can reduce tail latency.",
        workspace=tmp_path,
        ideas_dir=tmp_path / "ideas",
        iterations=2,
        time_limit_seconds=1740,
    )

    assert result["success"] is True
    assert captured["validate"] is True
    assert captured["use_github"] is False
    assert captured["idea"]["idea"]["metadata"]["local_workspace"] == str(tmp_path)
    assert captured["run"] == {
        "idea_id": "harbor-idea",
        "provider": "codex",
        "full_permissions": True,
        "multi_agent": True,
        "use_scribe": False,
        "write_paper": False,
        "scoring_enabled": True,
        "benchmark_mode": True,
        "hitl_autoresearch": "cli",
        "hitl_manager_no_browser": True,
        "hitl_mode": "auto",
        "autoresearch_iterations": 2,
        "time_limit_seconds": 1740,
        "workspace_mode": "embedded",
    }
    assert "autoresearch" not in captured["run"]


def test_trace_export_preserves_research_records_and_excludes_live_secrets(
    tmp_path: Path,
) -> None:
    unrelated_environment_secret = "unrelated-environment-secret-value"
    mounted_auth_secret = "opaque-mounted-auth-value-without-provider-prefix"
    connection_secret = "opaque-hosted-connection-value-without-provider-prefix"
    auth_file = tmp_path / "mounted-auth.json"
    auth_file.write_text(
        json.dumps({"tokens": {"access_token": mounted_auth_secret}}),
        encoding="utf-8",
    )
    redactor = TraceRedactor.from_sources(
        {"UNRELATED_SECRET_TOKEN": unrelated_environment_secret},
        credential_file=auth_file,
        additional_values=(connection_secret,),
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    preexisting_marker = "SUPPLIED-BENCHMARK-FUNCTION-DO-NOT-EXPORT"
    (workspace / "benchmark_fixture.py").write_text(
        f"# {preexisting_marker}\n",
        encoding="utf-8",
    )
    baseline = capture_workspace_baseline(workspace, redactor=redactor)
    logs = workspace / "logs"
    logs.mkdir()
    (logs / "experiment_runner_codex_transcript.jsonl").write_text(
        json.dumps(
            {
                "message": "OPENAI_API_KEY=definitely-secret-value",
                "OPENAI_API_KEY": "opaque-json-secret",
                "client_secret": "opaque-client-secret",
                "token_count": 17,
                "mounted_value": mounted_auth_secret,
                "connection_value": connection_secret,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (logs / "experiment_runner_config.yaml").write_text(
        "AWS_SECRET_ACCESS_KEY: opaque-yaml-secret\n"
        "client_secret=second-client-secret\n"
        'prefix private_key="opaque inline secret with spaces"\n'
        "method=GET request headers Authorization: Bearer opaque-inline-bearer-secret\n"
        "private_key: |\n"
        "  -----BEGIN PRIVATE KEY-----\n"
        "  opaque-private-key-block\n"
        "  -----END PRIVATE KEY-----\n"
        "api_key:\n"
        "  opaque-indented-api-key\n"
        "Bearer opaque-unconfigured-bearer-secret\n"
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "opaque-bare-private-key\n"
        "-----END OPENSSH PRIVATE KEY-----\n"
        "public_note: keep-this-public-note\n",
        encoding="utf-8",
    )
    dsi_logs = logs / "dsi-slurm-artifacts" / "123"
    dsi_logs.mkdir(parents=True)
    (dsi_logs / "slurm_123.out").write_text("public cluster stdout\n", encoding="utf-8")
    (dsi_logs / "slurm_123.err").write_text("public cluster stderr\n", encoding="utf-8")
    (dsi_logs / "job.json").write_text(
        '{"job_id":"123","status":"completed"}\n',
        encoding="utf-8",
    )
    modal_log = logs / "modal_lora-train_20261109_120000.log"
    modal_log.write_text("public Modal training trace\n", encoding="utf-8")
    (logs / "auth.json").write_text('{"token":"arbitrary-mounted-secret"}\n')
    (logs / "experiment_runner_binary.bin").write_bytes(b"\x00opaque-binary-credential\xff")
    secret_named_log = logs / f"experiment_runner_{mounted_auth_secret}.log"
    secret_named_log.write_text("path must also be withheld\n", encoding="utf-8")
    (workspace / ".envrc").write_text(
        "export DATABASE_URL=postgresql://alice:opaque-direnv-password@example.invalid/db\n",
        encoding="utf-8",
    )
    direnv_cache = workspace / ".direnv" / "environment"
    direnv_cache.parent.mkdir()
    direnv_cache.write_text("opaque-direnv-cache\n", encoding="utf-8")
    kube_config = workspace / ".kube" / "config"
    kube_config.parent.mkdir()
    kube_config.write_text("opaque-mounted-kube-credential\n", encoding="utf-8")

    managed_attempt = logs / "experiment-autoresearch" / "parent-sha" / "attempt_1"
    managed_attempt.mkdir(parents=True)
    managed_records = {
        "proposer_prompt.txt": "Public proposal prompt.\n",
        "proposer_codex_transcript.jsonl": '{"message":"public proposal trace"}\n',
        "proposal.md": "# Public candidate proposal\n",
        "autoresearch_hitl_experiment_codex.log": "Public candidate experiment trace.\n",
        "additional_agent_01_resource_finder/resource_finder_codex.log": (
            "Public additional-agent trace.\n"
        ),
        "proposal_discussion/tasks/task-1/launch-1/codex.log": (
            "Public proposal discussion trace.\n"
        ),
    }
    for relative, content in managed_records.items():
        destination = managed_attempt / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    scoring = workspace / "scoring"
    scoring.mkdir()
    sealed_marker = "SEALED-EVALUATOR-MARKER-DO-NOT-EXPORT"
    (scoring / "eval.py").write_text(
        f"# {sealed_marker}\ndef evaluate():\n    return 42\n",
        encoding="utf-8",
    )
    os.link(scoring / "eval.py", workspace / "generated-evaluator-alias.txt")
    (scoring / "targets.json").write_text('{"target": 0.731}\n', encoding="utf-8")
    (scoring / "interface.md").write_text("Write public results.\n", encoding="utf-8")
    (logs / "leaked_worker_note.txt").write_text(sealed_marker + "\n", encoding="utf-8")
    borrowed_role = logs / "untrusted" / "proposal.txt"
    borrowed_role.parent.mkdir()
    borrowed_role.write_text(sealed_marker + "\n", encoding="utf-8")
    (logs / "rule_maker_codex_transcript.jsonl").write_text(
        '{"message":"privileged trace with answer 42 and ' + sealed_marker + '"}\n',
        encoding="utf-8",
    )

    neurico = workspace / ".neurico"
    manager = neurico / "hitl" / "manager"
    manager.mkdir(parents=True)
    (neurico / "pipeline_state.json").write_text(
        '{"workflow":"ordinary","completed":true}\n',
        encoding="utf-8",
    )
    control = neurico / "hitl" / "control"
    control.mkdir()
    (control / "credential.json").write_text('{"token":"never-copy-this"}\n')
    (manager / "history.jsonl").write_text(
        '{"message":"manager private answer 42"}\n', encoding="utf-8"
    )

    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    manifest = export_harbor_research_artifacts(
        run_id="test-run",
        workspace=workspace,
        workspace_baseline=baseline,
        artifact_dir=artifact_dir,
        project_root=tmp_path / "not-a-repository",
        instruction=f"Solve the supplied task exactly. Credential: {connection_secret}",
        run_configuration={"workflow": "ordinary", "focused": True},
        started_at="2026-11-08T00:00:00+00:00",
        elapsed_seconds=12.5,
        outcome="success",
        return_code=0,
        supervisor_error_type=None,
        redactor=redactor,
    )

    transcript = artifact_dir / "workspace/files/logs/experiment_runner_codex_transcript.jsonl"
    assert transcript.is_file()
    assert "definitely-secret-value" not in transcript.read_text()
    assert "opaque-json-secret" not in transcript.read_text()
    assert "opaque-client-secret" not in transcript.read_text()
    assert '"token_count": 17' in transcript.read_text()
    assert "REDACTED_SECRET_FIELD" in transcript.read_text()
    yaml_trace = (artifact_dir / "workspace/files/logs/experiment_runner_config.yaml").read_text()
    assert "opaque-yaml-secret" not in yaml_trace
    assert "second-client-secret" not in yaml_trace
    assert "opaque inline secret with spaces" not in yaml_trace
    assert "opaque-inline-bearer-secret" not in yaml_trace
    assert "opaque-private-key-block" not in yaml_trace
    assert "opaque-indented-api-key" not in yaml_trace
    assert "opaque-unconfigured-bearer-secret" not in yaml_trace
    assert "opaque-bare-private-key" not in yaml_trace
    assert "keep-this-public-note" in yaml_trace
    assert (artifact_dir / "workspace/files/logs/dsi-slurm-artifacts/123/slurm_123.out").is_file()
    assert (artifact_dir / "workspace/files/logs/dsi-slurm-artifacts/123/slurm_123.err").is_file()
    assert (artifact_dir / "workspace/files/logs/dsi-slurm-artifacts/123/job.json").is_file()
    assert (artifact_dir / "workspace/files/logs/modal_lora-train_20261109_120000.log").is_file()
    assert not (artifact_dir / "workspace/files/logs/auth.json").exists()
    assert not (artifact_dir / "workspace/files/logs/leaked_worker_note.txt").exists()
    assert not (artifact_dir / "workspace/files/logs/untrusted/proposal.txt").exists()
    assert not (artifact_dir / "workspace/files/logs/rule_maker_codex_transcript.jsonl").exists()
    assert not (artifact_dir / "workspace/files/logs/experiment_runner_binary.bin").exists()
    assert not (artifact_dir / "workspace/files/generated-evaluator-alias.txt").exists()
    assert not (artifact_dir / "workspace/files/.envrc").exists()
    assert not (artifact_dir / "workspace/files/.direnv/environment").exists()
    assert not (artifact_dir / "workspace/files/.kube/config").exists()
    for relative in managed_records:
        assert (
            artifact_dir / "workspace/files" / managed_attempt.relative_to(workspace) / relative
        ).is_file()
    assert not (artifact_dir / "workspace/files/.neurico/hitl/control/credential.json").exists()
    assert not (artifact_dir / "workspace/files/.neurico/pipeline_state.json").exists()
    assert (artifact_dir / "workspace/snapshot.json").is_file()
    assert not (artifact_dir / "workspace/files/.neurico/hitl/manager/history.jsonl").exists()
    snapshot = json.loads((artifact_dir / "workspace/snapshot.json").read_text())
    assert snapshot["capture_complete"] is False
    assert snapshot["capture_incomplete_reasons"] == ["unclassified_log_withheld"]
    assert not (set(snapshot["exclusion_summary"]) & artifacts_module._SENSITIVE_EXCLUSION_REASONS)
    collection = json.loads((artifact_dir / "collection.json").read_text())
    assert not (
        set(collection["excluded_entry_counts"]) & artifacts_module._SENSITIVE_EXCLUSION_REASONS
    )
    assert collection["policy"]["threat_model"] == "behavioral_application_level_sealing"
    assert collection["policy"]["worker_log_assumption"] == (
        "workers_do_not_access_sealed_evaluator_material"
    )
    assert collection["policy"]["unregistered_mount_assumption"] == (
        "workers_do_not_access_or_disclose_unrelated_mounted_credentials"
    )
    assert collection["policy"]["not_an_os_sandbox"] is True
    run_record = json.loads((artifact_dir / "run.json").read_text())
    assert run_record["outcome"] == "success"
    assert run_record["instruction_hash_basis"] == "sanitized_trace_text"
    assert run_record["output_stream"]["public_payload_persisted"] is False
    exported_payload = b"\n".join(
        path.read_bytes() for path in artifact_dir.rglob("*") if path.is_file()
    )
    assert sealed_marker.encode() not in exported_payload
    assert preexisting_marker.encode() not in exported_payload
    assert "benchmark_fixture.py" not in (artifact_dir / "workspace/snapshot.json").read_text()
    assert b"arbitrary-mounted-secret" not in exported_payload
    assert b"never-copy-this" not in exported_payload
    assert unrelated_environment_secret.encode() not in exported_payload
    assert mounted_auth_secret.encode() not in exported_payload
    assert connection_secret.encode() not in exported_payload
    assert b"opaque-binary-credential" not in exported_payload
    assert b"opaque-direnv-password" not in exported_payload
    assert b"opaque-direnv-cache" not in exported_payload
    assert b"opaque-mounted-kube-credential" not in exported_payload
    workspace_git = json.loads((artifact_dir / "workspace/git-summary.json").read_text())
    assert set(workspace_git) == {"available", "head"}
    runtime = json.loads((artifact_dir / "runtime.json").read_text())
    assert "environment" not in runtime
    assert "executable" not in runtime["python"]
    manifest_paths = {entry["path"] for entry in manifest["files"]}
    assert "input/instruction.txt" in manifest_paths
    assert "run.json" in manifest_paths
    assert "manifest.json" not in manifest_paths


def test_workspace_snapshots_preserve_reproducible_state_and_audit_exclusions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = "snapshot-test-secret-value"
    monkeypatch.setenv("OPENAI_API_KEY", secret)

    source = workspace / "REPORT.md"
    source.write_text(f"result=initial\nOPENAI_API_KEY={secret}\n", encoding="utf-8")
    supplied_source = workspace / "benchmark_source.py"
    supplied_source.write_text("PUBLIC-SUPPLIED-FUNCTION\n", encoding="utf-8")
    binary = workspace / "results" / "weights.bin"
    binary.parent.mkdir()
    binary_payload = b"ascii-binary-payload"
    binary.write_bytes(binary_payload)
    (workspace / "results" / "unsafe.bin").write_bytes(secret.encode("utf-8"))
    (workspace / "empty-directory").mkdir()
    (workspace / "latest-result").symlink_to("results/weights.bin")
    (workspace / ".env").write_text(f"OPENAI_API_KEY={secret}\n", encoding="utf-8")
    hidden = workspace / "data" / ".test"
    hidden.mkdir(parents=True)
    (hidden / "answers.json").write_text('{"answer": 42}\n', encoding="utf-8")
    dependency = workspace / ".venv"
    dependency.mkdir()
    (dependency / "installed.txt").write_text("dependency cache\n", encoding="utf-8")
    baseline = capture_workspace_baseline(workspace)

    artifact_dir = workspace / "trace-output"
    source.write_text(f"result=final\nOPENAI_API_KEY={secret}\n", encoding="utf-8")
    supplied_source.write_text(
        "PUBLIC-SUPPLIED-FUNCTION\n# agent modification\n",
        encoding="utf-8",
    )
    (workspace / "generated.txt").write_text("new evidence\n", encoding="utf-8")
    scoring = workspace / "scoring"
    scoring.mkdir()
    (scoring / "eval.py").write_text("def evaluate():\n    return 42\n", encoding="utf-8")
    (scoring / "targets.json").write_text('{"target": 42}\n', encoding="utf-8")
    (scoring / "interface.md").write_text("Return a public metric.\n", encoding="utf-8")
    final_manifest = capture_workspace_snapshot(
        workspace=workspace,
        artifact_dir=artifact_dir,
        baseline=baseline,
        phase="final",
    )

    final_files = {entry["path"]: entry for entry in final_manifest["files"]}
    assert "generated.txt" in final_files
    assert final_files["REPORT.md"]["redacted"] is True
    assert final_files["REPORT.md"]["source_metadata_withheld"] is True
    assert "source_bytes" not in final_files["REPORT.md"]
    redacted_copy = artifact_dir / final_files["REPORT.md"]["artifact"]
    assert secret not in redacted_copy.read_text()
    assert "results/weights.bin" not in final_files
    assert "benchmark_source.py" in final_files
    supplied_copy = artifact_dir / final_files["benchmark_source.py"]["artifact"]
    assert supplied_copy.read_text() == "PUBLIC-SUPPLIED-FUNCTION\n# agent modification\n"
    assert binary_payload not in b"\n".join(
        path.read_bytes() for path in artifact_dir.rglob("*") if path.is_file()
    )

    exclusions = {(entry["path"], entry["reason"]) for entry in final_manifest["public_exclusions"]}
    assert (".venv", "dependency_environment") in exclusions
    assert ("trace-output", "artifact_output") in exclusions
    assert not (
        set(final_manifest["exclusion_summary"]) & artifacts_module._SENSITIVE_EXCLUSION_REASONS
    )
    assert not any(
        entry["path"] in {".env", "data/.test", "latest-result"}
        for entry in final_manifest["public_exclusions"]
    )
    assert "scoring/eval.py" not in final_files
    assert "scoring/targets.json" not in final_files
    assert "scoring/interface.md" in final_files
    snapshot_payload = (artifact_dir / "workspace/snapshot.json").read_text()
    assert "scoring/eval.py" not in snapshot_payload
    assert "scoring/targets.json" not in snapshot_payload
    assert ".env" not in snapshot_payload
    assert "benchmark_source.py" in snapshot_payload
    assert "PUBLIC-SUPPLIED-FUNCTION" in supplied_copy.read_text()
    assert (artifact_dir / "workspace/snapshot.json").is_file()


def test_workspace_snapshot_limits_are_audited_without_reading_oversized_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    baseline = capture_workspace_baseline(workspace)
    oversized = workspace / "oversized.txt"
    with oversized.open("wb") as handle:
        handle.truncate(32)
    (workspace / "budget.txt").write_text("12345", encoding="utf-8")

    monkeypatch.setattr(artifacts_module, "_SNAPSHOT_MAX_FILE_BYTES", 16)
    monkeypatch.setattr(artifacts_module, "_SNAPSHOT_BUDGET_BYTES", 4)
    monkeypatch.setattr(artifacts_module, "_SNAPSHOT_MIN_FREE_BYTES", 0)
    manifest = capture_workspace_snapshot(
        workspace=workspace,
        artifact_dir=tmp_path / "artifacts",
        baseline=baseline,
        phase="final",
    )

    exclusions = {(entry["path"], entry["reason"]) for entry in manifest["public_exclusions"]}
    assert ("oversized.txt", "file_size_limit") in exclusions
    assert ("budget.txt", "snapshot_byte_budget") in exclusions
    assert manifest["capture_complete"] is False
    assert manifest["capture_stop_reason"] is None
    assert manifest["capture_incomplete_reasons"] == [
        "file_size_limit",
        "snapshot_byte_budget",
    ]


def test_changed_binary_output_is_withheld_but_makes_coverage_partial(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    binary = workspace / "results" / "model.bin"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"initial-binary")
    baseline = capture_workspace_baseline(workspace)
    binary.write_bytes(b"changed-binary")
    # Immediate same-size writes can share timestamps on container filesystems.
    current = binary.stat()
    os.utime(binary, ns=(current.st_atime_ns, current.st_mtime_ns + 1_000_000_000))

    artifact_dir = tmp_path / "artifacts"
    snapshot = capture_workspace_snapshot(
        workspace=workspace,
        artifact_dir=artifact_dir,
        baseline=baseline,
    )

    assert snapshot["capture_complete"] is False
    assert snapshot["capture_incomplete_reasons"] == ["public_binary_payload_withheld"]
    assert snapshot["files"] == []
    serialized = (artifact_dir / "workspace/snapshot.json").read_text()
    assert "model.bin" not in serialized
    assert "changed-binary" not in serialized


def test_public_text_that_cannot_be_sanitized_makes_coverage_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    baseline = capture_workspace_baseline(workspace)
    unsafe_payload = b"public-looking-output-that-sanitizer-rejected\n"
    (workspace / "generated.txt").write_bytes(unsafe_payload)
    original_safe_text_payload = artifacts_module._safe_text_payload

    def reject_generated(payload: bytes, suffix: str, redactor, **kwargs):
        if payload == unsafe_payload and suffix == ".txt":
            return None
        return original_safe_text_payload(payload, suffix, redactor, **kwargs)

    monkeypatch.setattr(artifacts_module, "_safe_text_payload", reject_generated)
    artifact_dir = tmp_path / "artifacts"
    snapshot = capture_workspace_snapshot(
        workspace=workspace,
        artifact_dir=artifact_dir,
        baseline=baseline,
    )

    assert snapshot["capture_complete"] is False
    assert snapshot["capture_incomplete_reasons"] == ["public_text_redaction_failed"]
    assert snapshot["files"] == []
    serialized = (artifact_dir / "workspace/snapshot.json").read_text()
    assert "generated.txt" not in serialized
    assert unsafe_payload not in serialized.encode()


def test_workspace_snapshot_time_budget_stops_best_effort_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    baseline = capture_workspace_baseline(workspace)
    (workspace / "input.txt").write_text("input\n", encoding="utf-8")
    monkeypatch.setattr(artifacts_module, "_SNAPSHOT_MAX_CAPTURE_SECONDS", 0.0)

    manifest = capture_workspace_snapshot(
        workspace=workspace,
        artifact_dir=tmp_path / "artifacts",
        baseline=baseline,
        phase="final",
    )

    assert manifest["capture_complete"] is False
    assert manifest["capture_stop_reason"] == "capture_time_budget_exhausted"
    assert manifest["capture_incomplete_reasons"] == ["capture_time_budget_exhausted"]
    assert manifest["files"] == []


def test_workspace_snapshot_entry_budget_marks_collection_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    baseline = capture_workspace_baseline(workspace)
    (workspace / "first.txt").write_text("first\n", encoding="utf-8")
    (workspace / "second.txt").write_text("second\n", encoding="utf-8")
    monkeypatch.setattr(artifacts_module, "_SNAPSHOT_MAX_ENTRIES", 1)
    monkeypatch.setattr(artifacts_module, "_SNAPSHOT_MIN_FREE_BYTES", 0)

    manifest = capture_workspace_snapshot(
        workspace=workspace,
        artifact_dir=tmp_path / "artifacts",
        baseline=baseline,
    )

    assert manifest["capture_complete"] is False
    assert manifest["capture_stop_reason"] == "entry_budget_exhausted"
    assert manifest["capture_incomplete_reasons"] == ["entry_budget_exhausted"]
    assert manifest["examined_public_files"] == 1
    assert [entry["path"] for entry in manifest["files"]] == ["first.txt"]


def test_workspace_snapshot_rejects_file_replaced_after_lstat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    baseline = capture_workspace_baseline(workspace)
    public_file = workspace / "generated.txt"
    public_file.write_text("benign public output\n", encoding="utf-8")
    sealed_file = tmp_path / "sealed-evaluator.txt"
    sealed_marker = "SEALED-RACE-MARKER"
    sealed_file.write_text(sealed_marker + "\n", encoding="utf-8")
    original_open = artifacts_module._open_workspace_regular_file
    swapped = False

    def swap_then_open(workspace_path, expected_workspace_stat, relative):
        nonlocal swapped
        if relative == Path("generated.txt") and not swapped:
            swapped = True
            public_file.unlink()
            os.link(sealed_file, public_file)
        return original_open(workspace_path, expected_workspace_stat, relative)

    monkeypatch.setattr(artifacts_module, "_open_workspace_regular_file", swap_then_open)
    artifact_dir = tmp_path / "artifacts"
    snapshot = capture_workspace_snapshot(
        workspace=workspace,
        artifact_dir=artifact_dir,
        baseline=baseline,
    )

    assert swapped is True
    assert snapshot["files"] == []
    assert snapshot["capture_complete"] is False
    assert snapshot["capture_stop_reason"] is None
    assert snapshot["capture_incomplete_reasons"] == ["filesystem_error"]
    assert snapshot["errors"] == [{"type": "OSError", "count": 1}]
    bundle = b"\n".join(path.read_bytes() for path in artifact_dir.rglob("*") if path.is_file())
    assert sealed_marker.encode() not in bundle


def test_workspace_snapshot_rejects_replaced_workspace_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    baseline = capture_workspace_baseline(workspace)
    original_workspace = tmp_path / "original-workspace"
    workspace.rename(original_workspace)
    workspace.mkdir()
    sealed_marker = "SEALED-REPLACED-WORKSPACE-MARKER"
    (workspace / "generated.txt").write_text(sealed_marker + "\n", encoding="utf-8")
    artifact_dir = tmp_path / "artifacts"

    with pytest.raises(OSError, match="workspace was replaced"):
        capture_workspace_snapshot(
            workspace=workspace,
            artifact_dir=artifact_dir,
            baseline=baseline,
        )

    assert not artifact_dir.exists()


def test_workspace_baseline_rejects_symlinked_workspace_root(tmp_path: Path) -> None:
    real_workspace = tmp_path / "real-workspace"
    real_workspace.mkdir()
    workspace_link = tmp_path / "workspace"
    workspace_link.symlink_to(real_workspace, target_is_directory=True)

    with pytest.raises(OSError):
        capture_workspace_baseline(workspace_link)


def test_sensitive_paths_are_rejected_before_per_file_metadata_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    sealed_file = workspace / "scoring" / "eval.py"
    sealed_file.parent.mkdir(parents=True)
    sealed_file.write_text("def sealed_evaluator(): return 42\n", encoding="utf-8")
    original_is_symlink = Path.is_symlink
    original_lstat = Path.lstat

    def guarded_is_symlink(path: Path) -> bool:
        if path == sealed_file:
            raise AssertionError("sealed path metadata was inspected")
        return original_is_symlink(path)

    def guarded_lstat(path: Path):
        if path == sealed_file:
            raise AssertionError("sealed path metadata was inspected")
        return original_lstat(path)

    monkeypatch.setattr(Path, "is_symlink", guarded_is_symlink)
    monkeypatch.setattr(Path, "lstat", guarded_lstat)
    baseline = capture_workspace_baseline(workspace)
    snapshot = capture_workspace_snapshot(
        workspace=workspace,
        artifact_dir=tmp_path / "artifacts",
        baseline=baseline,
    )

    assert baseline.complete is True
    assert baseline.fingerprints == {}
    assert snapshot["errors"] == []
    assert snapshot["files"] == []
    assert snapshot["examined_public_files"] == 0
    assert snapshot["exclusion_summary"] == {}
    assert snapshot["public_exclusions"] == []


def test_workspace_baseline_detects_same_size_edit_with_restored_mtime(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    log_file = workspace / "logs" / "experiment_runner_codex.log"
    log_file.parent.mkdir(parents=True)
    log_file.write_text("original-public-log\n", encoding="utf-8")
    original_stat = log_file.stat()
    baseline = capture_workspace_baseline(workspace)
    # Allow ctime to advance on filesystems with coarse update granularity.
    time.sleep(0.01)
    log_file.write_text("modified-public-log\n", encoding="utf-8")
    os.utime(log_file, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    snapshot = capture_workspace_snapshot(
        workspace=workspace,
        artifact_dir=tmp_path / "artifacts",
        baseline=baseline,
    )

    assert [entry["path"] for entry in snapshot["files"]] == ["logs/experiment_runner_codex.log"]


def test_workspace_capture_errors_are_reported_in_collection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    baseline = capture_workspace_baseline(workspace)
    (workspace / "generated.txt").write_text("public output\n", encoding="utf-8")

    def fail_open(*_args: Any, **_kwargs: Any):
        raise OSError("simulated read failure")

    monkeypatch.setattr(artifacts_module, "_open_workspace_regular_file", fail_open)
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    manifest = export_harbor_research_artifacts(
        run_id="test-run",
        workspace=workspace,
        workspace_baseline=baseline,
        artifact_dir=artifact_dir,
        project_root=tmp_path / "not-a-repository",
        instruction="Run the public task.",
        run_configuration={"workflow": "autoresearch"},
        started_at="2026-11-09T00:00:00+00:00",
        elapsed_seconds=1.0,
        outcome="success",
        return_code=0,
        supervisor_error_type=None,
    )

    snapshot = json.loads((artifact_dir / "workspace/snapshot.json").read_text())
    collection = json.loads((artifact_dir / "collection.json").read_text())
    assert snapshot["capture_complete"] is False
    assert snapshot["capture_stop_reason"] is None
    assert snapshot["capture_incomplete_reasons"] == ["filesystem_error"]
    assert collection["workspace_capture_complete"] is False
    assert collection["workspace_capture_stop_reason"] is None
    assert collection["workspace_capture_incomplete_reasons"] == ["filesystem_error"]
    assert collection["errors"] == [{"stage": "workspace_snapshot", "type": "OSError", "count": 1}]
    assert manifest["collection_status"] == "partial"


def test_unpreserved_instruction_has_no_content_hash_and_marks_bundle_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    baseline = capture_workspace_baseline(workspace)
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    instruction = "instruction rejected by sanitizer"
    original_safe_text_payload = artifacts_module._safe_text_payload

    def reject_instruction(payload: bytes, suffix: str, redactor, **kwargs):
        if payload == instruction.encode("utf-8") and suffix == ".txt":
            return None
        return original_safe_text_payload(payload, suffix, redactor, **kwargs)

    monkeypatch.setattr(artifacts_module, "_safe_text_payload", reject_instruction)
    manifest = export_harbor_research_artifacts(
        run_id="test-run",
        workspace=workspace,
        workspace_baseline=baseline,
        artifact_dir=artifact_dir,
        project_root=tmp_path / "not-a-repository",
        instruction=instruction,
        run_configuration={"workflow": "autoresearch"},
        started_at="2026-11-09T00:00:00+00:00",
        elapsed_seconds=1.0,
        outcome="success",
        return_code=0,
        supervisor_error_type=None,
    )

    run_record = json.loads((artifact_dir / "run.json").read_text())
    collection = json.loads((artifact_dir / "collection.json").read_text())
    assert run_record["instruction_sha256"] is None
    assert run_record["instruction_hash_basis"] == "not_recorded"
    assert collection["instruction_preserved"] is False
    assert collection["collection_incomplete_reasons"] == ["instruction_not_preserved"]
    assert manifest["collection_status"] == "partial"
    assert not (artifact_dir / "input/instruction.txt").exists()


def test_incomplete_pre_run_inventory_fails_closed_for_unknown_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "possibly-supplied-function.py").write_text(
        "def hidden_evaluator(): return 42\n",
        encoding="utf-8",
    )
    baseline = artifacts_module.WorkspaceBaseline(
        fingerprints={},
        root_identity=None,
        complete=False,
        stop_reason="entry_budget_exhausted",
    )

    manifest = capture_workspace_snapshot(
        workspace=workspace,
        artifact_dir=tmp_path / "artifacts",
        baseline=baseline,
        phase="final",
    )

    assert manifest["files"] == []
    assert manifest["capture_complete"] is False
    assert manifest["capture_incomplete_reasons"] == ["pre_run_inventory_incomplete"]
    assert manifest["exclusion_summary"] == {}
    assert manifest["public_exclusions"] == []
    payload = (tmp_path / "artifacts/workspace/snapshot.json").read_text()
    assert "possibly-supplied-function.py" not in payload
    assert "hidden_evaluator" not in payload


def test_private_scratch_retains_uncertain_files_without_copying_sealed_paths(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sealed = workspace / "scoring" / "eval.py"
    sealed.parent.mkdir()
    sealed.write_text("def evaluate(): return 'sealed-before'\n", encoding="utf-8")
    baseline = capture_workspace_baseline(workspace)

    unclassified = workspace / "logs" / "unknown-producer.log"
    unclassified.parent.mkdir()
    unclassified.write_bytes(b"raw unclassified trace\x00\xff")
    binary = workspace / "result.bin"
    binary.write_bytes(b"\x00generated binary\xff")
    sealed.write_text("def evaluate(): return 'sealed-after'\n", encoding="utf-8")

    scratch = EphemeralRunScratch.create(root=tmp_path / "scratch", run_id="scratch-run")
    snapshot = capture_workspace_snapshot(
        workspace=workspace,
        artifact_dir=tmp_path / "artifacts",
        baseline=baseline,
        scratch=scratch,
    )
    scratch.finalize()

    public_payload = b"\n".join(
        path.read_bytes() for path in (tmp_path / "artifacts").rglob("*") if path.is_file()
    )
    assert b"raw unclassified trace" not in public_payload
    assert b"generated binary" not in public_payload
    assert b"sealed-after" not in public_payload
    assert snapshot["capture_complete"] is False
    assert set(snapshot["capture_incomplete_reasons"]) == {
        "public_binary_payload_withheld",
        "unclassified_log_withheld",
    }

    run_scratch = tmp_path / "scratch" / "scratch-run"
    assert (run_scratch / "workspace/logs/unknown-producer.log").read_bytes() == (
        b"raw unclassified trace\x00\xff"
    )
    assert (run_scratch / "workspace/result.bin").read_bytes() == b"\x00generated binary\xff"
    assert not (run_scratch / "workspace/scoring/eval.py").exists()
    metadata = json.loads((run_scratch / "scratch.json").read_text())
    assert {record["path"] for record in metadata["files"]} == {
        "workspace/logs/unknown-producer.log",
        "workspace/result.bin",
    }
    assert run_scratch.stat().st_mode & 0o777 == 0o700
    assert (run_scratch / "scratch.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    ("exit_code", "expected_outcome"),
    [(0, "success"), (7, "failed"), (124, "time_limit")],
)
def test_parent_owns_post_stop_trace_finalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exit_code: int,
    expected_outcome: str,
) -> None:
    async def exercise() -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        artifact_root = tmp_path / "artifacts"
        artifact_root.mkdir()
        scratch_root = tmp_path / "scratch"
        original_create = asyncio.create_subprocess_exec
        emitted: list[str] = []

        async def fake_create(*_args: Any, **kwargs: Any):
            assert not (artifact_root / "test-run").exists()
            assert not scratch_root.exists()
            code = (
                "from pathlib import Path; import sys; "
                "Path('generated.txt').write_text('public result\\n'); "
                "Path('logs').mkdir(exist_ok=True); "
                "Path('logs/experiment_runner_codex.log').write_text('worker trace\\n'); "
                "sys.stdout.write('mixed-authority-output'); "
                f"raise SystemExit({exit_code})"
            )
            return await original_create(
                sys.executable,
                "-c",
                code,
                cwd=kwargs["cwd"],
                env=kwargs["env"],
                stdout=kwargs["stdout"],
                stderr=kwargs["stderr"],
                start_new_session=kwargs["start_new_session"],
            )

        async def emit(text: str) -> None:
            assert not (artifact_root / "test-run").exists()
            emitted.append(text)

        monkeypatch.setattr(agent_module, "DEFAULT_HARBOR_ARTIFACT_ROOT", artifact_root)
        monkeypatch.setattr(agent_module, "DEFAULT_HARBOR_SCRATCH_ROOT", scratch_root)
        monkeypatch.setattr(
            agent_module,
            "build_autoresearch_environment",
            lambda base_environment, connection, **_kwargs: dict(base_environment),
        )
        monkeypatch.setattr(agent_module.asyncio, "create_subprocess_exec", fake_create)
        connection = CodexInferenceConnection(
            requested_model="openai/test-model",
            mode="hosted-gateway",
            token="not-used",
            base_url="https://example.invalid/v1",
        )
        return_code = await run_autoresearch_process(
            task=HarborAutoResearchTask(
                instruction="Run the benchmark.",
                workspace=workspace,
            ),
            connection=connection,
            base_environment=dict(os.environ),
            iterations=1,
            time_limit_seconds=None,
            run_id="test-run",
            emit=emit,
            register_process=lambda _process: False,
        )

        assert return_code == exit_code
        assert emitted == []
        run_dir = artifact_root / "test-run"
        run_record = json.loads((run_dir / "run.json").read_text())
        manifest = json.loads((run_dir / "manifest.json").read_text())
        assert run_record["outcome"] == expected_outcome
        assert run_record["run_id"] == "test-run"
        assert manifest["run_id"] == "test-run"
        assert manifest["collection_status"] == "scope_complete"
        assert run_record["output_stream"]["public_payload_forwarded"] is False
        assert run_record["output_stream"]["public_payload_persisted"] is False
        assert run_record["output_stream"]["public_payload_metadata_persisted"] is False
        assert set(run_record["output_stream"]) == {
            "public_payload_forwarded",
            "public_payload_persisted",
            "public_payload_metadata_persisted",
            "reason",
        }
        assert (run_dir / "workspace/files/generated.txt").read_text() == "public result\n"
        assert (
            run_dir / "workspace/files/logs/experiment_runner_codex.log"
        ).read_text() == "worker trace\n"
        bundle = b"\n".join(path.read_bytes() for path in run_dir.rglob("*") if path.is_file())
        assert b"mixed-authority-output" not in bundle
        scratch_dir = scratch_root / "test-run"
        assert (scratch_dir / "streams/stdout-stderr.raw").read_bytes() == (
            b"mixed-authority-output"
        )
        assert scratch_dir.stat().st_mode & 0o777 == 0o700
        assert (scratch_dir / "streams/stdout-stderr.raw").stat().st_mode & 0o777 == 0o600
        assert not any("scratch" in str(path) for path in run_dir.rglob("*"))
        verified = artifacts_module.verify_trace_bundle(artifact_dir=run_dir)
        assert verified["collection_status"] == "scope_complete"
        (run_dir / "post-publication-injection.txt").write_text(
            "unmanifested payload\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="absent from its manifest"):
            artifacts_module.verify_trace_bundle(artifact_dir=run_dir)

    asyncio.run(exercise())


def test_trace_preflight_keeps_event_loop_responsive_to_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        artifact_root = tmp_path / "artifacts"
        capture_started = threading.Event()
        release_capture = threading.Event()
        cancelled = False
        original_capture = agent_module.capture_workspace_baseline

        def blocking_capture(*args: Any, **kwargs: Any):
            assert threading.current_thread() is not threading.main_thread()
            capture_started.set()
            assert release_capture.wait(timeout=5), "preflight blocked the event loop"
            return original_capture(*args, **kwargs)

        async def unexpected_spawn(*_args: Any, **_kwargs: Any):
            raise AssertionError("cancelled preflight must not spawn NeuriCo")

        monkeypatch.setattr(agent_module, "DEFAULT_HARBOR_ARTIFACT_ROOT", artifact_root)
        monkeypatch.setattr(agent_module, "capture_workspace_baseline", blocking_capture)
        monkeypatch.setattr(agent_module.asyncio, "create_subprocess_exec", unexpected_spawn)
        run = asyncio.create_task(
            run_autoresearch_process(
                task=HarborAutoResearchTask(
                    instruction="Run the benchmark.",
                    workspace=workspace,
                ),
                connection=CodexInferenceConnection(
                    requested_model="openai/test-model",
                    mode="hosted-gateway",
                    token="not-used",
                    base_url="https://example.invalid/v1",
                ),
                base_environment={},
                iterations=1,
                time_limit_seconds=None,
                run_id="cancelled-preflight",
                emit=lambda _text: asyncio.sleep(0),
                register_process=lambda _process: False,
                cancellation_requested=lambda: cancelled,
            )
        )

        deadline = time.monotonic() + 5
        while not capture_started.is_set():
            assert time.monotonic() < deadline
            await asyncio.sleep(0.01)
        cancelled = True
        release_capture.set()

        assert await asyncio.wait_for(run, timeout=5) == 1
        run_record = json.loads((artifact_root / "cancelled-preflight/run.json").read_text())
        assert run_record["outcome"] == "cancelled"

    asyncio.run(exercise())


def test_trace_finalization_does_not_block_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        artifact_root = tmp_path / "artifacts"
        export_started = threading.Event()
        release_export = threading.Event()
        original_create = asyncio.create_subprocess_exec
        original_export = agent_module.export_harbor_research_artifacts

        async def fake_create(*_args: Any, **kwargs: Any):
            return await original_create(
                sys.executable,
                "-c",
                "raise SystemExit(0)",
                cwd=kwargs["cwd"],
                env=kwargs["env"],
                stdout=kwargs["stdout"],
                stderr=kwargs["stderr"],
                start_new_session=kwargs["start_new_session"],
            )

        def blocking_export(**kwargs: Any):
            assert threading.current_thread() is not threading.main_thread()
            export_started.set()
            assert release_export.wait(timeout=5), "trace export blocked the event loop"
            return original_export(**kwargs)

        monkeypatch.setattr(agent_module, "DEFAULT_HARBOR_ARTIFACT_ROOT", artifact_root)
        monkeypatch.setattr(
            agent_module,
            "build_autoresearch_environment",
            lambda base_environment, connection, **_kwargs: dict(base_environment),
        )
        monkeypatch.setattr(agent_module.asyncio, "create_subprocess_exec", fake_create)
        monkeypatch.setattr(
            agent_module,
            "export_harbor_research_artifacts",
            blocking_export,
        )
        run = asyncio.create_task(
            run_autoresearch_process(
                task=HarborAutoResearchTask(
                    instruction="Run the benchmark.",
                    workspace=workspace,
                ),
                connection=CodexInferenceConnection(
                    requested_model="openai/test-model",
                    mode="hosted-gateway",
                    token="not-used",
                    base_url="https://example.invalid/v1",
                ),
                base_environment={},
                iterations=1,
                time_limit_seconds=None,
                run_id="threaded-finalization",
                emit=lambda _text: asyncio.sleep(0),
                register_process=lambda _process: False,
            )
        )

        deadline = time.monotonic() + 5
        while not export_started.is_set():
            assert time.monotonic() < deadline
            await asyncio.sleep(0.01)
        event_loop_progress = asyncio.Event()
        asyncio.get_running_loop().call_soon(event_loop_progress.set)
        try:
            await asyncio.wait_for(event_loop_progress.wait(), timeout=1)
        finally:
            release_export.set()

        assert await asyncio.wait_for(run, timeout=5) == 0
        manifest = json.loads((artifact_root / "threaded-finalization/manifest.json").read_text())
        assert manifest["collection_status"] == "scope_complete"

    asyncio.run(exercise())


def test_spawn_failure_still_gets_metadata_only_run_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        artifact_root = tmp_path / "artifacts"

        async def fail_spawn(*_args: Any, **_kwargs: Any):
            assert artifact_root.is_dir()
            assert list(artifact_root.iterdir()) == []
            raise OSError("spawn unavailable")

        monkeypatch.setattr(agent_module, "DEFAULT_HARBOR_ARTIFACT_ROOT", artifact_root)
        monkeypatch.setattr(
            agent_module,
            "build_autoresearch_environment",
            lambda base_environment, connection, **_kwargs: dict(base_environment),
        )
        monkeypatch.setattr(agent_module.asyncio, "create_subprocess_exec", fail_spawn)
        connection = CodexInferenceConnection(
            requested_model="openai/test-model",
            mode="hosted-gateway",
            token="not-used",
            base_url="https://example.invalid/v1",
        )
        with pytest.raises(OSError, match="spawn unavailable"):
            await run_autoresearch_process(
                task=HarborAutoResearchTask(
                    instruction="Run the benchmark.",
                    workspace=workspace,
                ),
                connection=connection,
                base_environment={},
                iterations=1,
                time_limit_seconds=None,
                run_id="spawn-failure",
                emit=lambda _text: asyncio.sleep(0),
                register_process=lambda _process: False,
            )

        run_record = json.loads((artifact_root / "spawn-failure/run.json").read_text())
        assert run_record["outcome"] == "spawn_failure"
        assert run_record["supervisor_error_type"] == "OSError"

    asyncio.run(exercise())


def test_trace_preflight_failure_does_not_prevent_research_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        artifact_root = tmp_path / "artifacts"
        auth_file = tmp_path / "large-valid-auth.json"
        auth_file.write_text(
            json.dumps({"token": "x" * (4 * 1024 * 1024)}),
            encoding="utf-8",
        )
        original_create = asyncio.create_subprocess_exec
        spawn_calls = 0

        async def fake_create(*_args: Any, **kwargs: Any):
            nonlocal spawn_calls
            spawn_calls += 1
            return await original_create(
                sys.executable,
                "-c",
                "raise SystemExit(0)",
                cwd=kwargs["cwd"],
                env=kwargs["env"],
                stdout=kwargs["stdout"],
                stderr=kwargs["stderr"],
                start_new_session=kwargs["start_new_session"],
            )

        monkeypatch.setattr(agent_module, "DEFAULT_HARBOR_ARTIFACT_ROOT", artifact_root)
        monkeypatch.setattr(
            agent_module,
            "build_autoresearch_environment",
            lambda base_environment, connection, **_kwargs: dict(base_environment),
        )
        monkeypatch.setattr(agent_module.asyncio, "create_subprocess_exec", fake_create)
        return_code = await run_autoresearch_process(
            task=HarborAutoResearchTask(
                instruction="Run the benchmark.",
                workspace=workspace,
            ),
            connection=CodexInferenceConnection(
                requested_model="openai/test-model",
                mode="chatgpt",
                auth_file=auth_file,
            ),
            base_environment={},
            iterations=1,
            time_limit_seconds=None,
            run_id="trace-preflight-failure",
            emit=lambda _text: asyncio.sleep(0),
            register_process=lambda _process: False,
        )

        assert return_code == 0
        assert spawn_calls == 1
        run_dir = artifact_root / "trace-preflight-failure"
        run_record = json.loads((run_dir / "run.json").read_text())
        collection = json.loads((run_dir / "collection.json").read_text())
        manifest = json.loads((run_dir / "manifest.json").read_text())
        assert run_record["outcome"] == "success"
        assert run_record["trace_export_error_type"] == "ValueError"
        assert collection["workspace_snapshot_preserved"] is False
        assert manifest["collection_status"] == "minimal"
        assert not (run_dir / "workspace").exists()

    asyncio.run(exercise())


def test_trace_export_failure_falls_back_without_changing_child_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        artifact_root = tmp_path / "artifacts"
        original_create = asyncio.create_subprocess_exec
        emitted: list[str] = []

        async def emit(text: str) -> None:
            emitted.append(text)

        async def fake_create(*_args: Any, **kwargs: Any):
            return await original_create(
                sys.executable,
                "-c",
                "raise SystemExit(0)",
                cwd=kwargs["cwd"],
                env=kwargs["env"],
                stdout=kwargs["stdout"],
                stderr=kwargs["stderr"],
                start_new_session=kwargs["start_new_session"],
            )

        monkeypatch.setattr(agent_module, "DEFAULT_HARBOR_ARTIFACT_ROOT", artifact_root)
        monkeypatch.setattr(
            agent_module,
            "build_autoresearch_environment",
            lambda base_environment, connection, **_kwargs: dict(base_environment),
        )
        monkeypatch.setattr(agent_module.asyncio, "create_subprocess_exec", fake_create)

        def fail_after_partial_export(**kwargs: Any):
            orphan = Path(kwargs["artifact_dir"]) / "workspace" / "files" / "orphan.txt"
            orphan.parent.mkdir(parents=True)
            orphan.write_text("partial payload\n", encoding="utf-8")
            raise OSError("export unavailable")

        monkeypatch.setattr(
            agent_module,
            "export_harbor_research_artifacts",
            fail_after_partial_export,
        )
        connection = CodexInferenceConnection(
            requested_model="openai/test-model",
            mode="hosted-gateway",
            token="not-used",
            base_url="https://example.invalid/v1",
        )
        return_code = await run_autoresearch_process(
            task=HarborAutoResearchTask(
                instruction="Run the benchmark.",
                workspace=workspace,
            ),
            connection=connection,
            base_environment={},
            iterations=1,
            time_limit_seconds=None,
            run_id="export-failure",
            emit=emit,
            register_process=lambda _process: False,
        )

        assert return_code == 0
        run_record = json.loads((artifact_root / "export-failure/run.json").read_text())
        assert run_record["outcome"] == "success"
        assert run_record["trace_export_error_type"] == "OSError"
        assert not (artifact_root / "export-failure/workspace/files/orphan.txt").exists()
        manifest = json.loads((artifact_root / "export-failure/manifest.json").read_text())
        assert "workspace/files/orphan.txt" not in {entry["path"] for entry in manifest["files"]}
        assert manifest["collection_status"] == "minimal"
        assert len(emitted) == 1
        assert "partial trace bundle" in emitted[0]
        assert [path.name for path in artifact_root.iterdir()] == ["export-failure"]

    asyncio.run(exercise())


def test_total_trace_export_failure_is_visible_without_changing_child_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        artifact_root = tmp_path / "artifacts"
        original_create = asyncio.create_subprocess_exec
        emitted: list[str] = []

        async def fake_create(*_args: Any, **kwargs: Any):
            return await original_create(
                sys.executable,
                "-c",
                "raise SystemExit(0)",
                cwd=kwargs["cwd"],
                env=kwargs["env"],
                stdout=kwargs["stdout"],
                stderr=kwargs["stderr"],
                start_new_session=kwargs["start_new_session"],
            )

        async def emit(text: str) -> None:
            emitted.append(text)

        def fail_export(**_kwargs: Any):
            raise OSError("full export unavailable")

        def fail_minimal_export(**_kwargs: Any):
            raise OSError("minimal export unavailable")

        monkeypatch.setattr(agent_module, "DEFAULT_HARBOR_ARTIFACT_ROOT", artifact_root)
        monkeypatch.setattr(
            agent_module,
            "build_autoresearch_environment",
            lambda base_environment, connection, **_kwargs: dict(base_environment),
        )
        monkeypatch.setattr(agent_module.asyncio, "create_subprocess_exec", fake_create)
        monkeypatch.setattr(agent_module, "export_harbor_research_artifacts", fail_export)
        monkeypatch.setattr(
            agent_module,
            "write_minimal_harbor_run_bundle",
            fail_minimal_export,
        )
        return_code = await run_autoresearch_process(
            task=HarborAutoResearchTask(
                instruction="Run the benchmark.",
                workspace=workspace,
            ),
            connection=CodexInferenceConnection(
                requested_model="openai/test-model",
                mode="hosted-gateway",
                token="not-used",
                base_url="https://example.invalid/v1",
            ),
            base_environment={},
            iterations=1,
            time_limit_seconds=None,
            run_id="total-export-failure",
            emit=emit,
            register_process=lambda _process: False,
        )

        assert return_code == 0
        assert artifact_root.is_dir()
        assert list(artifact_root.iterdir()) == []
        assert len(emitted) == 1
        assert "could not publish a trace bundle" in emitted[0]
        transaction_root = tmp_path / ".artifacts.transactions"
        assert transaction_root.is_dir()
        assert list(transaction_root.iterdir()) == []

    asyncio.run(exercise())


def test_trace_store_failure_is_visible_without_changing_child_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        artifact_root = tmp_path / "artifacts"
        original_create = asyncio.create_subprocess_exec
        emitted: list[str] = []

        class UnavailableStore:
            @staticmethod
            def open(_root: Path):
                raise OSError("storage unavailable")

        async def fake_create(*_args: Any, **kwargs: Any):
            return await original_create(
                sys.executable,
                "-c",
                "raise SystemExit(0)",
                cwd=kwargs["cwd"],
                env=kwargs["env"],
                stdout=kwargs["stdout"],
                stderr=kwargs["stderr"],
                start_new_session=kwargs["start_new_session"],
            )

        async def emit(text: str) -> None:
            emitted.append(text)

        monkeypatch.setattr(agent_module, "DEFAULT_HARBOR_ARTIFACT_ROOT", artifact_root)
        monkeypatch.setattr(agent_module, "HarborArtifactStore", UnavailableStore)
        monkeypatch.setattr(
            agent_module,
            "build_autoresearch_environment",
            lambda base_environment, connection, **_kwargs: dict(base_environment),
        )
        monkeypatch.setattr(agent_module.asyncio, "create_subprocess_exec", fake_create)
        return_code = await run_autoresearch_process(
            task=HarborAutoResearchTask(
                instruction="Run the benchmark.",
                workspace=workspace,
            ),
            connection=CodexInferenceConnection(
                requested_model="openai/test-model",
                mode="hosted-gateway",
                token="not-used",
                base_url="https://example.invalid/v1",
            ),
            base_environment={},
            iterations=1,
            time_limit_seconds=None,
            run_id="store-unavailable",
            emit=emit,
            register_process=lambda _process: False,
        )

        assert return_code == 0
        assert not artifact_root.exists()
        assert len(emitted) == 1
        assert "could not publish a trace bundle" in emitted[0]

    asyncio.run(exercise())


def test_forced_timeout_finalizes_only_after_child_termination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        artifact_root = tmp_path / "artifacts"
        original_create = asyncio.create_subprocess_exec

        async def fake_create(*_args: Any, **kwargs: Any):
            assert artifact_root.is_dir()
            assert list(artifact_root.iterdir()) == []
            return await original_create(
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
                cwd=kwargs["cwd"],
                env=kwargs["env"],
                stdout=kwargs["stdout"],
                stderr=kwargs["stderr"],
                start_new_session=kwargs["start_new_session"],
            )

        monkeypatch.setattr(agent_module, "DEFAULT_HARBOR_ARTIFACT_ROOT", artifact_root)
        monkeypatch.setattr(agent_module, "_COOPERATIVE_SHUTDOWN_GRACE_SECONDS", 0.0)
        monkeypatch.setattr(agent_module, "_FORCED_TERMINATION_GRACE_SECONDS", 0.1)
        monkeypatch.setattr(
            agent_module,
            "build_autoresearch_environment",
            lambda base_environment, connection, **_kwargs: dict(base_environment),
        )
        monkeypatch.setattr(agent_module.asyncio, "create_subprocess_exec", fake_create)
        connection = CodexInferenceConnection(
            requested_model="openai/test-model",
            mode="hosted-gateway",
            token="not-used",
            base_url="https://example.invalid/v1",
        )
        return_code = await run_autoresearch_process(
            task=HarborAutoResearchTask(
                instruction="Run the benchmark.",
                workspace=workspace,
            ),
            connection=connection,
            base_environment={},
            iterations=1,
            time_limit_seconds=0,
            run_id="forced-timeout",
            emit=lambda _text: asyncio.sleep(0),
            register_process=lambda _process: False,
        )

        assert return_code == 1
        run_record = json.loads((artifact_root / "forced-timeout/run.json").read_text())
        assert run_record["outcome"] == "forced_timeout"

    asyncio.run(exercise())


def test_child_translates_native_budget_stop_after_neurico_finalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class FakeManager:
        def __init__(self, ideas_dir: Path):
            pass

        def submit_idea(self, idea: dict[str, Any], validate: bool) -> str:
            return "harbor-idea"

    class FakeRunner:
        def __init__(self, *, use_github: bool):
            pass

        def run_research(self, **kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            raise runner_module.HitlRunStopRequested("HITL run stopped: budget_exhausted.")

    monkeypatch.setattr(runner_module, "IdeaManager", FakeManager)
    monkeypatch.setattr(runner_module, "ResearchRunner", FakeRunner)
    result = execute_autoresearch(
        instruction="Run until the benchmark budget expires.",
        workspace=tmp_path,
        ideas_dir=tmp_path / "ideas",
        time_limit_seconds=20,
    )

    assert result["stopped"] is True
    assert result["time_limit_reached"] is True
    assert captured["time_limit_seconds"] == 20


def test_harbor_interrupt_requests_native_run_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[str] = []

    class FakeControl:
        def request(self, *, requested_by: str) -> None:
            requests.append(requested_by)

    control = FakeControl()
    monkeypatch.setattr(runner_module, "active_hitl_run_stop_control", lambda: control)
    stop_requested = runner_module.threading.Event()
    finished = runner_module.threading.Event()
    stop_requested.set()

    runner_module._propagate_native_stop(stop_requested, finished)

    assert requests == ["harbor_cancel"]


def test_child_does_not_reclassify_non_budget_native_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeManager:
        def __init__(self, ideas_dir: Path):
            pass

        def submit_idea(self, idea: dict[str, Any], validate: bool) -> str:
            return "harbor-idea"

    class FakeRunner:
        def __init__(self, *, use_github: bool):
            pass

        def run_research(self, **kwargs: Any) -> dict[str, Any]:
            raise runner_module.HitlRunStopRequested("HITL run stopped: provider_unavailable.")

    monkeypatch.setattr(runner_module, "IdeaManager", FakeManager)
    monkeypatch.setattr(runner_module, "ResearchRunner", FakeRunner)

    with pytest.raises(runner_module.HitlRunStopRequested, match="provider_unavailable"):
        execute_autoresearch(
            instruction="Run this benchmark.",
            workspace=tmp_path,
            ideas_dir=tmp_path / "ideas",
            time_limit_seconds=20,
        )


def test_acp_prompt_launches_autoresearch_not_direct_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instruction = "Keep this exact:\n\n  value: '# literal'\n"
    captured: dict[str, Any] = {}
    task_venv = tmp_path / ".venv" / "pyvenv.cfg"
    task_venv.parent.mkdir()
    task_venv.write_text("owned by task\n")

    async def fake_autoresearch(**kwargs: Any) -> int:
        captured.update(kwargs)
        await kwargs["emit"]("AutoResearch output\n")
        return 0

    monkeypatch.setattr(agent_module, "run_autoresearch_process", fake_autoresearch)

    async def run_prompt() -> None:
        auth_file = tmp_path / "auth.json"
        auth_file.write_text('{"tokens": {}}')
        agent = NeuricoHarborAgent(
            {
                "NEURICO_MODEL": "openai/test-model",
                "NEURICO_CODEX_AUTH_FILE": str(auth_file),
                "NEURICO_HARBOR_TIME_LIMIT_SECONDS": "1740",
            }
        )
        session = await agent.new_session(cwd=str(tmp_path), mcp_servers=[])
        response = await agent.prompt(
            session_id=session.session_id,
            prompt=[{"type": "text", "text": instruction}],
        )
        assert response.stop_reason == "end_turn"

    asyncio.run(run_prompt())
    assert captured["task"].instruction == instruction
    assert captured["task"].workspace == tmp_path
    assert captured["iterations"] == 1
    assert captured["time_limit_seconds"] == 1740
    assert captured["connection"].backend_model == "test-model"
    assert captured["connection"].mode == "chatgpt"
    assert len(captured["run_id"]) == 65
    assert captured["run_id"][32] == "-"
    assert captured["run_id"].replace("-", "").isalnum()
    assert task_venv.read_text() == "owned by task\n"


def test_autoresearch_failure_fails_the_acp_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_venv = tmp_path / ".venv" / "pyvenv.cfg"
    task_venv.parent.mkdir()
    task_venv.write_text("owned by task\n")

    async def failing_autoresearch(**kwargs: Any) -> int:
        return 7

    monkeypatch.setattr(agent_module, "run_autoresearch_process", failing_autoresearch)

    async def run_prompt() -> None:
        auth_file = tmp_path / "auth.json"
        auth_file.write_text('{"tokens": {}}')
        agent = NeuricoHarborAgent(
            {
                "NEURICO_MODEL": "openai/test-model",
                "NEURICO_CODEX_AUTH_FILE": str(auth_file),
            }
        )
        session = await agent.new_session(cwd=str(tmp_path), mcp_servers=[])
        with pytest.raises(RuntimeError, match="status 7"):
            await agent.prompt(
                session_id=session.session_id,
                prompt=[{"type": "text", "text": "Run AutoResearch on this task"}],
            )

    asyncio.run(run_prompt())
    assert task_venv.read_text() == "owned by task\n"


def test_task_provided_mcp_servers_are_rejected_explicitly(tmp_path: Path) -> None:
    async def exercise() -> None:
        agent = NeuricoHarborAgent({"NEURICO_MODEL": "openai/test-model"})
        with pytest.raises(RequestError):
            await agent.new_session(
                cwd=str(tmp_path),
                mcp_servers=[{"name": "task-tools"}],
            )

    asyncio.run(exercise())


def test_stdio_acp_handshake_and_model_selection(tmp_path: Path) -> None:
    class RecordingClient(Client):
        async def request_permission(self, session_id, tool_call, options, **kwargs: Any):
            return {"outcome": {"outcome": "cancelled"}}

        async def session_update(self, session_id, update, **kwargs: Any) -> None:
            return None

    async def exercise_protocol() -> None:
        environment = dict(os.environ)
        environment["NEURICO_MODEL"] = "openai/test-model"
        async with spawn_agent_process(
            RecordingClient(),
            sys.executable,
            "-m",
            "neurico_harbor_agent",
            env=environment,
            cwd=tmp_path,
        ) as (connection, _process):
            initialized = await connection.initialize(protocol_version=PROTOCOL_VERSION)
            assert initialized.agent_info is not None
            assert initialized.agent_info.name == "neurico"

            session = await connection.new_session(cwd=str(tmp_path), mcp_servers=[])
            assert session.config_options is not None
            model_option = session.config_options[0]
            assert model_option.id == "model"
            assert model_option.current_value == "openai/test-model"

            response = await connection.set_config_option(
                session_id=session.session_id,
                config_id="model",
                value="openai/test-model",
            )
            assert response.config_options[0].current_value == "openai/test-model"

    asyncio.run(exercise_protocol())
