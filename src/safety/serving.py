"""Resolve a model registry entry to something inspect_ai / OpenAI clients can call.

- ``vllm:<hf_id>``      start a local vLLM OpenAI-compatible server on the given GPU.
- ``openrouter:<slug>`` -> inspect model string ``openrouter/<slug>`` (needs OPENROUTER_API_KEY).
- ``anthropic:<id>``    -> ``anthropic/<id>``.
- ``openai:<id>``       -> ``openai/<id>``.

The vLLM server is a child in its own process group so stopping it never touches
other users' servers on a shared machine (never kill by name pattern).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

ENV_ALIASES = {
    # NeuriCo .env name -> name expected by inspect_ai / SDKs
    "OPENROUTER_KEY": "OPENROUTER_API_KEY",
    "GOOGLE_API_KEY": "GOOGLE_API_KEY",
    "AZURE_OPENAI_API_KEY": "AZURE_API_KEY",
}


def export_provider_env(env: Dict[str, str]) -> Dict[str, str]:
    """Copy NeuriCo-style key names to the names the SDKs read. Values are never printed."""
    for src, dst in ENV_ALIASES.items():
        if env.get(src) and not env.get(dst):
            env[dst] = env[src]
    return env


@dataclass
class Endpoint:
    inspect_model: str            # e.g. "openai/qwen2.5-0.5b-instruct" or "openrouter/openai/gpt-4.1-mini"
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    extra_env: Optional[Dict[str, str]] = None

    def env(self) -> Dict[str, str]:
        out: Dict[str, str] = {k: v for k, v in (self.extra_env or {}).items() if v}
        if self.base_url:
            out["OPENAI_BASE_URL"] = self.base_url
            out.setdefault("OPENAI_API_KEY", "local")
        return out


def free_port(start: int = 8400, end: int = 8499) -> int:
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("no free port in range")


class VLLMServer:
    """Start/stop a vLLM OpenAI-compatible server for one HF model."""

    def __init__(self, hf_id: str, served_name: str, *, gpu: Optional[str], python: str,
                 log_file: Path, gpu_memory_utilization: float = 0.45, max_model_len: int = 8192,
                 extra_args: Optional[List[str]] = None, port: Optional[int] = None,
                 hf_home: Optional[str] = None):
        self.hf_id = hf_id
        self.served_name = served_name
        self.gpu = gpu
        self.python = python
        self.log_file = Path(log_file)
        self.port = port or free_port()
        self.gpu_memory_utilization = gpu_memory_utilization
        self.max_model_len = max_model_len
        self.extra_args = extra_args or []
        self.hf_home = hf_home
        self.process: Optional[subprocess.Popen] = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def effective_utilization(self) -> float:
        """vLLM's --gpu-memory-utilization is a fraction of TOTAL memory and the server refuses to
        start when less than that is free. On a shared GPU, size the request from what is free now
        (minus 2 GB headroom) so co-located jobs do not kill each other at startup."""
        try:
            query = ["nvidia-smi", "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"]
            if self.gpu is not None:
                query += ["-i", str(self.gpu).split(",")[0]]
            total, free = (float(x) for x in subprocess.check_output(query, text=True, timeout=20).strip().splitlines()[0].split(","))
            available = max(0.0, (free - 2048) / total)
            return round(min(self.gpu_memory_utilization, available), 2)
        except Exception:  # noqa: BLE001 - no nvidia-smi: trust the configured fraction
            return self.gpu_memory_utilization

    def command(self) -> List[str]:
        return [self.python, "-m", "vllm.entrypoints.openai.api_server",
                "--model", self.hf_id, "--served-model-name", self.served_name,
                "--port", str(self.port), "--max-model-len", str(self.max_model_len),
                "--gpu-memory-utilization", str(self.effective_utilization()),
                *self.extra_args]

    def start(self, timeout: Optional[float] = None) -> "VLLMServer":
        # First start on a network filesystem can take 20+ minutes (weights, torch.compile,
        # CUDA graphs); later starts reuse the compile cache under VLLM_CACHE_ROOT.
        if timeout is None:
            timeout = float(os.environ.get("NEURICO_VLLM_STARTUP_TIMEOUT", 2700))
        env = os.environ.copy()
        cache_root = os.environ.get("NEURICO_CACHE_ROOT")
        if cache_root:
            env.setdefault("VLLM_CACHE_ROOT", os.path.join(cache_root, "vllm"))
            env.setdefault("TORCHINDUCTOR_CACHE_DIR", os.path.join(cache_root, "torchinductor"))
            env.setdefault("TRITON_CACHE_DIR", os.path.join(cache_root, "triton"))
            env.setdefault("XDG_CACHE_HOME", cache_root)
        if self.gpu is not None:
            env["CUDA_VISIBLE_DEVICES"] = str(self.gpu)
        if self.hf_home:
            env["HF_HOME"] = self.hf_home
        # The flashinfer sampler JIT fails on this host's toolchain; the default sampler is fine.
        env.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")
        # One fresh file per start: appending to a file a killed server still holds open
        # stalled the next server in Lustre sync-I/O wait on this cluster.
        base = self.log_file
        self.log_file = base.with_name(f"{base.stem}.{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}{base.suffix}")
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        log = self.log_file.open("w", encoding="utf-8")
        log.write(f"$ {' '.join(self.command())}\n")
        log.flush()
        self.process = subprocess.Popen(self.command(), env=env, stdout=log, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL, start_new_session=True)
        log.close()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"vLLM exited with code {self.process.returncode}; see {self.log_file}")
            if self.is_ready():
                return self
            time.sleep(5)
        self.stop()
        raise TimeoutError(f"vLLM did not become ready within {timeout}s; see {self.log_file}")

    def is_ready(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/models", timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return any(m.get("id") == self.served_name for m in data.get("data", []))
        except Exception:  # noqa: BLE001
            return False

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            try:
                os.killpg(self.process.pid, 15)
                self.process.wait(timeout=60)
            except Exception:  # noqa: BLE001
                try:
                    os.killpg(self.process.pid, 9)
                except Exception:  # noqa: BLE001
                    pass
        self.process = None

    def endpoint(self) -> Endpoint:
        return Endpoint(inspect_model=f"openai/{self.served_name}", base_url=self.base_url,
                        api_key_env="OPENAI_API_KEY")

    def __enter__(self) -> "VLLMServer":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()


def resolve_api_endpoint(model_entry: Dict[str, Any]) -> Endpoint:
    access = str(model_entry["access"])
    kind, _, target = access.partition(":")
    if kind == "openrouter":
        return Endpoint(inspect_model=f"openrouter/{target}", api_key_env="OPENROUTER_API_KEY")
    if kind == "anthropic":
        return Endpoint(inspect_model=f"anthropic/{target}", api_key_env="ANTHROPIC_API_KEY")
    if kind == "openai":
        return Endpoint(inspect_model=f"openai/{target}", api_key_env="OPENAI_API_KEY")
    if kind == "google":
        return Endpoint(inspect_model=f"google/{target}", api_key_env="GOOGLE_API_KEY")
    if kind == "azure":
        # OpenAI-compatible Azure v1 endpoint; inspect's openai-api provider reads
        # AZURE_BASE_URL / AZURE_API_KEY for the "azure" provider name.
        base_url = (os.environ.get("AZURE_OPENAI_BASE_URL") or "").rstrip("/")
        resource = os.environ.get("AZURE_FOUNDRY_RESOURCE")
        if not base_url and resource:
            base_url = f"https://{resource}.openai.azure.com/openai/v1"
        return Endpoint(inspect_model=f"openai-api/azure/{target}", api_key_env="AZURE_API_KEY",
                        extra_env={"AZURE_BASE_URL": base_url, "AZURE_API_KEY": os.environ.get("AZURE_OPENAI_API_KEY", "")})
    if kind == "vllm":
        raise ValueError("vllm models need a running VLLMServer; use serve()")
    raise ValueError(f"unknown access scheme in {access!r}")


def serve(model_entry: Dict[str, Any], *, gpu: Optional[str], python: str, log_dir: Path,
          hf_home: Optional[str] = None) -> VLLMServer:
    access = str(model_entry["access"])
    kind, _, hf_id = access.partition(":")
    if kind != "vllm":
        raise ValueError(f"not a vllm model: {access}")
    # Catalog paths (chat templates, lora adapters) are relative to the project root; servers may
    # be started from a workspace, so resolve them here.
    project_root = Path(__file__).resolve().parents[2]
    serve_args = [str(project_root / a) if (project_root / str(a)).is_file() else str(a)
                  for a in (model_entry.get("serve_args") or [])]
    return VLLMServer(hf_id, model_entry["id"], gpu=gpu, python=python,
                      log_file=Path(log_dir) / f"vllm_{model_entry['id']}.log",
                      gpu_memory_utilization=float(model_entry.get("gpu_memory_utilization", 0.45)),
                      max_model_len=int(model_entry.get("max_model_len", 8192)),
                      extra_args=serve_args, hf_home=hf_home).start()
