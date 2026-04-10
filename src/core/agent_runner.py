"""
Standalone Agent Runner

Runs a single research agent (resource_finder, experiment_runner, paper_writer,
comment_handler) in a workspace directory WITHOUT managing idea lifecycle.

This is used by the interactive mode manager to invoke individual agents.
Unlike runner.py which handles the full pipeline + idea state transitions,
this module:
- Takes a workspace path + idea spec + agent name
- Runs just that one agent
- Tracks invocation status via .neurico/runs/<run_id>/
- Does NOT move idea files between folders
- Does NOT manage GitHub integration
- Does NOT impose timeouts (the caller handles that)

Usage (inside Docker):
    python src/core/agent_runner.py <agent_name> --workspace /path --provider claude --run-id rf_001 --idea-file /path/to/idea.yaml

Supported agents: resource_finder, experiment_runner, paper_writer, comment_handler
"""

from pathlib import Path
from typing import Dict, Any, Optional
import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import traceback
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.security import sanitize_text


# CLI commands for different providers
CLI_COMMANDS = {
    'claude': 'claude -p',
    'codex': 'codex exec',
    'gemini': 'gemini'
}

# CLI flags for verbose/structured transcript output
TRANSCRIPT_FLAGS = {
    'claude': '--verbose --output-format stream-json',
    'codex': '--json',
    'gemini': '--output-format stream-json'
}


class RunTracker:
    """
    Tracks a single agent invocation via .neurico/runs/<run_id>/.

    Provides robust status tracking so the manager never has to guess
    whether an agent is running, succeeded, or failed.
    """

    def __init__(self, work_dir: Path, run_id: str, agent_name: str):
        self.run_dir = work_dir / ".neurico" / "runs" / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.status_file = self.run_dir / "status.json"
        self.result_file = self.run_dir / "result.json"
        self.error_file = self.run_dir / "error.json"
        self.run_id = run_id
        self.agent_name = agent_name

    def mark_running(self, pid: int):
        """Mark this run as started."""
        self._write_status({
            "run_id": self.run_id,
            "agent": self.agent_name,
            "status": "running",
            "pid": pid,
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "exit_code": None
        })

    def mark_completed(self, exit_code: int, result: Dict[str, Any]):
        """Mark this run as successfully completed."""
        status = self._read_status()
        status["status"] = "completed"
        status["completed_at"] = datetime.now().isoformat()
        status["exit_code"] = exit_code
        self._write_status(status)

        with open(self.result_file, 'w') as f:
            json.dump(result, f, indent=2)

    def mark_failed(self, exit_code: Optional[int], error_msg: str, tb: Optional[str] = None):
        """Mark this run as failed."""
        status = self._read_status()
        status["status"] = "failed"
        status["completed_at"] = datetime.now().isoformat()
        status["exit_code"] = exit_code
        self._write_status(status)

        error_info = {
            "error": error_msg,
            "traceback": tb,
            "timestamp": datetime.now().isoformat()
        }
        with open(self.error_file, 'w') as f:
            json.dump(error_info, f, indent=2)

    def mark_stopped(self):
        """Mark this run as stopped (by user/manager)."""
        status = self._read_status()
        status["status"] = "stopped"
        status["completed_at"] = datetime.now().isoformat()
        self._write_status(status)

    def _read_status(self) -> Dict[str, Any]:
        if self.status_file.exists():
            with open(self.status_file) as f:
                return json.load(f)
        return {}

    def _write_status(self, status: Dict[str, Any]):
        with open(self.status_file, 'w') as f:
            json.dump(status, f, indent=2)


def _build_agent_command(provider: str, full_permissions: bool = True,
                         use_scribe: bool = False) -> str:
    """Build the CLI command for launching an agent."""
    if use_scribe:
        cmd = f"scribe {provider}"
    else:
        cmd = CLI_COMMANDS[provider]

    # Add permission flags
    if full_permissions:
        if provider == "codex":
            cmd += " --yolo"
        elif provider == "claude":
            cmd += " --dangerously-skip-permissions"
        elif provider == "gemini":
            cmd += " --yolo"

    # Add transcript/JSON output flags
    transcript_flag = TRANSCRIPT_FLAGS.get(provider, '')
    if transcript_flag:
        cmd += f" {transcript_flag}"

    return cmd


