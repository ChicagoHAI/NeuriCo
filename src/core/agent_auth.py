"""Agent backbone authentication: which account the coding-agent CLI itself runs on.

This is deliberately separate from the *research* API keys that agents receive for the
calls they make inside their experiments (see ``core.azure_config`` and the agent-key
variables in ``.env``). The two layers combine freely:

    agent auth (this module)      research keys (azure_config / .env)
    ------------------------      -----------------------------------
    oauth  (default: the          OPENROUTER_KEY, ANTHROPIC_API_KEY, ... passed through;
            provider CLI's login) NEURICO_AZURE=1 adds the azure-models skill + Azure keys
    azure  (Codex on the Azure    same as above; nothing about the research keys changes
            OpenAI v1 endpoint;
            Claude Code on Azure
            AI Foundry when a
            Claude deployment
            exists)

Resolution order for the mode: explicit argument (``--agent-auth``) > ``NEURICO_AGENT_AUTH``
> ``oauth``. Every agent launch goes through ``core.agent_cli.build_agent_command`` and
``build_agent_environment``, which call into here, so one setting covers resource finder,
rule maker, experiment runner, paper writer, HITL workers, baselines and the safety planner.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Mapping, Optional

from core.azure_config import azure_active, azure_openai_base_url, azure_openai_deployments

AGENT_AUTH_ENV_VAR = "NEURICO_AGENT_AUTH"
AGENT_AUTH_MODES = ("oauth", "azure")
AZURE_CODEX_MODEL_ENV_VAR = "NEURICO_AZURE_CODEX_MODEL"
DEFAULT_AZURE_CODEX_MODEL = "gpt-5.6-sol"
CODEX_CATALOG_DIR_ENV_VAR = "NEURICO_CODEX_CATALOG_DIR"

_catalog_cache: Dict[str, Optional[Path]] = {}


def _env(env: Optional[Mapping[str, str]]) -> Mapping[str, str]:
    return os.environ if env is None else env


def resolve_agent_auth(explicit: Optional[str] = None, env: Optional[Mapping[str, str]] = None) -> str:
    """The configured mode, validated against ``AGENT_AUTH_MODES``."""
    mode = (explicit or _env(env).get(AGENT_AUTH_ENV_VAR) or "oauth").strip().lower()
    if mode not in AGENT_AUTH_MODES:
        raise ValueError(f"unknown agent auth mode {mode!r}; expected one of {AGENT_AUTH_MODES}")
    return mode


def supports(provider: str, mode: str, env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """None when the (provider, mode) pair is usable, else a human-readable reason it is not."""
    env = _env(env)
    if mode == "oauth":
        return None
    if not azure_active(env):
        return "NEURICO_AGENT_AUTH=azure needs NEURICO_AZURE=1 and AZURE_OPENAI_API_KEY in .env"
    if provider == "codex":
        return None if azure_openai_base_url(env) else "set AZURE_FOUNDRY_RESOURCE or AZURE_OPENAI_BASE_URL"
    if provider == "claude":
        if not (env.get("ANTHROPIC_FOUNDRY_RESOURCE") or env.get("ANTHROPIC_FOUNDRY_BASE_URL")):
            return "Claude Code on Azure needs ANTHROPIC_FOUNDRY_RESOURCE (or _BASE_URL) with a Claude deployment"
        return None
    return f"provider {provider!r} has no Azure backbone; use NEURICO_AGENT_AUTH=oauth"


def validate(provider: str, mode: str, env: Optional[Mapping[str, str]] = None) -> None:
    reason = supports(provider, mode, env)
    if reason:
        raise RuntimeError(f"agent auth {mode!r} is not available for provider {provider!r}: {reason}")


def agent_model(provider: str, mode: str, model: Optional[str], env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Model name the CLI should receive for this mode.

    On Azure, Codex must name a *deployment*. A gateway-style id (``openai/gpt-5.6-sol``)
    is reduced to its bare name; when no model is given the deployment comes from
    ``NEURICO_AZURE_CODEX_MODEL``, else the first ``AZURE_OPENAI_DEPLOYMENTS`` entry, else
    ``gpt-5.6-sol``.
    """
    env = _env(env)
    if mode != "azure" or provider != "codex":
        return model
    if model:
        return model.split("/", 1)[1] if model.startswith("openai/") else model
    deployments = azure_openai_deployments(env)
    return env.get(AZURE_CODEX_MODEL_ENV_VAR) or (deployments[0] if deployments else DEFAULT_AZURE_CODEX_MODEL)


def codex_azure_overrides(env: Optional[Mapping[str, str]] = None) -> List[str]:
    """``codex exec -c ...`` overrides routing Codex through the Azure OpenAI v1 endpoint.

    Mirrors the SAI review service's Azure lane: a custom provider with the Responses
    wire API and the key read from ``AZURE_OPENAI_API_KEY``. Overrides are passed on the
    command line so the mounted ``~/.codex`` login config is left untouched.
    """
    base_url = azure_openai_base_url(_env(env))
    if not base_url:
        raise RuntimeError("Codex on Azure needs AZURE_FOUNDRY_RESOURCE or AZURE_OPENAI_BASE_URL")
    return ["-c", 'model_provider="azure"',
            "-c", 'model_providers.azure.name="Azure OpenAI"',
            "-c", f'model_providers.azure.base_url="{base_url}"',
            "-c", 'model_providers.azure.env_key="AZURE_OPENAI_API_KEY"',
            "-c", 'model_providers.azure.wire_api="responses"']


