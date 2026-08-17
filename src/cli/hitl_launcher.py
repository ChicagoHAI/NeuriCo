"""Shared workspace and run-launch plumbing for HITL user interfaces."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import yaml

from core.config_loader import ConfigLoader
from core.hitl_frontier import HitlFrontierStore
from core.hitl_lock import (
    HitlWorkspaceRunActiveError,
    active_hitl_workspace_run,
    select_hitl_manager_provider,
)
from core.hitl_manager_inbox import HitlManagerInbox
from core.hitl_paths import hitl_launch_requests_dir, hitl_launch_status_path
from core.hitl_run_control import request_hitl_run_stop
from core.hitl_util import atomic_write_json, utc_now
from core.hitl_workspace_view import HitlWorkspaceView
from core.idea_manager import IdeaManager, resolve_ideas_dir


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

    def snapshot(self) -> Dict[str, Any]:
        return HitlWorkspaceView(self.work_dir).live_status()

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
            external_owner = active_hitl_workspace_run(self.work_dir)
            if external_owner is not None:
                raise HitlWorkspaceRunActiveError(self.work_dir, external_owner)
            if HitlManagerInbox(self.work_dir).snapshot().get("active") is not None:
                raise RuntimeError(
                    "Wait for the current manager message to finish before starting research."
                )
            launch_path = hitl_launch_status_path(self.work_dir)
            if launch_path.exists():
                try:
                    launch_state = json.loads(launch_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    launch_state = {}
                saved_status = str(launch_state.get("status", "")).strip()
                if saved_status in {"starting", "running"}:
                    try:
                        launch_age = max(0.0, time.time() - launch_path.stat().st_mtime)
                    except OSError:
                        launch_age = 0.0
                    handoff_grace = 30.0 if saved_status == "starting" else 5.0
                    if launch_age < handoff_grace:
                        raise RuntimeError("Research is already starting for this workspace.")
                    stale_request_id = str(launch_state.get("request_id", "")).strip()
                    if stale_request_id:
                        requests_dir = hitl_launch_requests_dir(
                            ConfigLoader().get_workspace_parent_dir()
                        )
                        for suffix in (".json", ".json.claimed"):
                            stale_request = requests_dir / (
                                f"request.{self.idea_id}.{stale_request_id}{suffix}"
                            )
                            stale_request.unlink(missing_ok=True)
            select_hitl_manager_provider(self.work_dir, provider)
            continuation = HitlFrontierStore(self.work_dir).exists()
            mode = "continue" if continuation else "fresh"
            request_id = uuid.uuid4().hex
            request = {
                "version": 1,
                "request_id": request_id,
                "idea_id": self.idea_id,
                "work_dir": str(self.work_dir.resolve()),
                "project_root": str(self.project_root.resolve()),
                "provider": provider,
                "iterations": iterations,
                "write_paper": bool(payload.get("write_paper", False)),
                "paper_style": None if style == "auto" else style,
                "github": bool(payload.get("github", False)),
                "mode": mode,
                "interface": self.interface,
                "created_at": utc_now(),
            }
            requests_dir = hitl_launch_requests_dir(ConfigLoader().get_workspace_parent_dir())
            requests_dir.mkdir(parents=True, exist_ok=True)
            request_path = requests_dir / f"request.{self.idea_id}.{request_id}.json"
            prepare_handoff = getattr(self.host, "prepare_run_handoff", None)
            cancel_handoff = getattr(self.host, "cancel_run_handoff", None)
            if callable(prepare_handoff):
                prepare_handoff()
            try:
                atomic_write_json(request_path, request)
                atomic_write_json(
                    hitl_launch_status_path(self.work_dir),
                    {
                        "status": "starting",
                        "request_id": request_id,
                        "created_at": request["created_at"],
                        "updated_at": request["created_at"],
                        "mode": mode,
                        "provider": provider,
                    },
                )
                if os.environ.get("NEURICO_HITL_DOCKER_HANDOFF") != "1":
                    log_path = self.work_dir / "logs" / "hitl_runtime.log"
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    with log_path.open("ab") as output:
                        process = subprocess.Popen(
                            [
                                sys.executable,
                                str(self.project_root / "src" / "cli" / "hitl_run_worker.py"),
                                "--request",
                                str(request_path),
                            ],
                            cwd=self.project_root,
                            stdin=subprocess.DEVNULL,
                            stdout=output,
                            stderr=subprocess.STDOUT,
                            start_new_session=True,
                            close_fds=True,
                        )
                        threading.Thread(
                            target=process.wait,
                            name=f"hitl-run-reaper-{request_id[:8]}",
                            daemon=True,
                        ).start()
            except Exception:
                request_path.unlink(missing_ok=True)
                if callable(cancel_handoff):
                    cancel_handoff()
                raise
        self._publish_status()
        return {
            "status": "accepted",
            "mode": mode,
        }

    def stop(self) -> Dict[str, Any]:
        """Request a clean stop through the workspace-owned run protocol."""
        with self._lock:
            result = request_hitl_run_stop(
                self.work_dir,
                requested_by=self.interface,
            )
        self._publish_status()
        return result

    def _publish_status(self) -> None:
        if self.on_status_change is not None:
            self.on_status_change(self.snapshot())
