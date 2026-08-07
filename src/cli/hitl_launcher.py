"""Shared workspace and run-launch plumbing for HITL user interfaces."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import yaml

from core.config_loader import ConfigLoader
from core.hitl_frontier import HitlFrontierStore
from core.hitl_lock import HitlWorkspaceRunActiveError, active_hitl_workspace_run
from core.idea_manager import IdeaManager
from core.runner import ResearchRunner


def workspace_for_idea(project_root: Path, idea_id: str) -> Path:
    """Resolve or initialize the local workspace recorded for an idea."""
    idea_manager = IdeaManager(Path(project_root) / "ideas")
    idea = idea_manager.get_idea(idea_id)
    if idea is None:
        raise ValueError(f"Idea not found: {idea_id}")

    metadata = dict(idea.get("idea", {}).get("metadata", {}) or {})
    workspace_root = ConfigLoader().get_workspace_parent_dir()
    candidates: list[Path] = []
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


class HitlRunController:
    """Launch and report one workspace-owned HITL AutoResearch run at a time."""

    def __init__(
        self,
        *,
        idea_id: str,
        work_dir: Path,
        project_root: Path,
        host: Any,
        interface: str,
        on_status_change: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        if interface not in {"web", "cli"}:
            raise ValueError("HITL run interface must be 'web' or 'cli'.")
        self.idea_id = str(idea_id)
        self.work_dir = Path(work_dir)
        self.project_root = Path(project_root)
        self.host = host
        self.interface = interface
        self.on_status_change = on_status_change
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._status: Dict[str, Any] = {"status": "idle"}

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            local_status = dict(self._status)
            local_running = self._thread is not None and self._thread.is_alive()
        if local_running:
            return {"status": "running", "source": self.interface}
        external_owner = active_hitl_workspace_run(self.work_dir)
        if external_owner is not None:
            return {
                "status": "running",
                "source": "external",
                "owner": external_owner,
            }
        return local_status

    def launch(self, payload: Dict[str, Any]) -> Dict[str, Any]:
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

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("An HITL AutoResearch run is already active for this workspace.")
            external_owner = active_hitl_workspace_run(self.work_dir)
            if external_owner is not None:
                raise HitlWorkspaceRunActiveError(self.work_dir, external_owner)
            continuation = HitlFrontierStore(self.work_dir).exists()
            runner = ResearchRunner(
                project_root=self.project_root,
                use_github=bool(payload.get("github", False)),
            )

            def execute() -> Dict[str, Any]:
                return runner.run_research(
                    self.idea_id,
                    provider=provider,
                    write_paper=bool(payload.get("write_paper", False)),
                    paper_style=None if style == "auto" else style,
                    autoresearch_iterations=iterations,
                    hitl_autoresearch=None if continuation else self.interface,
                    hitl_continue_autoresearch=(self.interface if continuation else None),
                    hitl_host=self.host,
                )

            def run() -> None:
                try:
                    if self.interface == "cli":
                        log_path = self.work_dir / "logs" / "hitl_cli_runtime.log"
                        log_path.parent.mkdir(parents=True, exist_ok=True)
                        with log_path.open("a", encoding="utf-8") as output:
                            with redirect_stdout(output), redirect_stderr(output):
                                result = execute()
                    else:
                        result = execute()
                    next_status = "completed" if result.get("success") else "failed"
                    error = ""
                except HitlWorkspaceRunActiveError as exc:
                    next_status = "idle"
                    error = str(exc)
                except Exception as exc:
                    next_status = "failed"
                    error = str(exc)
                with self._lock:
                    self._status = {"status": next_status}
                    if error:
                        self._status["error"] = error
                self._publish_status()

            self._thread = threading.Thread(
                target=run,
                name="hitl-autoresearch-launch",
                daemon=True,
            )
            self._status = {
                "status": "running",
                "mode": "continue" if continuation else "fresh",
            }
            self._thread.start()
        self._publish_status()
        return {
            "status": "accepted",
            "mode": "continue" if continuation else "fresh",
        }

    def _publish_status(self) -> None:
        if self.on_status_change is not None:
            with self._lock:
                status = dict(self._status)
            self.on_status_change(status)