def patched_codex_catalog(env: Optional[Mapping[str, str]] = None) -> Optional[Path]:
    """Codex model catalog with the ChatGPT-backend-only wire modes disabled.

    Codex's bundled catalog puts the gpt-5.6 family in "code mode" (a freeform ``exec``
    tool via Responses Lite and a v2 multi-agent tool). Those shapes only work on the
    first-party backend; Azure returns the call as a plain function call that Codex then
    rejects (openai/codex#31882). ``model_catalog_json`` is the supported escape hatch:
    dump the bundled catalog and null those fields. Returns None when codex is missing or
    nothing needs patching; the result is cached per process and per catalog directory.
    """
    env = _env(env)
    cache_dir = Path(env.get(CODEX_CATALOG_DIR_ENV_VAR) or Path(tempfile.gettempdir()) / f"neurico-codex-{os.getuid()}")
    key = str(cache_dir)
    if key in _catalog_cache:
        return _catalog_cache[key]
    result: Optional[Path] = None
    try:
        if shutil.which("codex"):
            cache_dir.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run(["codex", "debug", "models", "--bundled"], capture_output=True, text=True,
                                       timeout=60, check=True, stdin=subprocess.DEVNULL)
            catalog = json.loads(completed.stdout)
            models = catalog.get("models") if isinstance(catalog, dict) else catalog
            patched = False
            for entry in models or []:
                if not isinstance(entry, dict):
                    continue
                if (entry.get("use_responses_lite") or entry.get("tool_mode") in ("code_mode", "code_mode_only")
                        or entry.get("multi_agent_version") == "v2"):
                    entry["tool_mode"] = None
                    entry["use_responses_lite"] = False
                    entry["multi_agent_version"] = None
                    patched = True
            if patched:
                path = cache_dir / "models-catalog.json"
                path.write_text(json.dumps(catalog), encoding="utf-8")
                result = path
    except Exception:  # noqa: BLE001 - fall back to the unpatched catalog
        result = None
    _catalog_cache[key] = result
    return result


def claude_foundry_env(env: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """Env deltas that make Claude Code (>= 2.1.203) talk to Azure AI Foundry.

    ``CLAUDE_CODE_USE_FOUNDRY=1`` plus the Foundry key and resource (or base URL); the
    direct-API / gateway variables are blanked so no request can leak to another route.
    """
    env = _env(env)
    key = env.get("ANTHROPIC_FOUNDRY_API_KEY") or env.get("AZURE_OPENAI_API_KEY") or ""
    base_url = (env.get("ANTHROPIC_FOUNDRY_BASE_URL") or "").strip()
    resource = (env.get("ANTHROPIC_FOUNDRY_RESOURCE") or "").strip()
    if not key or not (base_url or resource):
        raise RuntimeError("Claude Code on Foundry needs ANTHROPIC_FOUNDRY_API_KEY (or AZURE_OPENAI_API_KEY) and "
                           "ANTHROPIC_FOUNDRY_RESOURCE (or ANTHROPIC_FOUNDRY_BASE_URL)")
    out = {"CLAUDE_CODE_USE_FOUNDRY": "1", "ANTHROPIC_FOUNDRY_API_KEY": key,
           "ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": "", "ANTHROPIC_BASE_URL": ""}
    if base_url:
        out["ANTHROPIC_FOUNDRY_BASE_URL"] = base_url
    else:
        out["ANTHROPIC_FOUNDRY_RESOURCE"] = resource
    return out


def command_args(provider: str, mode: str, env: Optional[Mapping[str, str]] = None) -> List[str]:
    """Extra CLI arguments for the provider command under this auth mode."""
    if mode != "azure":
        return []
    validate(provider, mode, env)
    if provider == "codex":
        args = codex_azure_overrides(env)
        catalog = patched_codex_catalog(env)
        if catalog:
            args += ["-c", f'model_catalog_json="{catalog}"']
        return args
    return []  # Claude Code is configured through the environment


def environment(provider: str, mode: str, env: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """Environment deltas for the provider command under this auth mode."""
    if mode != "azure":
        return {}
    validate(provider, mode, env)
    out = {AGENT_AUTH_ENV_VAR: mode}
    if provider == "claude":
        out.update(claude_foundry_env(env))
    return out


def describe(provider: str, mode: str, model: Optional[str] = None, env: Optional[Mapping[str, str]] = None) -> str:
    """One line for logs; never includes key values."""
    if mode == "oauth":
        return f"agent auth: oauth ({provider} CLI login)"
    target = azure_openai_base_url(_env(env)) if provider == "codex" else "Azure AI Foundry"
    return f"agent auth: azure ({provider} -> {target}, model {agent_model(provider, mode, model, env)})"
