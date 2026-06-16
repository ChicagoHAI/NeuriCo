"""
Workspace Manifest Trimmer Agent

Pass 2 of the workspace_manifest feature. The trimmer reads a raw mechanical
manifest plus public write-ups (REPORT.md, planning.md, README.md) and emits a
TrimDecision -- a closed-enum curation of which files the bootstrap rule_maker
should see, role overrides for mechanical misclassifications, the ranked
primary runner outputs, and a structural task-shape description.

The agent's output is consumed by core.workspace_manifest.curate_manifest, which
validates and applies it under a retry-and-fallback loop. This module supplies
the concrete TrimmerCallable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional
import json
import os
import shlex
import subprocess
import sys
import time

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.security import sanitize_text


# CLI commands for different providers (mirrors rule_maker.py)
CLI_COMMANDS = {
    "claude": "claude -p",
    "codex": "codex exec",
    "gemini": "gemini",
}

# NOTE: unlike rule_maker / autoresearch_proposer (which only need the
# transcript for human debugging), the trimmer must PARSE the agent's
# response from stdout. Stream-json mode wraps the response in
# per-event envelopes whose first object is a system-init message --
# our JSON extractor would grab that and fail validation. Plain text
# mode prints only the final response, which is exactly what we need.
TRANSCRIPT_FLAGS: dict[str, str] = {}


_REPORT_MAX_CHARS = 50_000
_PLANNING_MAX_CHARS = 50_000
_README_MAX_CHARS = 20_000


def _read_capped(path: Path, max_chars: int) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""
    if len(text) > max_chars:
        return text[:max_chars] + f"\n\n[...truncated; original was {len(text)} chars]"
    return text


def generate_trimmer_prompt(
    manifest: Dict[str, Any],
    work_dir: Path,
    templates_dir: Path,
    prior_error: Optional[str] = None,
) -> str:
    """
    Render the trimmer prompt by injecting the manifest and public write-ups
    into the template.
    """
    from jinja2 import Environment, FileSystemLoader

    work_dir = Path(work_dir)
    templates_dir = Path(templates_dir)
    template_path = templates_dir / "agents" / "manifest_trimmer.txt"
    if not template_path.exists():
        raise FileNotFoundError(f"Manifest trimmer template not found: {template_path}")

    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("agents/manifest_trimmer.txt")

    return template.render(
        work_dir=str(work_dir),
        manifest_json=json.dumps(manifest, indent=2),
        report_md=_read_capped(work_dir / "REPORT.md", _REPORT_MAX_CHARS),
        planning_md=_read_capped(work_dir / "planning.md", _PLANNING_MAX_CHARS),
        readme_md=_read_capped(work_dir / "README.md", _README_MAX_CHARS),
        prior_error=prior_error,
    )


def run_manifest_trimmer(
    manifest: Dict[str, Any],
    work_dir: Path,
    provider: str = "claude",
    templates_dir: Optional[Path] = None,
    timeout: int = 300,
    full_permissions: bool = True,
    prior_error: Optional[str] = None,
    log_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Run the manifest trimmer agent once. Returns the parsed JSON dict the
    agent emitted on stdout. Raises on subprocess error, timeout, or non-JSON
    output -- the curate_manifest wrapper catches these and retries.
    """
    if provider not in CLI_COMMANDS:
        raise ValueError(
            f"Unsupported provider: {provider}. Choose from: {list(CLI_COMMANDS.keys())}"
        )

    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent.parent / "templates"

    work_dir = Path(work_dir)
    prompt = generate_trimmer_prompt(
        manifest=manifest,
        work_dir=work_dir,
        templates_dir=Path(templates_dir),
        prior_error=prior_error,
    )

    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "trimmer_prompt.txt").write_text(prompt, encoding="utf-8")

    cmd = CLI_COMMANDS[provider]
    if full_permissions:
        if provider == "codex":
            cmd += " --yolo"
        elif provider == "claude":
            cmd += " --dangerously-skip-permissions"
        elif provider == "gemini":
            cmd += " --yolo --skip-trust"

    transcript_flag = TRANSCRIPT_FLAGS.get(provider, "")
    if transcript_flag:
        cmd += f" {transcript_flag}"

    print(f"🧹 Launching manifest trimmer ({provider})")
    print(f"   Command: {cmd}")
    print(f"   Workspace: {work_dir}")
    print(f"   Prompt length: {len(prompt)} chars")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if provider == "gemini":
        env["GEMINI_CLI_IDE_DISABLE"] = "1"

    transcript_path: Optional[Path] = None
    if log_dir is not None:
        transcript_path = log_dir / f"trimmer_{provider}_transcript.jsonl"

    start = time.time()
    try:
        process = subprocess.Popen(
            shlex.split(cmd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=str(work_dir),
        )

        captured_lines: list[str] = []
        transcript_file = transcript_path.open("w", encoding="utf-8") if transcript_path else None

        try:
            process.stdin.write(prompt)
            process.stdin.close()

            for line in iter(process.stdout.readline, ""):
                if not line:
                    continue
                clean = sanitize_text(line)
                captured_lines.append(clean)
                if transcript_file is not None:
                    transcript_file.write(clean)

            return_code = process.wait(timeout=timeout)
        finally:
            if transcript_file is not None:
                transcript_file.close()
    except subprocess.TimeoutExpired:
        process.kill()
        raise TimeoutError(f"Manifest trimmer timed out after {timeout}s")

    elapsed = time.time() - start
    raw_output = "".join(captured_lines)

    if return_code != 0:
        raise RuntimeError(
            f"Manifest trimmer exited with code {return_code} after {elapsed:.1f}s"
        )

    payload = _extract_json_object(raw_output)
    print(f"✅ Trimmer returned in {elapsed:.1f}s")
    return payload


def _extract_json_object(text: str) -> Dict[str, Any]:
    """
    Pull the first balanced JSON object out of the agent's stdout. Tolerates
    surrounding prose by scanning for the first '{' and matching braces;
    raises if no valid object is found.
    """
    stripped = text.strip()
    if not stripped:
        raise ValueError("Trimmer produced empty output")

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    if start == -1:
        raise ValueError("No JSON object found in trimmer output")

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(stripped)):
        c = stripped[i]
        if escape:
            escape = False
            continue
        if c == "\\" and in_string:
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                candidate = stripped[start : i + 1]
                return json.loads(candidate)
    raise ValueError("Unbalanced braces in trimmer output")


def make_trimmer_callable(
    provider: str = "claude",
    templates_dir: Optional[Path] = None,
    timeout: int = 300,
    full_permissions: bool = True,
    log_dir: Optional[Path] = None,
) -> Callable[[Dict[str, Any], Path, Optional[str]], Dict[str, Any]]:
    """
    Bind a TrimmerCallable suitable for core.workspace_manifest.curate_manifest.

    Usage:
        from core.workspace_manifest import build_manifest, curate_manifest
        from agents.manifest_trimmer import make_trimmer_callable

        raw = build_manifest(work_dir)
        trimmer = make_trimmer_callable(provider="claude", templates_dir=tdir)
        curated = curate_manifest(raw, work_dir, trimmer)
    """
    def _trimmer(
        manifest: Dict[str, Any],
        work_dir: Path,
        prior_error: Optional[str],
    ) -> Dict[str, Any]:
        return run_manifest_trimmer(
            manifest=manifest,
            work_dir=work_dir,
            provider=provider,
            templates_dir=templates_dir,
            timeout=timeout,
            full_permissions=full_permissions,
            prior_error=prior_error,
            log_dir=log_dir,
        )

    return _trimmer
