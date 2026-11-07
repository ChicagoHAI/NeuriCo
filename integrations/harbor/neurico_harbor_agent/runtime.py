"""Harbor-to-NeuriCo input and Codex runtime configuration helpers."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from src.cli.submit_local import _convert_without_llm


@dataclass(frozen=True)
class HarborAutoResearchTask:
    """One Harbor instruction executed by NeuriCo AutoResearch."""

    instruction: str
    workspace: Path

    def __post_init__(self) -> None:
        if not self.instruction.strip():
            raise ValueError("Harbor instruction must not be empty")
        if not self.workspace.is_absolute():
            raise ValueError("Harbor workspace must be an absolute path")
        if not self.workspace.is_dir():
            raise ValueError(f"Harbor workspace does not exist: {self.workspace}")


@dataclass(frozen=True)
class CodexInferenceConnection:
    """Authentication and model routing for NeuriCo's Codex CLI provider."""

    requested_model: str
    mode: Literal["chatgpt", "openai-api", "hosted-gateway"]
    auth_file: Path | None = None
    token: str | None = None
    base_url: str | None = None

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str],
        *,
        requested_model: str,
    ) -> CodexInferenceConnection:
        hosted_token = environment.get("HOSTED_INFERENCE_TOKEN")
        hosted_url = environment.get("HOSTED_INFERENCE_URL")
        if hosted_token or hosted_url:
            if not hosted_token or not hosted_url:
                raise ValueError(
                    "Hosted Codex mode requires both HOSTED_INFERENCE_TOKEN and "
                    "HOSTED_INFERENCE_URL"
                )
            return cls(
                requested_model=requested_model,
                mode="hosted-gateway",
                token=hosted_token,
                base_url=hosted_url,
            )

        auth_file = _find_codex_auth_file(environment)
        if auth_file is not None:
            _validate_direct_openai_model(requested_model)
            return cls(
                requested_model=requested_model,
                mode="chatgpt",
                auth_file=auth_file,
            )

        api_key = environment.get("OPENAI_API_KEY")
        if api_key:
            _validate_direct_openai_model(requested_model)
            return cls(
                requested_model=requested_model,
                mode="openai-api",
                token=api_key,
                base_url=environment.get("OPENAI_BASE_URL") or "https://api.openai.com/v1",
            )

        raise ValueError(
            "Missing Codex authentication: mount a logged-in auth.json and set "
            "NEURICO_CODEX_AUTH_FILE, set CODEX_HOME to a logged-in directory, "
            "or provide OPENAI_API_KEY"
        )

    @property
    def backend_model(self) -> str:
        """Return the model spelling Codex should send to its selected backend."""
        if self.mode == "hosted-gateway":
            return self.requested_model
        provider, separator, model = self.requested_model.partition("/")
        if separator and provider == "openai":
            return model
        return self.requested_model

    def prepare_codex_home(self, codex_home: Path) -> dict[str, str]:
        """Create an isolated Codex home and return its secret environment."""
        codex_home.mkdir(parents=True, exist_ok=False)
        codex_home.chmod(0o700)

        if self.auth_file is not None:
            destination = codex_home / "auth.json"
            shutil.copyfile(self.auth_file, destination)
            destination.chmod(0o600)

        config_lines = [
            f"model = {json.dumps(self.backend_model)}",
            'cli_auth_credentials_store = "file"',
        ]
        secret_environment: dict[str, str] = {}
        if self.mode == "openai-api":
            config_lines.extend(
                [
                    'model_provider = "neurico_openai"',
                    "",
                    "[model_providers.neurico_openai]",
                    'name = "OpenAI API"',
                    f"base_url = {json.dumps(self.base_url)}",
                    'env_key = "OPENAI_API_KEY"',
                    'wire_api = "responses"',
                ]
            )
            assert self.token is not None
            secret_environment["OPENAI_API_KEY"] = self.token
        elif self.mode == "hosted-gateway":
            config_lines.extend(
                [
                    'model_provider = "harbor_hosted"',
                    "",
                    "[model_providers.harbor_hosted]",
                    'name = "Harbor hosted inference"',
                    f"base_url = {json.dumps(self.base_url)}",
                    'env_key = "HOSTED_INFERENCE_TOKEN"',
                    'wire_api = "responses"',
                ]
            )
            assert self.token is not None
            secret_environment["HOSTED_INFERENCE_TOKEN"] = self.token

        config_path = codex_home / "config.toml"
        config_path.write_text("\n".join(config_lines) + "\n", encoding="utf-8")
        config_path.chmod(0o600)
        return secret_environment


