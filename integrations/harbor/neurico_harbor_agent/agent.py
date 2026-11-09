"""ACP adapter that supervises NeuriCo's existing AutoResearch mode."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
import signal
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from acp import (
    Agent,
    InitializeResponse,
    NewSessionResponse,
    PromptResponse,
    RequestError,
    text_block,
    update_agent_message,
)
from acp.interfaces import Client
from acp.schema import (
    AcpMcpServer,
    AudioContentBlock,
    ClientCapabilities,
    EmbeddedResourceContentBlock,
    HttpMcpServer,
    ImageContentBlock,
    Implementation,
    McpServerStdio,
    ResourceContentBlock,
    SessionConfigOptionSelect,
    SessionConfigSelectOption,
    SetSessionConfigOptionResponse,
    SseMcpServer,
    TextContentBlock,
)

from .runtime import (
    CodexInferenceConnection,
    HarborAutoResearchTask,
    build_autoresearch_environment,
)
from .artifacts import (
    DEFAULT_HARBOR_ARTIFACT_ROOT,
    HarborArtifactStore,
    HarborRunBundleTransaction,
    TraceRedactor,
    WorkspaceBaseline,
    capture_workspace_baseline,
    export_harbor_research_artifacts,
    write_minimal_harbor_run_bundle,
)
from .process_control import (
    owned_process_group_ids as _owned_process_group_ids,
    signal_process_groups as _signal_process_groups,
)
from .scratch import (
    DEFAULT_HARBOR_SCRATCH_ROOT,
    EphemeralRunScratch,
    PrivateOutputSpool,
)

ContentBlock = (
    TextContentBlock
    | ImageContentBlock
    | AudioContentBlock
    | ResourceContentBlock
    | EmbeddedResourceContentBlock
)
OutputHandler = Callable[[str], Awaitable[None]]
_TIME_LIMIT_EXIT_CODE = 124
_COOPERATIVE_SHUTDOWN_GRACE_SECONDS = 30.0
_CANCELLATION_GRACE_SECONDS = 30.0
_FORCED_TERMINATION_GRACE_SECONDS = 5.0
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class _Session:
    cwd: Path
    model: str
    cancelled: bool = False
    active_task: asyncio.Task[Any] | None = None
    process: asyncio.subprocess.Process | None = None


def _text_from_prompt(prompt: list[ContentBlock]) -> str:
    """Return Harbor's text prompt without normalizing or reformatting it."""
    text_parts: list[str] = []
    for block in prompt:
        text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
        if isinstance(text, str):
            text_parts.append(text)
    if not text_parts:
        raise RequestError.invalid_params(
            {"prompt": "NeuriCo's Harbor adapter requires a text instruction"}
        )
    return "".join(text_parts)


def _autoresearch_iterations(environment: dict[str, str]) -> int:
    raw = environment.get("NEURICO_HARBOR_AUTORESEARCH_ITERATIONS", "1")
    try:
        iterations = int(raw)
    except ValueError as error:
        raise ValueError("NEURICO_HARBOR_AUTORESEARCH_ITERATIONS must be an integer") from error
    if iterations < 1:
        raise ValueError("NEURICO_HARBOR_AUTORESEARCH_ITERATIONS must be at least 1")
    return iterations


def _autoresearch_time_limit(environment: dict[str, str]) -> int | None:
    raw = environment.get("NEURICO_HARBOR_TIME_LIMIT_SECONDS")
    if raw is None or not raw.strip():
        return None
    try:
        seconds = int(raw)
    except ValueError as error:
        raise ValueError("NEURICO_HARBOR_TIME_LIMIT_SECONDS must be a positive integer") from error
    if seconds <= 0:
        raise ValueError("NEURICO_HARBOR_TIME_LIMIT_SECONDS must be a positive integer")
    return seconds


