"""Azure research keys: one switch that exposes the lab's Azure endpoints to every agent.

Configuration (``.env``):

    NEURICO_AZURE=1                 activate: agents get the azure-models skill and the keys below
    AZURE_OPENAI_API_KEY=...        Azure OpenAI resource key
    AZURE_FOUNDRY_RESOURCE=...      resource name -> https://<resource>.openai.azure.com/openai/v1
    AZURE_OPENAI_BASE_URL=...       optional explicit base URL (wins over the resource name)
    AZURE_OPENAI_DEPLOYMENTS=...    optional comma-separated deployment names agents may use
    ANTHROPIC_FOUNDRY_API_KEY=...   optional: Claude on Azure AI Foundry (falls back to AZURE_OPENAI_API_KEY)
    ANTHROPIC_FOUNDRY_RESOURCE=...  resource name -> https://<resource>.services.ai.azure.com/anthropic/
    ANTHROPIC_FOUNDRY_BASE_URL=...  optional explicit base URL
The coding agents' own account (OAuth login vs Azure) is a separate setting handled by
``core.agent_auth`` (``NEURICO_AGENT_AUTH``). Nothing here prints or logs key values.
"""

from __future__ import annotations

import os
from typing import Dict, List, Mapping, Optional

AZURE_SKILL = "azure-models"


def _get(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def azure_active(env: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    flag = _get(env, "NEURICO_AZURE").lower()
    return flag in ("1", "true", "yes", "on") and bool(_get(env, "AZURE_OPENAI_API_KEY"))


def azure_openai_base_url(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    env = os.environ if env is None else env
    explicit = _get(env, "AZURE_OPENAI_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    resource = _get(env, "AZURE_FOUNDRY_RESOURCE")
    return f"https://{resource}.openai.azure.com/openai/v1" if resource else None


def azure_openai_deployments(env: Optional[Mapping[str, str]] = None) -> List[str]:
    env = os.environ if env is None else env
    return [d.strip() for d in _get(env, "AZURE_OPENAI_DEPLOYMENTS").split(",") if d.strip()]


def foundry_anthropic_base_url(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    env = os.environ if env is None else env
    explicit = _get(env, "ANTHROPIC_FOUNDRY_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    resource = _get(env, "ANTHROPIC_FOUNDRY_RESOURCE")
    return f"https://{resource}.services.ai.azure.com/anthropic" if resource else None


def foundry_anthropic_key(env: Optional[Mapping[str, str]] = None) -> str:
    env = os.environ if env is None else env
    return _get(env, "ANTHROPIC_FOUNDRY_API_KEY") or _get(env, "AZURE_OPENAI_API_KEY")


def agent_env_overrides(provider: str, env: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """What to add to an agent's environment for the current Azure settings."""
    env = os.environ if env is None else env
    if not azure_active(env):
        return {}
    out: Dict[str, str] = {"NEURICO_AZURE": "1"}
    base_url = azure_openai_base_url(env)
    if base_url:
        out["AZURE_OPENAI_BASE_URL"] = base_url
    anthropic_url = foundry_anthropic_base_url(env)
    if anthropic_url:
        out["ANTHROPIC_FOUNDRY_BASE_URL"] = anthropic_url
    return out


def describe(env: Optional[Mapping[str, str]] = None) -> str:
    """One line for logs; never includes key values."""
    env = os.environ if env is None else env
    if not azure_active(env):
        return "Azure: off"
    parts = [f"Azure: on (openai {azure_openai_base_url(env) or 'unset'}"]
    if foundry_anthropic_base_url(env):
        parts.append(f"anthropic {foundry_anthropic_base_url(env)}")
    return ", ".join(parts) + ")"
