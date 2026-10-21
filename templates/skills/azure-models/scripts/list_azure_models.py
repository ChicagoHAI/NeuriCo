#!/usr/bin/env python3
"""Report which Azure deployments answer right now.

    python list_azure_models.py                      # probe the default candidate names
    python list_azure_models.py --probe gpt-6-astra my-deployment
    python list_azure_models.py --json               # machine-readable

Azure's v1 endpoint lists the model catalog, not your deployments, so this sends a
one-token request to each candidate name and reports the ones that answer. Keys are read
from the environment and never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from azure_client import anthropic_client, openai_client  # noqa: E402

DEFAULT_OPENAI = ["gpt-6-astra", "gpt-6", "gpt-5.6-sol", "gpt-5.6", "gpt-5.5", "gpt-5.4", "gpt-5",
                  "gpt-5-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini", "o3", "o4-mini"]
DEFAULT_ANTHROPIC = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1",
                     "claude-opus-4-8", "claude-sonnet-4-5", "claude-haiku-4-5"]


def probe_openai(names):
    out = {}
    try:
        client = openai_client()
    except Exception as e:  # noqa: BLE001
        return {"_error": f"{type(e).__name__}: {str(e)[:120]}"}
    for name in names:
        try:
            resp = client.chat.completions.create(model=name, max_completion_tokens=1,
                                                  messages=[{"role": "user", "content": "hi"}])
            out[name] = {"ok": True, "model": resp.model}
        except Exception as e:  # noqa: BLE001
            out[name] = {"ok": False, "error": type(e).__name__}
    return out


def probe_anthropic(names):
    out = {}
    try:
        client = anthropic_client()
    except Exception as e:  # noqa: BLE001
        return {"_error": f"{type(e).__name__}: {str(e)[:120]}"}
    for name in names:
        try:
            resp = client.messages.create(model=name, max_tokens=1, messages=[{"role": "user", "content": "hi"}])
            out[name] = {"ok": True, "model": resp.model}
        except Exception as e:  # noqa: BLE001
            out[name] = {"ok": False, "error": type(e).__name__}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--probe", nargs="*", help="candidate deployment names (default: common names)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    configured = [d.strip() for d in (os.environ.get("AZURE_OPENAI_DEPLOYMENTS") or "").split(",") if d.strip()]
    names = args.probe or (configured + [n for n in DEFAULT_OPENAI if n not in configured])
    openai_names = [n for n in names if not n.startswith("claude")]
    anthropic_names = [n for n in names if n.startswith("claude")] or ([] if args.probe else DEFAULT_ANTHROPIC)
    result = {"azure_openai": probe_openai(openai_names) if openai_names else {},
              "anthropic_foundry": probe_anthropic(anthropic_names) if anthropic_names else {}}
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    for family, entries in result.items():
        print(f"{family}:")
        for name, info in entries.items():
            if name == "_error":
                print(f"  not configured: {info}")
            elif info["ok"]:
                print(f"  OK   {name} -> {info['model']}")
            else:
                print(f"  --   {name} ({info['error']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