async def _terminate_process_tree(
    process: asyncio.subprocess.Process,
    *,
    request_cooperative_stop: bool = False,
) -> None:
    """Stop AutoResearch and every separately grouped provider descendant."""
    process_groups = _owned_process_group_ids(process.pid)
    if request_cooperative_stop and process.returncode is None:
        # The child translates SIGINT into NeuriCo's durable native stop request.
        # Providers then observe that request and terminate their own groups.
        try:
            process.send_signal(signal.SIGINT)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=_CANCELLATION_GRACE_SECONDS)
        except TimeoutError:
            pass
        process_groups.update(_owned_process_group_ids(process.pid))

    if process.returncode is not None and not process_groups:
        return

    _signal_process_groups(process_groups, signal.SIGTERM)
    if process.returncode is None:
        try:
            await asyncio.wait_for(process.wait(), timeout=_FORCED_TERMINATION_GRACE_SECONDS)
        except TimeoutError:
            pass

    process_groups.update(_owned_process_group_ids(process.pid))
    _signal_process_groups(process_groups, signal.SIGKILL)
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()


async def _stream_process_output(
    process: asyncio.subprocess.Process,
    output_spool: PrivateOutputSpool | None = None,
) -> int:
    """Drain mixed-authority output into an unlinked parent-held spool."""
    if process.stdout is None:
        raise RuntimeError("NeuriCo child output was not connected to the supervisor")
    while chunk := await process.stdout.read(64 * 1024):
        if output_spool is not None:
            try:
                output_spool.append_output(chunk)
            except Exception:
                # Scratch is observational and cannot interrupt output
                # draining or change the supervised child's result.
                pass
    return await process.wait()


async def _emit_trace_preservation_notice(emit: OutputHandler, status: str) -> None:
    if status == "partial":
        message = (
            "WARNING: NeuriCo published a metadata-only or partial trace bundle; "
            "inspect its collection record before using it for analysis.\n"
        )
    elif status == "unavailable":
        message = (
            "WARNING: NeuriCo could not publish a trace bundle for this run. "
            "The research outcome is unchanged.\n"
        )
    else:
        return
    try:
        await emit(message)
    except BaseException:
        # Trace reporting is observational and must not replace the child result.
        pass


