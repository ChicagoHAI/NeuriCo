"""
Model-Monitor Agent

Launches a CLI agent (Claude Code, Codex, or Gemini) to do mechanistic-
interpretability analysis and (eventually real-time) monitoring of open-weight
models: launching models locally with hooks into their internals, training and
evaluating probes on hidden states, applying/training sparse autoencoders, and
running causal interventions (activation patching / tracing / steering).

The agent's toolkit is the `mech-interp` skill (templates/skills/mech-interp),
which it composes with `safety-evals` (shared probe/serve scripts and the result
schema), `dsi-slurm` (GPUs), and `modal-vllm` (off-machine serving).

Module shape mirrors agents/resource_finder.py: a prompt builder plus a run
function that launches through core.agent_factory with the `model_monitor` role
from config/agents.yaml. The actual interp work is done by the launched agent
following the skill; the heavy lifting lives in the skill's scripts, NOT here.

TODO(impl): wire optional dataset/model objective fields from the idea YAML into
the objective string; add a JSON-schema output contract once the result schema
is finalised; add a Phase-2 "serve + stream" monitoring entry point.
"""

from pathlib import Path
from typing import Optional, Dict, Any
import shlex
import sys
import time

# Add parent directory to path for imports (mirrors resource_finder.py).
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agent_factory import AgentFactory
from core.agent_cli import require_supported_provider

_OBJECTIVE_MARKER = "{{OBJECTIVE}}"
_DEFAULT_OBJECTIVE = (
    "No specific objective was provided. Execute the default Phase-1 objective "
    "described below."
)


def generate_model_monitor_prompt(
    idea: Dict[str, Any],
    templates_dir: Path,
    *,
    objective: str = "",
    provider: str = "claude",
) -> str:
    """Build the model-monitor prompt from templates/agents/model_monitor.txt.

    Simple marker substitution (not Jinja/PromptGenerator) keeps the scaffold
    self-contained. ``objective`` is a focused instruction for this invocation;
    when empty we fall back to the idea's title/description, then to the
    template's built-in Phase-1 default.

    TODO(impl): pull a richer objective (target model id, dataset id, layer
    sweep, SAE release) out of ``idea`` once the idea schema carries them.
    """
    template_path = Path(templates_dir) / "agents" / "model_monitor.txt"
    template = template_path.read_text(encoding="utf-8")

    if not objective:
        spec = idea.get("idea", idea) if isinstance(idea, dict) else {}
        title = str(spec.get("title", "")).strip()
        description = str(spec.get("description", "")).strip()
        objective = "\n".join(p for p in (title, description) if p).strip()

    return template.replace(_OBJECTIVE_MARKER, objective or _DEFAULT_OBJECTIVE)


def run_model_monitor(
    idea: Dict[str, Any],
    work_dir: Path,
    provider: str = "claude",
    tracker: Any = None,
    templates_dir: Optional[Path] = None,
    timeout: Optional[int] = None,  # None = the role's config (no limit unless set), 0 = no limit
    full_permissions: bool = True,
    objective: str = "",
    env_extra: Optional[Dict[str, str]] = None,
    prompt_override: Optional[str] = None,
    logs_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Launch the model-monitor agent for a mech-interp / monitoring task.

    The ``model_monitor`` role (config/agents.yaml) supplies provider flags,
    the ``files`` output contract (REPORT.md), and the skills copied into the
    agent's workspace (mech-interp + safety-evals + dsi-slurm). Success is the
    role's contract: REPORT.md exists after the run.

    Called two ways:
      * directly / via the dispatch table in core.agent_runner (``run_agent``
        passes idea, work_dir, provider, tracker, **kwargs);
      * by the interactive manager's run_agent tool (src/interactive/tools.py).
    """
    require_supported_provider(provider)

    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent.parent / "templates"

    print("🔬 Starting Model-Monitor Agent")
    print(f"   Provider: {provider}")
    print(f"   Work dir: {work_dir}")
    timeout_label = (
        "role budget (config/agents.yaml)" if timeout is None
        else ("disabled" if not timeout else f"{timeout}s")
    )
    print(f"   Timeout: {timeout_label}")
    print("=" * 80)

    if prompt_override is not None:
        prompt = prompt_override
    else:
        prompt = generate_model_monitor_prompt(
            idea, templates_dir, objective=objective, provider=provider
        )

    logs_dir = Path(logs_dir) if logs_dir is not None else work_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    start_time = time.time()

    # Launch through the agent factory with the model_monitor role. The role's
    # files contract (REPORT.md) decides success; the factory writes the prompt,
    # streams output, enforces any deadline, cleans up the process group, and
    # records a ledger line.
    factory = AgentFactory()
    spec = factory.spec(
        "model_monitor",
        provider=provider,
        full_permissions=full_permissions,
        timeout=timeout,
        transcript={"logs_dir": logs_dir, "prefix": "model_monitor"},
    )
    handle = factory.build(spec, env_extra)
    _print_launch_banner(provider, shlex.join(handle.argv),
                         logs_dir / f"model_monitor_{provider}.log",
                         logs_dir / f"model_monitor_{provider}_transcript.jsonl")

    on_start = tracker.mark_running if tracker is not None else None
    result = factory.run(handle, prompt, work_dir, on_start=on_start).legacy_dict()

    elapsed = time.time() - start_time
    print()
    print("=" * 80)
    print(f"⏱️  Model-monitor completed in {elapsed:.1f}s")

    # Verify outputs.
    outputs: Dict[str, str] = {}
    output_paths = {
        "report": work_dir / "REPORT.md",
        "results_dir": work_dir / "results" / "mech-interp",
        "findings_dir": work_dir / "findings",
    }
    for name, path in output_paths.items():
        if path.exists():
            outputs[name] = str(path)
            print(f"   ✅ {name}: {path}")
        else:
            print(f"   ⚠️  {name}: not found at {path}")

    result["outputs"] = outputs
    result["elapsed_time"] = elapsed
    return result


def _print_launch_banner(provider: str, command: str, log_file: Path, transcript_file: Path) -> None:
    print(f"▶️  Launching {provider} CLI agent...")
    print(f"   Command: {command}")
    print(f"   Log file: {log_file}")
    print(f"   Transcript: {transcript_file}")
    print()
    print("=" * 80)
    print("MODEL-MONITOR OUTPUT (streaming)")
    print("=" * 80)
    print()