def _validate_direct_openai_model(requested_model: str) -> None:
    provider, separator, _ = requested_model.partition("/")
    if separator and provider != "openai":
        raise ValueError(
            "Direct Codex authentication requires an OpenAI model; use hosted "
            "gateway mode for other model namespaces"
        )


def _find_codex_auth_file(environment: Mapping[str, str]) -> Path | None:
    explicit = environment.get("NEURICO_CODEX_AUTH_FILE")
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            raise ValueError("NEURICO_CODEX_AUTH_FILE must be an absolute path")
        if not path.is_file():
            raise ValueError(f"Codex authentication file does not exist: {path}")
        return path

    codex_home = environment.get("CODEX_HOME")
    if codex_home:
        path = Path(codex_home) / "auth.json"
        if path.is_file():
            return path

    home = environment.get("HOME")
    if home:
        path = Path(home) / ".codex" / "auth.json"
        if path.is_file():
            return path
    return None


def _title_from_instruction(instruction: str) -> str:
    """Derive only the schema-required title; preserve the full task elsewhere."""
    first_line = next((line.strip() for line in instruction.splitlines() if line.strip()), "")
    first_line = re.sub(r"^#{1,6}\s+", "", first_line)
    first_line = re.sub(r"\s+", " ", first_line).strip()
    title = first_line[:197].rstrip()
    if len(title) < 10:
        title = f"Harbor AutoResearch: {title or 'Research task'}"
    return title


def build_harbor_idea(task: HarborAutoResearchTask) -> dict[str, Any]:
    """Use NeuriCo's local converter to wrap a Harbor instruction as an idea.

    The complete instruction is retained in ``background.description``, which
    NeuriCo already promotes as high-priority user instructions when generating
    research and AutoResearch prompts.
    """
    converted = _convert_without_llm(
        {
            "path": "harbor://instruction",
            "title": _title_from_instruction(task.instruction),
            "description": task.instruction,
            "tags": ["harbor", "autoresearch"],
            "author": None,
            "raw_text": task.instruction,
        }
    )["parsed"]
    idea = converted["idea"]
    metadata = idea.setdefault("metadata", {})
    metadata.update(
        {
            "source": "harbor",
            "local_workspace": str(task.workspace),
            "instruction_sha256": sha256(task.instruction.encode("utf-8")).hexdigest(),
        }
    )
    return converted


def codex_launcher_directory() -> Path:
    """Return the locked adapter script directory containing the Codex launcher."""
    # Keep the virtual-environment path: its Python is often a symlink to uv's
    # managed interpreter, while console scripts live beside that symlink.
    scripts = Path(sys.executable).parent
    launcher = scripts / "codex"
    if not launcher.is_file():
        raise RuntimeError(f"NeuriCo's locked Codex launcher is missing: {launcher}")
    return scripts


def build_autoresearch_environment(
    base_environment: Mapping[str, str],
    connection: CodexInferenceConnection,
    *,
    ideas_dir: Path,
    codex_home: Path,
) -> dict[str, str]:
    """Build the environment inherited by NeuriCo and all Codex agents."""
    environment = dict(base_environment)
    environment.update(connection.prepare_codex_home(codex_home))
    environment["CODEX_HOME"] = str(codex_home)
    environment["NEURICO_IDEAS"] = str(ideas_dir)
    environment["PYTHONUNBUFFERED"] = "1"
    current_path = environment.get("PATH", os.defpath)
    environment["PATH"] = f"{codex_launcher_directory()}{os.pathsep}{current_path}"
    return environment