async def run_autoresearch_process(
    *,
    task: HarborAutoResearchTask,
    connection: CodexInferenceConnection,
    base_environment: dict[str, str],
    iterations: int,
    time_limit_seconds: int | None,
    run_id: str,
    emit: OutputHandler,
    register_process: Callable[[asyncio.subprocess.Process], bool],
    cancellation_requested: Callable[[], bool] | None = None,
) -> int:
    """Supervise AutoResearch and finalize its trace only after the child stops."""
    started_at = datetime.now(timezone.utc).isoformat()
    started_monotonic = time.monotonic()
    process: asyncio.subprocess.Process | None = None
    output_task: asyncio.Task[int] | None = None
    return_code: int | None = None
    forced_termination = False
    supervisor_error_type: str | None = None
    run_configuration = {
        "workflow": "autoresearch",
        "run_id": run_id,
        "provider": "codex",
        "requested_model": connection.requested_model,
        "hitl_mode": "auto",
        "scoring_enabled": True,
        "benchmark_mode": True,
        "autoresearch_iterations": iterations,
        "time_limit_seconds": time_limit_seconds,
        "workspace_mode": "embedded",
    }
    workspace_baseline = WorkspaceBaseline(
        fingerprints={},
        root_identity=None,
        complete=False,
        stop_reason="inventory_failed",
    )
    redactor = TraceRedactor()
    trace_preflight_ready = False
    trace_preflight_error_type: str | None = None
    artifact_store: HarborArtifactStore | None = None
    output_spool: PrivateOutputSpool | None = None
    scratch: EphemeralRunScratch | None = None

    try:
        output_spool = PrivateOutputSpool.create()
    except Exception:
        # Private retention is observational and cannot affect the research
        # run or the independently sanitized public bundle.
        output_spool = None

    # Retain parent-held directory identities before the child can replace
    # filesystem paths. Harbor's artifact channel remains agent-controlled;
    # these handles protect the collector's own unpublished transaction, not a
    # deployment-level trust boundary.
    try:
        artifact_store = HarborArtifactStore.open(DEFAULT_HARBOR_ARTIFACT_ROOT)
    except Exception as storage_error:
        trace_preflight_error_type = type(storage_error).__name__
    else:
        # Capture preparation is observational. If the private redactor or
        # baseline inventory fails, the established store can still publish a
        # metadata-only bundle after the child stops.
        try:
            redactor = TraceRedactor.from_sources(
                base_environment,
                credential_file=connection.auth_file,
                additional_values=(connection.token,),
            )
            workspace_baseline = capture_workspace_baseline(
                task.workspace,
                redactor=redactor,
            )
            trace_preflight_ready = True
        except Exception as trace_preflight_error:
            trace_preflight_error_type = type(trace_preflight_error).__name__

    try:
        with tempfile.TemporaryDirectory(prefix="neurico-harbor-") as control_dir_value:
            control_dir = Path(control_dir_value)
            instruction_file = control_dir / "instruction.txt"
            instruction_file.write_text(task.instruction, encoding="utf-8")
            ideas_dir = control_dir / "ideas"
            codex_home = control_dir / "codex-home"
            environment = build_autoresearch_environment(
                base_environment,
                connection,
                ideas_dir=ideas_dir,
                codex_home=codex_home,
            )

            command = [
                sys.executable,
                "-m",
                "neurico_harbor_agent.process_control",
                sys.executable,
                "-m",
                "neurico_harbor_agent.run_autoresearch",
                "--instruction-file",
                str(instruction_file),
                "--workspace",
                str(task.workspace),
                "--ideas-dir",
                str(ideas_dir),
                "--iterations",
                str(iterations),
            ]
            if time_limit_seconds is not None:
                command.extend(["--time-limit-seconds", str(time_limit_seconds)])

            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=task.workspace,
                env=environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            output_task = asyncio.create_task(_stream_process_output(process, output_spool))
            cancelled_before_registration = register_process(process)
            if cancelled_before_registration:
                await _terminate_process_tree(
                    process,
                    request_cooperative_stop=True,
                )
                return_code = await output_task
                return return_code
            if time_limit_seconds is None:
                return_code = await output_task
                return return_code
            try:
                return_code = await asyncio.wait_for(
                    asyncio.shield(output_task),
                    timeout=time_limit_seconds + _COOPERATIVE_SHUTDOWN_GRACE_SECONDS,
                )
                return return_code
            except TimeoutError:
                forced_termination = True
                await emit(
                    "NeuriCo did not finish cooperative deadline cleanup within "
                    f"{_COOPERATIVE_SHUTDOWN_GRACE_SECONDS:g} seconds; terminating its process tree.\n"
                )
                await _terminate_process_tree(process)
                await output_task
                return_code = 1
                return return_code
    except BaseException as error:
        supervisor_error_type = type(error).__name__
        raise
    finally:
        if process is not None and process.returncode is None:
            try:
                await _terminate_process_tree(process)
            except BaseException as cleanup_error:
                supervisor_error_type = supervisor_error_type or type(cleanup_error).__name__
        if output_task is not None:
            try:
                drained_return_code = await output_task
                if return_code is None:
                    return_code = drained_return_code
            except BaseException as output_error:
                supervisor_error_type = supervisor_error_type or type(output_error).__name__
        if return_code is None and process is not None:
            return_code = process.returncode

        trace_status = "scope_complete"
        # Writing even sanitized workspace data while the child remains alive
        # would violate the producer boundary.
        child_stopped = process is None or process.returncode is not None
        if child_stopped:
            try:
                scratch = EphemeralRunScratch.create(
                    root=DEFAULT_HARBOR_SCRATCH_ROOT,
                    run_id=run_id,
                )
                if output_spool is not None:
                    output_spool.transfer_to(scratch)
            except Exception:
                # The public trace remains independently collectable.
                scratch = None
        if not child_stopped:
            trace_status = "unavailable"
        elif artifact_store is None:
            trace_status = "unavailable"
        else:
            try:
                was_cancelled = bool(cancellation_requested and cancellation_requested())
            except Exception:
                was_cancelled = False
            if process is None:
                outcome = "spawn_failure"
            elif was_cancelled:
                outcome = "cancelled"
            elif forced_termination:
                outcome = "forced_timeout"
            elif supervisor_error_type is not None:
                outcome = "supervisor_error"
            elif return_code == 0:
                outcome = "success"
            elif return_code == _TIME_LIMIT_EXIT_CODE:
                outcome = "time_limit"
            else:
                outcome = "failed"
            elapsed_seconds = time.monotonic() - started_monotonic
            transaction: HarborRunBundleTransaction | None = None
            try:
                transaction = artifact_store.begin(run_id)
                if not trace_preflight_ready:
                    manifest = write_minimal_harbor_run_bundle(
                        run_id=run_id,
                        artifact_dir=transaction.staging_dir,
                        run_configuration=run_configuration,
                        started_at=started_at,
                        elapsed_seconds=elapsed_seconds,
                        outcome=outcome,
                        return_code=return_code,
                        supervisor_error_type=supervisor_error_type,
                        export_error_type=(
                            trace_preflight_error_type or "TracePreflightInitializationError"
                        ),
                        redactor=redactor,
                    )
                    trace_status = "partial"
                else:
                    manifest = export_harbor_research_artifacts(
                        run_id=run_id,
                        workspace=task.workspace,
                        workspace_baseline=workspace_baseline,
                        artifact_dir=transaction.staging_dir,
                        project_root=_PROJECT_ROOT,
                        instruction=task.instruction,
                        run_configuration=run_configuration,
                        started_at=started_at,
                        elapsed_seconds=elapsed_seconds,
                        outcome=outcome,
                        return_code=return_code,
                        supervisor_error_type=supervisor_error_type,
                        redactor=redactor,
                        scratch=scratch,
                    )
                    if manifest.get("collection_status") != "scope_complete":
                        trace_status = "partial"
                transaction.commit()
            except Exception as export_error:
                if transaction is not None:
                    try:
                        artifact_dir = transaction.reset()
                        manifest = write_minimal_harbor_run_bundle(
                            run_id=run_id,
                            artifact_dir=artifact_dir,
                            run_configuration=run_configuration,
                            started_at=started_at,
                            elapsed_seconds=elapsed_seconds,
                            outcome=outcome,
                            return_code=return_code,
                            supervisor_error_type=supervisor_error_type,
                            export_error_type=type(export_error).__name__,
                            redactor=redactor,
                        )
                        transaction.commit()
                        trace_status = "partial"
                    except Exception:
                        transaction.abort()
                        trace_status = "unavailable"
                else:
                    trace_status = "unavailable"
        if artifact_store is not None:
            artifact_store.close()
        if scratch is not None:
            try:
                scratch.finalize()
            except Exception:
                pass
        if output_spool is not None:
            output_spool.close()
        await _emit_trace_preservation_notice(emit, trace_status)


