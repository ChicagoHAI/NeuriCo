"""ACP adapter that supervises NeuriCo's existing AutoResearch mode."""

from __future__ import annotations

import asyncio
import codecs
import os
import shutil
import signal
import stat
import sys
import tempfile
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
        raise ValueError(
            "NEURICO_HARBOR_TIME_LIMIT_SECONDS must be a positive integer"
        ) from error
    if seconds <= 0:
        raise ValueError(
            "NEURICO_HARBOR_TIME_LIMIT_SECONDS must be a positive integer"
        )
    return seconds


def _path_entry_exists(path: Path) -> bool:
    """Return whether a path entry exists without following a symlink."""
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _remove_created_workspace_venv(workspace: Path, *, existed_before: bool) -> bool:
    """Remove only a workspace ``.venv`` created during this Harbor run."""
    if existed_before:
        return False

    workspace = workspace.resolve()
    if workspace == Path(workspace.anchor):
        raise RuntimeError(
            "Refusing to clean a workspace virtual environment under filesystem root"
        )

    target = workspace / ".venv"
    try:
        target_stat = target.lstat()
    except FileNotFoundError:
        return False

    if stat.S_ISDIR(target_stat.st_mode) and not stat.S_ISLNK(target_stat.st_mode):
        shutil.rmtree(target)
    else:
        # Never follow a run-created symlink. Unlink the workspace entry only.
        target.unlink()
    return True


async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    """Stop the isolated AutoResearch process group and its provider children."""
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
        return
    except TimeoutError:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        process.kill()
    await process.wait()


async def _stream_process_output(
    process: asyncio.subprocess.Process,
    emit: OutputHandler,
) -> int:
    """Forward arbitrary-size child output without imposing a line limit."""
    assert process.stdout is not None
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    while chunk := await process.stdout.read(64 * 1024):
        text = decoder.decode(chunk)
        if text:
            await emit(text)
    final_text = decoder.decode(b"", final=True)
    if final_text:
        await emit(final_text)
    return await process.wait()


async def run_autoresearch_process(
    *,
    task: HarborAutoResearchTask,
    connection: CodexInferenceConnection,
    base_environment: dict[str, str],
    iterations: int,
    time_limit_seconds: int | None,
    emit: OutputHandler,
    register_process: Callable[[asyncio.subprocess.Process], None],
) -> int:
    """Run the normal NeuriCo AutoResearch entrypoint and stream its output."""
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
        register_process(process)
        if time_limit_seconds is None:
            return await _stream_process_output(process, emit)
        try:
            return await asyncio.wait_for(
                _stream_process_output(process, emit),
                timeout=time_limit_seconds + _COOPERATIVE_SHUTDOWN_GRACE_SECONDS,
            )
        except TimeoutError:
            await emit(
                "NeuriCo did not finish cooperative deadline cleanup within "
                f"{_COOPERATIVE_SHUTDOWN_GRACE_SECONDS:g} seconds; terminating its process group.\n"
            )
            await _terminate_process_tree(process)
            return 1


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
        mcp_servers: list[HttpMcpServer | SseMcpServer | AcpMcpServer | McpServerStdio]
        | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        workspace = Path(cwd)
        if not workspace.is_absolute() or not workspace.is_dir():
            raise RequestError.invalid_params(
                {"cwd": "Harbor must provide an existing absolute task workspace"}
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
            await _terminate_process_tree(session.process)

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
        workspace_venv_existed = _path_entry_exists(task.workspace.resolve() / ".venv")
        session.cancelled = False
        session.active_task = asyncio.current_task()

        def register_process(process: asyncio.subprocess.Process) -> None:
            session.process = process

        try:
            return_code = await run_autoresearch_process(
                task=task,
                connection=connection,
                base_environment=self._environment,
                iterations=iterations,
                time_limit_seconds=time_limit_seconds,
                emit=lambda text: self._send_text(session_id, text),
                register_process=register_process,
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
            try:
                _remove_created_workspace_venv(
                    task.workspace,
                    existed_before=workspace_venv_existed,
                )
            finally:
                session.process = None
                session.active_task = None
