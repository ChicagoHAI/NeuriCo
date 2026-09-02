"""Durable idea catalog and lazy workspace sessions for the HITL web portal."""

from __future__ import annotations

from copy import deepcopy
import json
import threading
from pathlib import Path
from typing import Any, Dict

import yaml

from cli.hitl_launcher import HitlRunController, workspace_for_idea
from core.config_loader import ConfigLoader
from core.hitl_lock import exclusive_file_lock
from core.hitl_manager_host import HitlManagerHost, HitlWebChannel
from core.hitl_util import atomic_write_json
from core.hitl_workspace_view import HitlWorkspaceView
from core.idea_manager import IdeaManager, resolve_ideas_dir


class IdeaPresentationStore:
    """Persist portal-only idea ordering and display names."""

    def __init__(self, workspace_root: Path) -> None:
        self.path = Path(workspace_root) / ".neurico" / "hitl-web" / "catalog.json"
        self.lock_path = self.path.with_suffix(".lock")

    @staticmethod
    def _empty() -> Dict[str, Any]:
        return {"version": 1, "order": [], "names": {}}

    def _read_unlocked(self) -> Dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty()
        if not isinstance(payload, dict):
            return self._empty()
        order = payload.get("order")
        names = payload.get("names")
        return {
            "version": 1,
            "order": [str(value).strip() for value in order if str(value).strip()]
            if isinstance(order, list)
            else [],
            "names": {
                str(key): str(value).strip()
                for key, value in names.items()
                if str(key).strip() and str(value).strip()
            }
            if isinstance(names, dict)
            else {},
        }

    def merge(self, summaries: list[Dict[str, Any]]) -> Dict[str, Any]:
        known = [str(item.get("idea_id", "")).strip() for item in summaries]
        known = [idea_id for idea_id in known if idea_id]
        with exclusive_file_lock(self.lock_path):
            payload = self._read_unlocked()
            existing: list[str] = []
            for idea_id in payload["order"]:
                if idea_id in known and idea_id not in existing:
                    existing.append(idea_id)
            missing = [idea_id for idea_id in known if idea_id not in existing]
            order = missing + existing
            names = {
                idea_id: name
                for idea_id, name in payload["names"].items()
                if idea_id in known
            }
            if order != payload["order"] or names != payload["names"]:
                payload["order"] = order
                payload["names"] = names
                atomic_write_json(self.path, payload)
            return payload

    def prepend(self, idea_id: str) -> None:
        with exclusive_file_lock(self.lock_path):
            payload = self._read_unlocked()
            payload["order"] = [idea_id] + [
                current for current in payload["order"] if current != idea_id
            ]
            atomic_write_json(self.path, payload)

    def rename(self, idea_id: str, display_name: str) -> None:
        value = str(display_name).strip()
        if len(value) > 160:
            raise ValueError("Idea name must be 160 characters or fewer.")
        with exclusive_file_lock(self.lock_path):
            payload = self._read_unlocked()
            if value and value != idea_id:
                payload["names"][idea_id] = value
            else:
                payload["names"].pop(idea_id, None)
            atomic_write_json(self.path, payload)

    def reorder(self, order: list[str], known_ids: list[str]) -> None:
        normalized = [str(value).strip() for value in order]
        if len(normalized) != len(set(normalized)) or set(normalized) != set(known_ids):
            raise ValueError("Idea order must contain every current idea exactly once.")
        with exclusive_file_lock(self.lock_path):
            payload = self._read_unlocked()
            payload["order"] = normalized
            payload["names"] = {
                idea_id: name
                for idea_id, name in payload["names"].items()
                if idea_id in known_ids
            }
            atomic_write_json(self.path, payload)


class HitlWebWorkspaceSession:
    """One existing HITL manager session, without its own HTTP listener."""

    def __init__(
        self,
        *,
        idea_id: str,
        work_dir: Path,
        project_root: Path,
        config: Dict[str, Any],
    ) -> None:
        self.idea_id = idea_id
        self.work_dir = Path(work_dir)
        self.host = HitlManagerHost(
            work_dir=self.work_dir,
            config=config,
            interface="web",
            project_root=project_root,
            title=idea_id,
            open_browser=False,
            serve_web=False,
        )

        def publish_run_status() -> None:
            emit = getattr(self.host.channel, "_emit", None)
            if callable(emit):
                emit({"event": "workspace_changed", "section": "run"})

        self.controller = HitlRunController(
            idea_id=idea_id,
            work_dir=self.work_dir,
            project_root=project_root,
            host=self.host,
            interface="web",
            on_status_change=lambda _status: publish_run_status(),
        )
        self.host.start()

    @property
    def channel(self) -> HitlWebChannel:
        if not isinstance(self.host.channel, HitlWebChannel):
            raise RuntimeError("The workspace does not have a web channel.")
        return self.host.channel

    def stop(self) -> None:
        self.host.stop()