class NeuricoHarborAgent(Agent):
    """A Harbor ACP surface for NeuriCo's fresh AutoResearch workflow."""

    def __init__(self, environment: dict[str, str] | None = None) -> None:
        self._environment = dict(os.environ if environment is None else environment)
        self._sessions: dict[str, _Session] = {}
        self._conn: Client | None = None

    def on_connect(self, conn: Client) -> None:
        self._conn = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        client_info: Implementation | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        return InitializeResponse(
            protocol_version=protocol_version,
            agent_info=Implementation(name="neurico", version="0.2.0"),
        )

    def _requested_model(self) -> str:
        model = self._environment.get("HARBOR_ACP_REQUESTED_MODEL") or self._environment.get(
            "NEURICO_MODEL"
        )
        if not model:
            raise RequestError.invalid_params(
                {
                    "model": (
                        "Harbor did not provide HARBOR_ACP_REQUESTED_MODEL; "
                        "set NEURICO_MODEL for a direct ACP launch"
                    )
                }
            )
        return model

    def _config_options(self, session_id: str) -> list[SessionConfigOptionSelect]:
        model = self._sessions[session_id].model
        return [
            SessionConfigOptionSelect(
                id="model",
                name="Model",
                description="Model selected by Harbor for every NeuriCo AutoResearch agent",
                category="model",
                type="select",
                current_value=model,
                options=[
                    SessionConfigSelectOption(
                        value=model,
                        name=model,
                        description="Harbor-requested inference model",
                    )
                ],
            )
        ]

    async def new_session(
        self,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: (
            list[HttpMcpServer | SseMcpServer | AcpMcpServer | McpServerStdio] | None
        ) = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        workspace = Path(cwd)
        if not workspace.is_absolute() or not workspace.is_dir():
            raise RequestError.invalid_params(
                {"cwd": "Harbor must provide an existing absolute task workspace"}
            )
        if mcp_servers:
            raise RequestError.invalid_params(
                {
                    "mcp_servers": (
                        "NeuriCo's Harbor adapter does not currently support "
                        "task-provided MCP servers"
                    )
                }
            )
        session_id = uuid4().hex
        self._sessions[session_id] = _Session(cwd=workspace, model=self._requested_model())
        return NewSessionResponse(
            session_id=session_id,
            config_options=self._config_options(session_id),
        )

    async def set_config_option(
        self,
        config_id: str,
        session_id: str,
        value: str | bool,
        **kwargs: Any,
    ) -> SetSessionConfigOptionResponse:
        session = self._sessions.get(session_id)
        if session is None:
            raise RequestError.resource_not_found(session_id)
        if config_id != "model" or not isinstance(value, str):
            raise RequestError.invalid_params(
                {"config_id": "Only the string-valued 'model' option is supported"}
            )
        requested = self._requested_model()
        if value != requested:
            raise RequestError.invalid_params(
                {"value": f"Model must match Harbor's requested model: {requested}"}
            )
        session.model = value
        return SetSessionConfigOptionResponse(config_options=self._config_options(session_id))

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        session.cancelled = True
        if session.process is not None and session.process.returncode is None:
            await _terminate_process_tree(
                session.process,
                request_cooperative_stop=True,
            )

    async def _send_text(self, session_id: str, text: str) -> None:
        if self._conn is None or not text:
            return
        await self._conn.session_update(
            session_id=session_id,
            update=update_agent_message(text_block(text)),
            source="neurico",
        )

    async def prompt(
        self,
        session_id: str,
        prompt: list[ContentBlock],
        **kwargs: Any,
    ) -> PromptResponse:
        session = self._sessions.get(session_id)
        if session is None:
            raise RequestError.resource_not_found(session_id)
        if session.active_task is not None:
            raise RequestError.invalid_params(
                {"session_id": "A NeuriCo AutoResearch run is already active"}
            )

        task = HarborAutoResearchTask(
            instruction=_text_from_prompt(prompt),
            workspace=session.cwd,
        )
        connection = CodexInferenceConnection.from_environment(
            self._environment,
            requested_model=session.model,
        )
        iterations = _autoresearch_iterations(self._environment)
        time_limit_seconds = _autoresearch_time_limit(self._environment)
        session.cancelled = False
        session.active_task = asyncio.current_task()

        def register_process(process: asyncio.subprocess.Process) -> bool:
            session.process = process
            return session.cancelled

        try:
            return_code = await run_autoresearch_process(
                task=task,
                connection=connection,
                base_environment=self._environment,
                iterations=iterations,
                time_limit_seconds=time_limit_seconds,
                run_id=f"{session_id}-{uuid4().hex}",
                emit=lambda text: self._send_text(session_id, text),
                register_process=register_process,
                cancellation_requested=lambda: session.cancelled,
            )
            if session.cancelled:
                return PromptResponse(stop_reason="cancelled")
            if return_code == _TIME_LIMIT_EXIT_CODE:
                await self._send_text(
                    session_id,
                    "NeuriCo reached its configured run-time limit and completed native "
                    "AutoResearch budget finalization; the workspace is ready for Harbor's "
                    "verifier.\n",
                )
                return PromptResponse(stop_reason="end_turn")
            if return_code != 0:
                raise RuntimeError(
                    f"NeuriCo AutoResearch exited unsuccessfully with status {return_code}"
                )
            await self._send_text(
                session_id,
                "NeuriCo AutoResearch completed; the workspace is at its retained best checkpoint.\n",
            )
            return PromptResponse(stop_reason="end_turn")
        finally:
            if session.process is not None and session.process.returncode is None:
                await _terminate_process_tree(session.process)
            session.process = None
            session.active_task = None