def _run_cli_agent(cmd: str, prompt: str, work_dir: Path,
                   log_file: Path, transcript_file: Path,
                   tracker: RunTracker) -> Dict[str, Any]:
    """
    Execute a CLI agent with streaming output capture.

    This is the common execution pattern shared by all agents.
    """
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'

    # Disable IDE integration for Gemini CLI
    if 'gemini' in cmd:
        env['GEMINI_CLI_IDE_DISABLE'] = '1'

    log_file.parent.mkdir(parents=True, exist_ok=True)

    start_time = time.time()

    with open(log_file, 'w') as log_f, open(transcript_file, 'w') as transcript_f:
        process = subprocess.Popen(
            shlex.split(cmd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            bufsize=1,
            cwd=str(work_dir)
        )

        tracker.mark_running(process.pid)

        # Send prompt via stdin
        process.stdin.write(prompt)
        process.stdin.close()

        # Stream output
        for line in iter(process.stdout.readline, ''):
            if line:
                sanitized_line = sanitize_text(line)
                print(sanitized_line, end='')
                log_f.write(sanitized_line)
                transcript_f.write(sanitized_line)

        return_code = process.wait()

    elapsed = time.time() - start_time
    success = return_code == 0

    return {
        'success': success,
        'return_code': return_code,
        'elapsed_time': elapsed,
        'log_file': str(log_file),
        'transcript_file': str(transcript_file)
    }


def run_resource_finder(idea: Dict[str, Any], work_dir: Path, provider: str,
                        tracker: RunTracker, full_permissions: bool = True,
                        templates_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Run the resource finder agent."""
    from agents.resource_finder import generate_resource_finder_prompt

    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent.parent / "templates"

    print(f"🔍 Starting Resource Finder Agent (run: {tracker.run_id})")
    print(f"   Provider: {provider}")
    print(f"   Work dir: {work_dir}")

    # Generate prompt
    prompt = generate_resource_finder_prompt(idea, templates_dir)

    # Save prompt for reference
    prompt_file = work_dir / "logs" / "resource_finder_prompt.txt"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    with open(prompt_file, 'w', encoding='utf-8') as f:
        f.write(prompt)

    # Build and run command
    cmd = _build_agent_command(provider, full_permissions)
    log_file = work_dir / "logs" / f"resource_finder_{provider}.log"
    transcript_file = work_dir / "logs" / f"resource_finder_{provider}_transcript.jsonl"

    result = _run_cli_agent(cmd, prompt, work_dir, log_file, transcript_file, tracker)

    # Check for outputs
    outputs = {}
    output_paths = {
        'literature_review': work_dir / "literature_review.md",
        'resources_catalog': work_dir / "resources.md",
        'papers_dir': work_dir / "papers",
        'datasets_dir': work_dir / "datasets",
        'code_dir': work_dir / "code"
    }
    for name, path in output_paths.items():
        if path.exists():
            outputs[name] = str(path)

    result['outputs'] = outputs
    return result


def run_experiment_runner(idea: Dict[str, Any], work_dir: Path, provider: str,
                          tracker: RunTracker, full_permissions: bool = True,
                          use_scribe: bool = False,
                          templates_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Run the experiment runner agent.

    Extracted from pipeline_orchestrator.py to be callable standalone.
    """
    from templates.prompt_generator import PromptGenerator
    from templates.research_agent_instructions import generate_instructions

    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent.parent / "templates"

    print(f"🧪 Starting Experiment Runner Agent (run: {tracker.run_id})")
    print(f"   Provider: {provider}")
    print(f"   Work dir: {work_dir}")

    # Generate research prompt
    prompt_generator = PromptGenerator(templates_dir)
    prompt = prompt_generator.generate_research_prompt(idea, root_dir=work_dir)

    # Save prompt
    prompt_file = work_dir / "logs" / "research_prompt.txt"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    with open(prompt_file, 'w', encoding='utf-8') as f:
        f.write(prompt)

    # Generate session instructions
    domain = idea.get('idea', {}).get('domain', 'general')
    session_instructions = generate_instructions(
        prompt=prompt,
        work_dir=str(work_dir),
        use_scribe=use_scribe,
        domain=domain
    )

    # Save session instructions
    session_file = work_dir / "logs" / "session_instructions.txt"
    with open(session_file, 'w', encoding='utf-8') as f:
        f.write(session_instructions)

    # Build and run command
    cmd = _build_agent_command(provider, full_permissions, use_scribe)
    if use_scribe:
        env_extra = {'SCRIBE_RUN_DIR': str(work_dir)}
        os.environ.update(env_extra)

    log_file = work_dir / "logs" / f"execution_{provider}.log"
    transcript_file = work_dir / "logs" / f"execution_{provider}_transcript.jsonl"

    # Experiment runner uses session_instructions (not raw prompt) as input
    result = _run_cli_agent(cmd, session_instructions, work_dir, log_file, transcript_file, tracker)

    return result


def run_paper_writer(idea: Dict[str, Any], work_dir: Path, provider: str,
                     tracker: RunTracker, full_permissions: bool = True,
                     paper_style: str = "neurips",
                     templates_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Run the paper writer agent."""
    from agents.paper_writer import run_paper_writer as _run_paper_writer

    print(f"📝 Starting Paper Writer Agent (run: {tracker.run_id})")
    print(f"   Provider: {provider}")
    print(f"   Style: {paper_style}")
    print(f"   Work dir: {work_dir}")

    domain = idea.get('idea', {}).get('domain', 'general')

    # Delegate to existing paper_writer module (it handles prompt generation,
    # style file copying, and CLI execution)
    result = _run_paper_writer(
        work_dir=work_dir,
        provider=provider,
        style=paper_style,
        timeout=None,  # No timeout in interactive mode
        full_permissions=full_permissions,
        domain=domain
    )

    return result


def run_comment_handler(idea: Dict[str, Any], work_dir: Path, provider: str,
                        tracker: RunTracker, full_permissions: bool = True,
                        templates_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Run the comment handler agent for targeted improvements."""
    from agents.comment_handler import generate_comment_prompt

    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent.parent / "templates"

    print(f"💬 Starting Comment Handler Agent (run: {tracker.run_id})")
    print(f"   Provider: {provider}")
    print(f"   Work dir: {work_dir}")

    # Generate prompt from comments in the idea file
    comments = idea.get('idea', {}).get('comments', [])
    if not comments:
        return {'success': False, 'error': 'No comments found in idea file'}

    prompt = generate_comment_prompt(idea, work_dir, templates_dir)

    # Build and run command
    cmd = _build_agent_command(provider, full_permissions)
    log_file = work_dir / "logs" / f"comment_handler_{provider}.log"
    transcript_file = work_dir / "logs" / f"comment_handler_{provider}_transcript.jsonl"

    result = _run_cli_agent(cmd, prompt, work_dir, log_file, transcript_file, tracker)

    return result


# Agent dispatch table
AGENTS = {
    'resource_finder': run_resource_finder,
    'experiment_runner': run_experiment_runner,
    'paper_writer': run_paper_writer,
    'comment_handler': run_comment_handler,
}


def run_agent(agent_name: str, idea: Dict[str, Any], work_dir: Path,
              provider: str, run_id: str, **kwargs) -> Dict[str, Any]:
    """
    Run a single agent with full run tracking.

    This is the main entry point. It wraps the agent execution in a
    try/finally to ensure status is always updated.

    Args:
        agent_name: One of: resource_finder, experiment_runner, paper_writer, comment_handler
        idea: Full idea specification (parsed YAML dict)
        work_dir: Workspace directory for the research
        provider: AI provider (claude, codex, gemini)
        run_id: Unique identifier for this invocation
        **kwargs: Additional agent-specific arguments (paper_style, use_scribe, etc.)

    Returns:
        Result dictionary from the agent
    """
    if agent_name not in AGENTS:
        raise ValueError(f"Unknown agent: {agent_name}. Choose from: {list(AGENTS.keys())}")

    tracker = RunTracker(work_dir, run_id, agent_name)
    agent_fn = AGENTS[agent_name]

    try:
        result = agent_fn(
            idea=idea,
            work_dir=work_dir,
            provider=provider,
            tracker=tracker,
            **kwargs
        )

        exit_code = result.get('return_code', 0 if result.get('success') else 1)
        if result.get('success', False):
            tracker.mark_completed(exit_code, result)
        else:
            tracker.mark_failed(exit_code, result.get('error', 'Agent returned unsuccessful'))

        return result

    except Exception as e:
        tracker.mark_failed(
            exit_code=1,
            error_msg=str(e),
            tb=traceback.format_exc()
        )
        raise


def main():
    """CLI entry point for running agents inside Docker."""
    parser = argparse.ArgumentParser(
        description="Run a single research agent (used by interactive mode)"
    )
    parser.add_argument(
        "agent",
        choices=list(AGENTS.keys()),
        help="Agent to run"
    )
    parser.add_argument(
        "--workspace",
        required=True,
        help="Workspace directory path"
    )
    parser.add_argument(
        "--provider",
        default="claude",
        choices=["claude", "codex", "gemini"],
        help="AI provider (default: claude)"
    )
    parser.add_argument(
        "--run-id",
        required=True,
        help="Unique identifier for this invocation"
    )
    parser.add_argument(
        "--idea-file",
        required=True,
        help="Path to the idea YAML file"
    )
    parser.add_argument(
        "--full-permissions",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Allow full permissions to CLI agents (default: True)"
    )
    parser.add_argument(
        "--paper-style",
        default="neurips",
        choices=["neurips", "icml", "acl", "ams"],
        help="Paper style template (for paper_writer agent)"
    )
    parser.add_argument(
        "--use-scribe",
        action="store_true",
        help="Use scribe for notebook integration (for experiment_runner agent)"
    )

    args = parser.parse_args()

    # Load idea spec
    import yaml
    with open(args.idea_file, 'r') as f:
        idea = yaml.safe_load(f)

    work_dir = Path(args.workspace)

    # Build kwargs based on agent type
    kwargs = {
        'full_permissions': args.full_permissions,
    }
    if args.agent == 'paper_writer':
        kwargs['paper_style'] = args.paper_style
    if args.agent == 'experiment_runner':
        kwargs['use_scribe'] = args.use_scribe

    # Run the agent
    result = run_agent(
        agent_name=args.agent,
        idea=idea,
        work_dir=work_dir,
        provider=args.provider,
        run_id=args.run_id,
        **kwargs
    )

    # Print final status
    if result.get('success'):
        print(f"\n✅ Agent {args.agent} completed successfully (run: {args.run_id})")
    else:
        print(f"\n⚠️  Agent {args.agent} finished with issues (run: {args.run_id})")

    sys.exit(0 if result.get('success') else 1)


if __name__ == "__main__":
    main()
