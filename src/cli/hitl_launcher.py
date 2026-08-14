"""Shared workspace and run-launch plumbing for HITL user interfaces."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import yaml

from core.config_loader import ConfigLoader
from core.hitl_frontier import HitlFrontierStore
from core.hitl_lock import HitlWorkspaceRunActiveError, active_hitl_workspace_run
from core.hitl_paths import hitl_launch_status_path
from core.hitl_util import atomic_write_json, utc_now
from core.hitl_workspace_view import HitlWorkspaceView
from core.idea_manager import IdeaManager, resolve_ideas_dir
from core.runner import ResearchRunner


LOGGER = logging.getLogger(__name__)


def workspace_for_idea(project_root: Path, idea_id: str) -> Path:
    """Resolve or initialize the local workspace recorded for an idea."""
    idea_manager = IdeaManager(resolve_ideas_dir(Path(project_root)))
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
            raise ValueError("NeuriCo run interface must be 'web' or 'cli'.")
        self.idea_id = str(idea_id)
        self.work_dir = Path(work_dir)
        self.project_root = Path(project_root)
        self.host = host
        self.interface = interface
        self.on_status_change = on_status_change
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def snapshot(self) -> Dict[str, Any]:
        return HitlWorkspaceView(self.work_dir).live_status()

    def _clear_launch_failure(self) -> None:
        hitl_launch_status_path(self.work_dir).unlink(missing_ok=True)

    def _record_launch_failure(
        self,
        error: Exception,
        *,
        provider: str,
        mode: str,
    ) -> None:
        detail = str(error).strip() or error.__class__.__name__
        failed_at = utc_now()
        atomic_write_json(
            hitl_launch_status_path(self.work_dir),
            {
                "status": "failed",
                "failed_at": failed_at,
                "updated_at": failed_at,
                "mode": mode,
                "provider": provider,
                "message": f"Research could not start: {detail}",
            },
        )

    def launch(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        provider = str(payload.get("provider", "")).strip().lower()
        if provider not in {"claude", "codex"}:
            raise ValueError(
                "Choose Claude or Codex for HITL research so the workers and manager "
                "can use the same backend."
            )
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
                raise RuntimeError("Research is already active for this workspace.")
            external_owner = active_hitl_workspace_run(self.work_dir)
            if external_owner is not None:
                raise HitlWorkspaceRunActiveError(self.work_dir, external_owner)
            manager = getattr(self.host, "manager", None)
            set_manager_provider = getattr(manager, "set_provider", None)
            if not callable(set_manager_provider):
                raise RuntimeError("The HITL host cannot select a manager backend.")
            set_manager_provider(provider)
            continuation = HitlFrontierStore(self.work_dir).exists()
            mode = "continue" if continuation else "fresh"
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
                                execute()
                    else:
                        execute()
                except Exception as exc:
                    LOGGER.exception(
                        "HITL AutoResearch launch failed for workspace %s",
                        self.work_dir,
                    )
                    try:
                        self._record_launch_failure(
                            exc,
                            provider=provider,
                            mode=mode,
                        )
                    except Exception:
                        LOGGER.exception(
                            "Unable to record HITL AutoResearch launch failure for workspace %s",
                            self.work_dir,
                        )
                self._publish_status()

            self._clear_launch_failure()
            self._thread = threading.Thread(
                target=run,
                name="hitl-autoresearch-launch",
                daemon=True,
            )
            self._thread.start()
        self._publish_status()
        return {
            "status": "accepted",
            "mode": mode,
        }

    def _publish_status(self) -> None:
        if self.on_status_change is not None:
            self.on_status_change(self.snapshot())