class HitlWebWorkspaceRegistry:
    """List ideas and start workspace sessions only when they are accessed."""

    def __init__(self, *, project_root: Path, config: Dict[str, Any]) -> None:
        self.project_root = Path(project_root)
        self.config = config
        self.idea_manager = IdeaManager(resolve_ideas_dir(self.project_root))
        self.workspace_root = ConfigLoader().get_workspace_parent_dir()
        self.presentation = IdeaPresentationStore(self.workspace_root)
        self._sessions: Dict[str, HitlWebWorkspaceSession] = {}
        self._lock = threading.Lock()

    def _summaries(self) -> list[Dict[str, Any]]:
        return self.idea_manager.list_ideas()

    def known_ids(self) -> list[str]:
        return [str(item["idea_id"]) for item in self._summaries()]

    def require_idea(self, idea_id: str) -> Dict[str, Any]:
        idea = self.idea_manager.get_idea(str(idea_id))
        if idea is None:
            raise ValueError(f"Idea not found: {idea_id}")
        return idea

    def _workspace_path(self, idea_id: str, idea: Dict[str, Any]) -> Path:
        metadata = dict(idea.get("idea", {}).get("metadata", {}) or {})
        local = str(metadata.get("local_workspace", "")).strip()
        if local:
            return Path(local).expanduser()
        return self.workspace_root / idea_id

    def catalog(self) -> Dict[str, Any]:
        summaries = self._summaries()
        presentation = self.presentation.merge(summaries)
        by_id = {str(item["idea_id"]): item for item in summaries}
        items: list[Dict[str, Any]] = []
        for idea_id in presentation["order"]:
            summary = by_id[idea_id]
            idea = self.require_idea(idea_id)
            workspace = self._workspace_path(idea_id, idea)
            items.append(
                {
                    "idea_id": idea_id,
                    "display_name": presentation["names"].get(idea_id, idea_id),
                    "title": str(summary.get("title", "")),
                    "domain": str(summary.get("domain", "unknown")),
                    "status": str(summary.get("status", "unknown")),
                    "created_at": str(summary.get("created_at", "")),
                    "workspace_exists": workspace.is_dir(),
                    "live": {},
                }
            )
        return {"ideas": items, "order": list(presentation["order"])}

    def schema(self) -> Dict[str, Any]:
        schema_path = self.project_root / "ideas" / "schema.yaml"
        payload = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
        idea_schema = deepcopy(payload.get("properties", {}).get("idea", {}))
        properties = idea_schema.get("properties", {})
        properties.pop("comments", None)
        properties.pop("max_directions", None)
        metadata = properties.get("metadata", {}).get("properties", {})
        for key in ("idea_id", "created_at", "status", "updated_at", "local_workspace"):
            metadata.pop(key, None)
        domains = ConfigLoader().get_domains_config().get("domains", {})
        return {
            "schema_version": str(payload.get("version", "")),
            "schema": idea_schema,
            "domains": [
                {"id": domain_id, "name": str(entry.get("name", domain_id))}
                for domain_id, entry in domains.items()
            ],
        }

    def definition(self, idea_id: str) -> Dict[str, Any]:
        payload = self.require_idea(idea_id)
        idea = payload.get("idea", {})
        if not isinstance(idea, dict):
            raise ValueError(f"Idea record is malformed: {idea_id}")
        return {
            "idea_id": idea_id,
            "idea": idea,
            "yaml": yaml.safe_dump(
                {"idea": idea},
                sort_keys=False,
                allow_unicode=True,
            ),
        }

    def submit(self, idea: Dict[str, Any]) -> str:
        if not isinstance(idea, dict):
            raise ValueError("Idea must be an object.")
        clean = deepcopy(idea)
        clean.pop("comments", None)
        metadata = clean.get("metadata")
        if isinstance(metadata, dict):
            for key in ("idea_id", "created_at", "status", "updated_at", "local_workspace"):
                metadata.pop(key, None)
            if not metadata:
                clean.pop("metadata", None)
        idea_id = self.idea_manager.submit_idea({"idea": clean}, validate=True)
        self.presentation.prepend(idea_id)
        return idea_id

    def session(self, idea_id: str) -> HitlWebWorkspaceSession:
        idea_id = str(idea_id).strip()
        self.require_idea(idea_id)
        with self._lock:
            current = self._sessions.get(idea_id)
            if current is not None:
                return current
            work_dir = workspace_for_idea(self.project_root, idea_id)
            current = HitlWebWorkspaceSession(
                idea_id=idea_id,
                work_dir=work_dir,
                project_root=self.project_root,
                config=self.config,
            )
            self._sessions[idea_id] = current
            return current

    def snapshot(self, idea_id: str) -> Dict[str, Any]:
        session = self.session(idea_id)
        snapshot = HitlWorkspaceView(session.work_dir).snapshot()
        snapshot["manager_status"] = session.channel.presentation_status()
        live = snapshot.get("live") if isinstance(snapshot.get("live"), dict) else {}
        current_provider = str(session.host.manager_provider() or "").strip().lower()
        locked_provider = str(live.get("provider") or "").strip().lower()
        snapshot["manager"] = {
            "provider": locked_provider if live.get("active") else current_provider,
            "provider_locked": bool(live.get("active")),
        }
        return snapshot

    def rename(self, idea_id: str, display_name: str) -> None:
        self.require_idea(idea_id)
        self.presentation.rename(idea_id, display_name)

    def select_manager_provider(self, idea_id: str, provider: str) -> str:
        return self.session(idea_id).host.select_manager_provider(provider)

    def reorder(self, order: list[str]) -> None:
        self.presentation.reorder(order, self.known_ids())

    def stop(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.stop()
