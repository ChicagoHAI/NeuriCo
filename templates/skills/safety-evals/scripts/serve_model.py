#!/usr/bin/env python3
"""Serve a model with vLLM as an OpenAI-compatible endpoint for ad-hoc experiments.

    $NEURICO_SAFETY_VENV/bin/python serve_model.py Qwen/Qwen2.5-0.5B-Instruct [--name qwen05] [--port 8450]
    $NEURICO_SAFETY_VENV/bin/python serve_model.py qwen2.5-0.5b-instruct     # catalog id works too
    $NEURICO_SAFETY_VENV/bin/python serve_model.py --stop                    # stop the server you started

Writes `.neurico/model_endpoint.json` ({base_url, model, pid}) in the workspace. The server
runs in the foreground; run it in the background with `nohup ... &` or a separate shell and
stop it with `--stop` (never kill by process name on a shared machine).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import add_safety_package, workspace_root  # noqa: E402

add_safety_package()
from safety.kb import KB  # noqa: E402
from safety.serving import VLLMServer  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("model", nargs="?", help="HF id or catalog model id")
    parser.add_argument("--name", help="served model name (default: catalog id or HF basename)")
    parser.add_argument("--port", type=int)
    parser.add_argument("--max-model-len", type=int, default=4096)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.45)
    parser.add_argument("--extra", nargs=argparse.REMAINDER, default=[], help="extra vLLM args after --extra")
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()

    root = workspace_root()
    endpoint_file = root / ".neurico" / "model_endpoint.json"
    if args.stop:
        if not endpoint_file.exists():
            print("no endpoint file; nothing to stop")
            return 0
        info = json.loads(endpoint_file.read_text())
        try:
            os.killpg(int(info["pid"]), signal.SIGTERM)
            print(f"stopped server pid {info['pid']}")
        except ProcessLookupError:
            print("server already gone")
        endpoint_file.unlink()
        return 0
    if not args.model:
        parser.error("model is required")

    hf_id, name = args.model, args.name
    try:
        entry = KB().models().get(args.model)
    except Exception:  # noqa: BLE001 - no knowledge base available
        entry = None
    if entry and str(entry.get("access", "")).startswith("vllm:"):
        hf_id = entry["access"].split(":", 1)[1]
        name = name or entry["id"]
    name = name or hf_id.split("/")[-1].lower()
    gpu = (os.environ.get("CUDA_VISIBLE_DEVICES") or "").split(",")[0] or None
    server = VLLMServer(hf_id, name, gpu=gpu, python=sys.executable, log_file=root / "logs" / f"vllm_{name}.log",
                        gpu_memory_utilization=args.gpu_memory_utilization, max_model_len=args.max_model_len,
                        extra_args=args.extra, port=args.port, hf_home=os.environ.get("HF_HOME"))
    server.start()
    endpoint_file.parent.mkdir(parents=True, exist_ok=True)
    endpoint_file.write_text(json.dumps({"base_url": server.base_url, "model": name, "hf_id": hf_id,
                                         "pid": server.process.pid, "inspect_model": f"openai/{name}"}, indent=2))
    print(f"ready: {server.base_url} model={name} (endpoint written to {endpoint_file})", flush=True)
    print("set OPENAI_BASE_URL to the base_url and OPENAI_API_KEY=local for inspect/openai clients", flush=True)
    try:
        while server.process.poll() is None:
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        if endpoint_file.exists():
            endpoint_file.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
