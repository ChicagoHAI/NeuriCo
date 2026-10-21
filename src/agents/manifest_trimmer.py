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
import shlex
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agent_cli import require_supported_provider
from core.agent_factory import AgentFactory

# NOTE: unlike rule_maker / autoresearch_proposer (which only need the
# transcript for human debugging), the trimmer must PARSE the agent's
# response from stdout. Stream-json mode wraps the response in
# per-event envelopes whose first object is a system-init message --
# our JSON extractor would grab that and fail validation. Plain text
# mode prints only the final response, which is exactly what we need;
# the manifest_trimmer role in config/agents.yaml selects it
# (transcript.stream_json: false) with a json_stdout output contract.


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
    timeout: Optional[int] = None,  # None = the role's config (no limit unless set), 0 = no limit
    full_permissions: bool = True,
    prior_error: Optional[str] = None,
    log_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Run the manifest trimmer agent once. Returns the parsed JSON dict the
    agent emitted on stdout. Raises on subprocess error, timeout, or non-JSON
    output -- the curate_manifest wrapper catches these and retries.
    """
    require_supported_provider(provider)

    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent.parent / "templates"

    work_dir = Path(work_dir)
    prompt = generate_trimmer_prompt(
        manifest=manifest,
        work_dir=work_dir,
        templates_dir=Path(templates_dir),
        prior_error=prior_error,
    )

    # The factory needs somewhere for its log and transcript; without a caller-owned
    # log_dir they go where every other agent's artifacts go.
    log_dir = Path(log_dir) if log_dir is not None else work_dir / "logs"

    factory = AgentFactory()
    spec = factory.spec(
        "manifest_trimmer", provider=provider, full_permissions=full_permissions, timeout=timeout,
        transcript={"logs_dir": log_dir, "prefix": "trimmer"},
    )
    handle = factory.build(spec)

    print(f"🧹 Launching manifest trimmer ({provider})")
    print(f"   Command: {shlex.join(handle.argv)}")
    print(f"   Workspace: {work_dir}")
    print(f"   Prompt length: {len(prompt)} chars")

    # Plain-text mode: stdout is the answer, and the role's json_stdout contract
    # extracts the first balanced JSON object and checks it against the schema.
    # Every failure is raised, as before, so curate_manifest can retry with the
    # message as prior_error.
    result = factory.run(handle, prompt, work_dir)
    if result.timed_out:
        raise TimeoutError(f"Manifest trimmer timed out after {timeout}s")
    if result.return_code != 0:
        raise RuntimeError(
            f"Manifest trimmer exited with code {result.return_code} after {result.elapsed_s:.1f}s"
        )
    if not result.success:
        raise ValueError("; ".join(result.issues) or f"Manifest trimmer failed: {result.status}")

    print(f"✅ Trimmer returned in {result.elapsed_s:.1f}s")
    return result.structured


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
    timeout: Optional[int] = None,  # None = the role's config (no limit unless set), 0 = no limit
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
