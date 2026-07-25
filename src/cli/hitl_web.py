"""Open the local HITL manager page for an existing research workspace."""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.config_loader import ConfigLoader
from core.idea_manager import IdeaManager
from core.hitl_manager_host import HitlManagerHost
from core.hitl_frontier import HitlFrontierStore
from core.runner import ResearchRunner
from interactive.manager import load_config


def _workspace_for_idea(project_root: Path, idea_id: str) -> Path:
    idea_manager = IdeaManager(project_root / "ideas")
    idea = idea_manager.get_idea(idea_id)
    if idea is None:
        raise ValueError(f"Idea not found: {idea_id}")

    metadata = dict(idea.get("idea", {}).get("metadata", {}) or {})
    workspace_root = ConfigLoader().get_workspace_parent_dir()
    candidates = []
    local_workspace = str(metadata.get("local_workspace", "")).strip()
    if local_workspace:
        candidates.append(Path(local_workspace).expanduser())
    repository_name = str(metadata.get("github_repo_name", "")).strip()
    if repository_name:
        candidates.append(workspace_root / repository_name)
    candidates.append(workspace_root / idea_id)

    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()

    workspace = (workspace_root / idea_id).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    idea.setdefault("idea", {}).setdefault("metadata", {})["local_workspace"] = str(workspace)
    with idea_manager.get_idea_path(idea_id).open("w", encoding="utf-8") as handle:
        yaml.safe_dump(idea, handle, default_flow_style=False, sort_keys=False)
    return workspace


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("idea_id")
    parser.add_argument("--port", type=int, default=7890)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    work_dir = _workspace_for_idea(PROJECT_ROOT, args.idea_id)
    host = HitlManagerHost(
        work_dir=work_dir,
        config=load_config(),
        interface="web",
        project_root=PROJECT_ROOT,
        title=args.idea_id,
        port=args.port,
        open_browser=not args.no_browser,
    )
    launch_lock = threading.Lock()
    launch_thread: threading.Thread | None = None
    run_status = {"status": "idle"}

    def snapshot_run_status() -> dict[str, object]:
        with launch_lock:
            return dict(run_status)

    def publish_run_status() -> None:
        emit = getattr(host.channel, "_emit", None)
        if callable(emit):
            emit({"event": "workspace_changed", "section": "run"})

    def launch(payload: dict[str, object]) -> dict[str, object]:
        nonlocal launch_thread
        provider = str(payload.get("provider", "")).strip().lower()
        if provider not in {"claude", "codex", "gemini"}:
            raise ValueError("Choose Claude, Codex, or Gemini as the worker.")
        try:
            iterations = int(payload.get("iterations", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError("Iterations must be a whole number.") from exc
        if not 1 <= iterations <= 100:
            raise ValueError("Iterations must be between 1 and 100.")
        style = str(payload.get("paper_style", "auto")).strip().lower()
        if style not in {"auto", "neurips", "icml", "acl"}:
            raise ValueError("Choose a supported paper style.")

        with launch_lock:
            if launch_thread is not None and launch_thread.is_alive():
                raise RuntimeError("An HITL AutoResearch run is already active for this workspace.")
            continuation = HitlFrontierStore(work_dir).exists()
            runner = ResearchRunner(
                project_root=PROJECT_ROOT,
                use_github=bool(payload.get("github", False)),
            )

            def run() -> None:
                try:
                    result = runner.run_research(
                        args.idea_id,
                        provider=provider,
                        write_paper=bool(payload.get("write_paper", False)),
                        paper_style=None if style == "auto" else style,
                        autoresearch_iterations=iterations,
                        hitl_autoresearch=None if continuation else "web",
                        hitl_continue_autoresearch="web" if continuation else None,
                        hitl_host=host,
                    )
                    next_status = "completed" if result.get("success") else "failed"
                except Exception:
                    next_status = "failed"
                with launch_lock:
                    run_status["status"] = next_status
                publish_run_status()

            launch_thread = threading.Thread(
                target=run,
                name="hitl-autoresearch-launch",
                daemon=True,
            )
            run_status["status"] = "running"
            launch_thread.start()
        publish_run_status()
        return {
            "status": "accepted",
            "mode": "continue" if continuation else "fresh",
        }

    assert host.web_server is not None
    host.web_server.set_run_launcher(launch, snapshot_run_status)

    stopping = False

    def stop(*_unused: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    host.start()
    print(f"HITL workspace: {host.web_server.url}", flush=True)
    try:
        while not stopping:
            time.sleep(0.25)
    finally:
        host.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
