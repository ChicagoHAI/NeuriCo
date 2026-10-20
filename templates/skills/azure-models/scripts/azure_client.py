#!/usr/bin/env python3
"""Clients for the lab's Azure endpoints. Import it, or run it for a smoke test:

    python azure_client.py [--model gpt-4.1-mini] [--prompt "hi"]

Keys and URLs come from the environment (AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL or
AZURE_FOUNDRY_RESOURCE, ANTHROPIC_FOUNDRY_API_KEY, ANTHROPIC_FOUNDRY_BASE_URL or
ANTHROPIC_FOUNDRY_RESOURCE). Nothing here prints a key.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional


def openai_base_url() -> str:
    explicit = (os.environ.get("AZURE_OPENAI_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    resource = (os.environ.get("AZURE_FOUNDRY_RESOURCE") or "").strip()
    if not resource:
        raise RuntimeError("set AZURE_OPENAI_BASE_URL or AZURE_FOUNDRY_RESOURCE")
    return f"https://{resource}.openai.azure.com/openai/v1"


def openai_client():
    import openai
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    if not key:
        raise RuntimeError("AZURE_OPENAI_API_KEY is not set")
    return openai.OpenAI(base_url=openai_base_url(), api_key=key)


def anthropic_client():
    import anthropic
    key = os.environ.get("ANTHROPIC_FOUNDRY_API_KEY") or os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = (os.environ.get("ANTHROPIC_FOUNDRY_BASE_URL") or "").strip()
    resource = (os.environ.get("ANTHROPIC_FOUNDRY_RESOURCE") or "").strip()
    if not key or not (base_url or resource):
        raise RuntimeError("set ANTHROPIC_FOUNDRY_API_KEY and ANTHROPIC_FOUNDRY_RESOURCE (or _BASE_URL)")
    if base_url:
        return anthropic.AnthropicFoundry(base_url=base_url, api_key=key)
    return anthropic.AnthropicFoundry(resource=resource, api_key=key)


def chat(model: str, prompt: str, *, max_tokens: int = 256, system: Optional[str] = None,
         temperature: Optional[float] = None) -> str:
    """One chat turn against an Azure OpenAI deployment (or a Foundry Claude deployment if the
    name starts with 'claude')."""
    if model.startswith("claude"):
        client = anthropic_client()
        kwargs = {"model": model, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt}]}
        if system:
            kwargs["system"] = system
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = client.messages.create(**kwargs)
        return "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    client = openai_client()
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    kwargs = {"model": model, "messages": messages, "max_completion_tokens": max_tokens}
    if temperature is not None:
        kwargs["temperature"] = temperature
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--prompt", default="Reply with the single word: ready")
    args = parser.parse_args()
    try:
        print(chat(args.model, args.prompt, max_tokens=16))
    except Exception as e:  # noqa: BLE001
        print(f"{type(e).__name__}: {str(e)[:300]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
