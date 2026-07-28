"""Read-only projection of canonical HITL workspace artifacts for the web UI.

The browser never reads workspace files directly and never reconstructs research
state from SSE fragments.  This module is the one translation boundary between
the durable HITL records and a complete UI snapshot.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from core.hitl import HitlIdeaLog, HitlValidationError
from core.hitl_frontier import HitlFrontierError, HitlFrontierStore
from core.hitl_manager_history import HitlManagerHistory
from core.hitl_manager_inbox import HitlManagerInbox
from core.hitl_runtime_state import HitlRuntimeState
from core.hitl_manager_context import HitlManagerContext
from core.hitl_paths import hitl_state_dir
from core.hitl_whiteboard import hitl_whiteboard_path
from core.whiteboard import MAX_TIP_CONTENT_CHARS


class HitlWorkspaceViewError(RuntimeError):
    """A durable HITL artifact cannot be faithfully presented."""


def _read_object(path: Path, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HitlWorkspaceViewError(f"Missing {label}: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise HitlWorkspaceViewError(f"Unreadable {label}: {path}") from exc
    if not isinstance(value, dict):
        raise HitlWorkspaceViewError(f"{label.capitalize()} must be a JSON object: {path}")
    return value


def _as_records(value: Any, label: str) -> List[Dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise HitlWorkspaceViewError(f"{label} must be a list of objects.")
    return [dict(item) for item in value]


class HitlWorkspaceView:
    """Build an immutable, complete UI snapshot from one HITL workspace."""

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.root = hitl_state_dir(self.work_dir)

    def snapshot(self) -> Dict[str, Any]:
        if not self.root.is_dir():
            raise HitlWorkspaceViewError(
                f"This workspace has no HITL state at {self.root}."
            )
        ideas = self._ideas()
        nodes, attempts, frontier = self._frontier()
        whiteboard = self._whiteboard()
        research = self._research_state()
        inbox = self._inbox()
        conversation = self._conversation(inbox)
        return {
            "workspace": self.work_dir.name,
            "autoresearch": self._autoresearch_status(),
            "conversation": conversation,
            "inbox": inbox,
            "research": research,
            "ideas": ideas,
            "frontier": frontier,
            "nodes": nodes,
            "attempts": attempts,
            "whiteboard": whiteboard,
            "activity": self._activity(ideas, nodes, attempts, whiteboard),
            "context": self._context(),
        }

    def _autoresearch_status(self) -> Dict[str, Any]:
        has_frontier_state = HitlFrontierStore(self.work_dir).exists()
        return {
            "mode": "continue" if has_frontier_state else "fresh",
            "has_frontier_state": has_frontier_state,
        }

    def _ideas(self) -> List[Dict[str, Any]]:
        log = HitlIdeaLog(self.work_dir)
        records = log.records()
        seen: set[str] = set()
        for record in records:
            try:
                HitlIdeaLog.validate(record, existing_ids=seen)
            except HitlValidationError as exc:
                raise HitlWorkspaceViewError(
                    f"Invalid finalized HITL idea {record.get('idea_id', '<unknown>')}: {exc}"
                ) from exc
            seen.add(str(record["idea_id"]))
        return records

    def _frontier(self) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
        store = HitlFrontierStore(self.work_dir)
        if not store.exists():
            return [], [], {"selected_frontier_node_sha": None, "active_frontier_node_shas": []}
        try:
            state = store.state(allow_unselected=True)
        except HitlFrontierError as exc:
            raise HitlWorkspaceViewError(str(exc)) from exc

        node_paths = sorted((self.root / "nodes").glob("*/*.json"))
        nodes: List[Dict[str, Any]] = []
        attempts: List[Dict[str, Any]] = []
        nodes_by_sha: Dict[str, Dict[str, Any]] = {}
        for path in node_paths:
            payload = _read_object(path, "frontier node")
            node_sha = str(payload.get("node_sha", "")).strip()
            if not node_sha or node_sha != path.stem:
                raise HitlWorkspaceViewError(f"Invalid node identity in {path}")
            if node_sha in nodes_by_sha:
                raise HitlWorkspaceViewError(f"Duplicate HITL node record for {node_sha}")
            plan_path = path.with_suffix(".md")
            if not plan_path.is_file():
                raise HitlWorkspaceViewError(f"Accepted HITL node is missing its saved plan: {node_sha}")
            try:
                payload["plan"] = plan_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise HitlWorkspaceViewError(
                    f"Accepted HITL node has an unreadable saved plan: {node_sha}"
                ) from exc
            payload["active"] = node_sha in state["active_frontier_node_shas"]
            payload["selected"] = node_sha == state["selected_frontier_node_sha"]
            nodes_by_sha[node_sha] = payload
            nodes.append(payload)

        for parent_dir in sorted((self.root / "nodes").glob("*")):
            attempts_dir = parent_dir / "attempts"
            if not attempts_dir.is_dir():
                continue
            parent_sha = parent_dir.name
            if parent_sha not in nodes_by_sha:
                raise HitlWorkspaceViewError(
                    f"Attempt history has no parent frontier node: {parent_sha}"
                )
            for path in sorted(attempts_dir.glob("*.json")):
                payload = _read_object(path, "frontier attempt")
                candidate = str(payload.get("node_sha", "")).strip()
                if not candidate or candidate != path.stem:
                    raise HitlWorkspaceViewError(f"Invalid attempt identity in {path}")
                if not isinstance(payload.get("accepted"), bool):
                    raise HitlWorkspaceViewError(f"Attempt accepted flag must be boolean: {path}")
                if payload["accepted"] and candidate not in nodes_by_sha:
                    raise HitlWorkspaceViewError(
                        f"Accepted attempt {candidate} is missing its frontier node record."
                    )
                payload["parent_node_sha"] = parent_sha
                attempts.append(payload)

        missing_active = [sha for sha in state["active_frontier_node_shas"] if sha not in nodes_by_sha]
        if missing_active:
            raise HitlWorkspaceViewError(
                "Active frontier refers to missing node record(s): " + ", ".join(missing_active)
            )
        return nodes, attempts, state

    def _whiteboard(self) -> Dict[str, Any]:
        path = hitl_whiteboard_path(self.work_dir)
        if not path.exists():
            return {"tips": []}
        payload = _read_object(path, "HITL whiteboard")
        tips = _as_records(payload.get("tips", []), "HITL whiteboard tips")
        for tip in tips:
            content = str(tip.get("content", ""))
            if not str(tip.get("id", "")).strip() or not content.strip():
                raise HitlWorkspaceViewError("Every HITL whiteboard tip requires id and content.")
            if len(content) > MAX_TIP_CONTENT_CHARS:
                tip["content"] = content[:MAX_TIP_CONTENT_CHARS]
            if not isinstance(tip.get("affects", []), list) or any(
                not isinstance(value, str) for value in tip.get("affects", [])
            ):
                raise HitlWorkspaceViewError("Every HITL whiteboard tip affects field must be a list of paths.")
        return {"tips": tips}

    def _research_state(self) -> Dict[str, Any]:
        path = self.work_dir / ".neurico" / "research_state.json"
        if not path.exists():
            return {"narrative": "", "crux": "", "hypotheses": [], "open_questions": []}
        state = _read_object(path, "research state")
        for key in ("narrative", "crux"):
            if key in state and not isinstance(state[key], str):
                raise HitlWorkspaceViewError(f"Research state {key} must be a string.")
        for key in ("hypotheses", "experiments", "findings", "decisions"):
            if key in state:
                _as_records(state[key], f"research state {key}")
        questions = state.get("open_questions", [])
        if not isinstance(questions, list) or any(not isinstance(item, str) for item in questions):
            raise HitlWorkspaceViewError("Research state open_questions must be a list of strings.")
        return state

    def _context(self) -> Dict[str, int]:
        manager_dir = self.root / "manager"
        if not (manager_dir / "context.jsonl").exists():
            return {"used_tokens": 0, "limit_tokens": 300_000, "percent": 0}
        try:
            return HitlManagerContext(manager_dir).usage()
        except Exception as exc:
            raise HitlWorkspaceViewError("Could not read manager prompt context.") from exc

    @staticmethod
    def _artifact_timestamp(path: Path) -> str:
        try:
            return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except OSError as exc:
            raise HitlWorkspaceViewError(f"Could not read artifact timestamp: {path}") from exc

    def _activity(
        self,
        ideas: List[Dict[str, Any]],
        nodes: List[Dict[str, Any]],
        attempts: List[Dict[str, Any]],
        whiteboard: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Chronological activity sourced only from durable HITL artifacts."""
        activity: List[Dict[str, Any]] = [
            {
                "id": f"idea:{idea['idea_id']}",
                "kind": "idea",
                "timestamp": idea["timestamp"],
                "record": idea,
            }
            for idea in ideas
        ]
        for node in nodes:
            path = self.root / "nodes" / str(node["node_sha"]) / f"{node['node_sha']}.json"
            activity.append({
                "id": f"node:{node['node_sha']}",
                "kind": "node",
                "timestamp": self._artifact_timestamp(path),
                "record": node,
            })
        for attempt in attempts:
            if bool(attempt.get("accepted")):
                continue
            parent = str(attempt["parent_node_sha"])
            candidate = str(attempt["node_sha"])
            path = self.root / "nodes" / parent / "attempts" / f"{candidate}.json"
            activity.append({
                "id": f"attempt:{candidate}",
                "kind": "attempt",
                "timestamp": self._artifact_timestamp(path),
                "record": attempt,
            })
        for tip in whiteboard["tips"]:
            timestamp = tip.get("written_at")
            if isinstance(timestamp, (int, float)):
                timestamp = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            if not isinstance(timestamp, str) or not timestamp.strip():
                timestamp = self._artifact_timestamp(hitl_whiteboard_path(self.work_dir))
            activity.append({
                "id": f"whiteboard:{tip['id']}",
                "kind": "whiteboard",
                "timestamp": timestamp,
                "record": tip,
            })
        return sorted(activity, key=lambda entry: str(entry["timestamp"]))

    def _conversation(self, inbox: Dict[str, Any]) -> List[Dict[str, str]]:
        manager_dir = self.root / "manager"
        path = manager_dir / "history.sqlite"
        if not path.exists():
            return []
        try:
            records = HitlManagerHistory.read_messages(manager_dir)
        except Exception as exc:
            raise HitlWorkspaceViewError("Could not read manager conversation history.") from exc
        # A request is a manager conversation turn with an additional structured
        # action surface.  Keep it in the durable transcript; the browser hides
        # that exact turn only while its request panel remains unresolved.
        del inbox
        conversation: List[Dict[str, str]] = []
        for record in records:
            metadata = record.get("metadata")
            if not isinstance(metadata, dict) or metadata.get("visibility") != "human":
                continue
            if metadata.get("kind") not in {
                "human_message",
                "human_reply",
                "human_request",
                "manager_reply",
            }:
                continue
            content = str(record.get("content") or "").strip()
            if not content or content.lower() == "null":
                continue
            normalized = dict(record)
            normalized["content"] = content
            conversation.append(normalized)
        return conversation

    def _inbox(self) -> Dict[str, Any]:
        try:
            payload = HitlManagerInbox(self.work_dir).snapshot()
        except Exception as exc:
            raise HitlWorkspaceViewError("Could not read the manager input state.") from exc
        queue = _as_records(payload.get("queue", []), "manager input queue")
        for entry in queue:
            if not str(entry.get("id", "")).strip() or not str(entry.get("text", "")).strip():
                raise HitlWorkspaceViewError("Every queued manager message requires id and text.")
        pending = HitlRuntimeState(self.work_dir).pending_worker_command()
        record_id = str((pending or {}).get("human_request_record_id") or "").strip()
        request = None
        if record_id:
            request_key = str(pending.get("request_key", "")).strip()
            try:
                record = next(
                    item
                    for item in HitlManagerHistory.read_messages(self.root / "manager")
                    if str(item.get("record_id", "")) == record_id
                )
            except StopIteration as exc:
                raise HitlWorkspaceViewError("Runtime pending request is missing its transcript record.") from exc
            metadata = record.get("metadata")
            if (
                not request_key
                or not isinstance(metadata, dict)
                or metadata.get("kind") != "human_request"
                or str(metadata.get("request_key", "")) != request_key
            ):
                raise HitlWorkspaceViewError("Runtime pending request is incomplete.")
            options = metadata.get("options")
            if not isinstance(options, list):
                raise HitlWorkspaceViewError("Runtime pending request options are invalid.")
            request = {
                "request_key": request_key,
                "message": str(record.get("content", "")).strip(),
                "options": [
                    {"id": f"option_{index + 1}", "text": str(option)}
                    for index, option in enumerate(options)
                    if str(option).strip()
                ],
                "created_at": record.get("created_at", ""),
                "conversation_record_id": record_id,
            }
        return {"queue": queue, "pending_request": request}
