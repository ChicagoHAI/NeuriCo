"""Runtime-owned AutoResearch frontier state for the HITL execution path.

The frontier is deliberately separate from main AutoResearch state.  It records
only accepted nodes and finalized attempts; workers and managers interact with
it through HITL tools rather than by reading or writing these files directly.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


class HitlFrontierError(RuntimeError):
    """Raised when persisted HITL frontier state is invalid or cannot change."""


@dataclass(frozen=True)
class HitlFrontierPaths:
    work_dir: Path

    @property
    def root(self) -> Path:
        return self.work_dir / ".neurico" / "hitl"

    @property
    def state(self) -> Path:
        return self.root / "autoresearch_state.json"

    @property
    def nodes(self) -> Path:
        return self.root / "nodes"

    def node_dir(self, node_sha: str) -> Path:
        return self.nodes / node_sha

    def node_json(self, node_sha: str) -> Path:
        return self.node_dir(node_sha) / f"{node_sha}.json"

    def node_plan(self, node_sha: str) -> Path:
        return self.node_dir(node_sha) / f"{node_sha}.md"

    def attempt_json(self, parent_sha: str, candidate_sha: str) -> Path:
        return self.node_dir(parent_sha) / "attempts" / f"{candidate_sha}.json"


class HitlFrontierStore:
    """Small, atomic store for HITL AutoResearch frontier state."""

    def __init__(self, work_dir: Path):
        self.paths = HitlFrontierPaths(Path(work_dir))

    @staticmethod
    def _require_sha(value: str, label: str) -> str:
        sha = str(value).strip()
        if not sha or "/" in sha or "\\" in sha or sha in {".", ".."}:
            raise HitlFrontierError(f"Invalid {label}: {value!r}")
        return sha

    @staticmethod
    def _write_json(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise HitlFrontierError(f"Missing HITL frontier file: {path}") from exc
        except json.JSONDecodeError as exc:
            raise HitlFrontierError(f"Invalid HITL frontier JSON: {path}") from exc
        if not isinstance(payload, dict):
            raise HitlFrontierError(f"HITL frontier file must contain an object: {path}")
        return payload

    def exists(self) -> bool:
        return self.paths.state.is_file()

    def state(self) -> Dict[str, Any]:
        payload = self._read_json(self.paths.state)
        selected = self._require_sha(
            payload.get("selected_frontier_node_sha", ""), "selected frontier node SHA"
        )
        active = payload.get("active_frontier_node_shas")
        if not isinstance(active, list) or not active:
            raise HitlFrontierError(
                "HITL frontier state requires non-empty active_frontier_node_shas"
            )
        active_shas = [self._require_sha(value, "active frontier node SHA") for value in active]
        if len(set(active_shas)) != len(active_shas):
            raise HitlFrontierError("HITL frontier state contains duplicate active node SHAs")
        if selected not in active_shas:
            raise HitlFrontierError("Selected HITL frontier node must be active")
        return {
            "selected_frontier_node_sha": selected,
            "active_frontier_node_shas": active_shas,
        }

    def initialize_root(
        self,
        *,
        node_sha: str,
        plan_text: str,
        objective_score: Dict[str, Any],
        reason_for_acceptance: str,
    ) -> None:
        if self.exists():
            return
        self._write_node(
            parent_node_sha=None,
            node_sha=node_sha,
            plan_text=plan_text,
            objective_score=objective_score,
            reason_for_acceptance=reason_for_acceptance,
        )
        self._write_json(
            self.paths.state,
            {
                "selected_frontier_node_sha": self._require_sha(node_sha, "root node SHA"),
                "active_frontier_node_shas": [self._require_sha(node_sha, "root node SHA")],
            },
        )

    def _write_node(
        self,
        *,
        parent_node_sha: str | None,
        node_sha: str,
        plan_text: str,
        objective_score: Dict[str, Any],
        reason_for_acceptance: str,
    ) -> None:
        node_sha = self._require_sha(node_sha, "node SHA")
        if parent_node_sha is not None:
            parent_node_sha = self._require_sha(parent_node_sha, "parent node SHA")
        if not isinstance(objective_score, dict):
            raise HitlFrontierError(
                "Frontier objective_score must be the complete scoring result object"
            )
        if not str(plan_text).strip():
            raise HitlFrontierError("Accepted frontier node requires non-empty experiment plan")
        if not str(reason_for_acceptance).strip():
            raise HitlFrontierError("Accepted frontier node requires reason_for_acceptance")
        self._write_json(
            self.paths.node_json(node_sha),
            {
                "parent_node_sha": parent_node_sha,
                "node_sha": node_sha,
                "objective_score": objective_score,
                "reason_for_acceptance": str(reason_for_acceptance).strip(),
            },
        )
        plan_path = self.paths.node_plan(node_sha)
        self._write_text(plan_path, str(plan_text))

    def finalize_attempt(
        self,
        *,
        parent_node_sha: str,
        candidate_node_sha: str,
        attempt_id: str,
        proposal_idea_id: str,
        proposal_type: str,
        objective_score: Dict[str, Any],
        accepted: bool,
        reason: str,
        plan_text: str,
    ) -> Dict[str, Any]:
        parent = self._require_sha(parent_node_sha, "parent node SHA")
        candidate = self._require_sha(candidate_node_sha, "candidate node SHA")
        current = self.state()
        if proposal_type not in {"exploitation", "exploration"}:
            raise HitlFrontierError("proposal_type must be exploitation or exploration")
        if not str(attempt_id).strip() or not str(proposal_idea_id).strip():
            raise HitlFrontierError("Finalized attempt requires attempt_id and proposal_idea_id")
        if not isinstance(objective_score, dict):
            raise HitlFrontierError(
                "Attempt objective_score must be the complete scoring result object"
            )
        reason_key = "reason_for_acceptance" if accepted else "reason_for_rejection"
        if not str(reason).strip():
            raise HitlFrontierError(f"Finalized attempt requires {reason_key}")
        attempt_path = self.paths.attempt_json(parent, candidate)
        if attempt_path.is_file():
            existing = self._read_json(attempt_path)
            if (
                existing.get("attempt_id") == str(attempt_id).strip()
                and existing.get("proposal_idea_id") == str(proposal_idea_id).strip()
                and bool(existing.get("accepted")) == bool(accepted)
            ):
                if accepted:
                    self._write_node(
                        parent_node_sha=parent,
                        node_sha=candidate,
                        plan_text=plan_text,
                        objective_score=objective_score,
                        reason_for_acceptance=str(existing.get("reason_for_acceptance", reason)),
                    )
                    active = list(current["active_frontier_node_shas"])
                    if proposal_type == "exploitation":
                        active = [sha for sha in active if sha != parent]
                    if candidate not in active:
                        active.append(candidate)
                    self._write_json(
                        self.paths.state,
                        {
                            "selected_frontier_node_sha": candidate,
                            "active_frontier_node_shas": active,
                        },
                    )
                return existing
            raise HitlFrontierError(
                "A different finalized HITL attempt already exists for this candidate node"
            )
        if parent not in current["active_frontier_node_shas"]:
            raise HitlFrontierError("Candidate parent is not an active HITL frontier node")
        attempt = {
            "attempt_id": str(attempt_id).strip(),
            "node_sha": candidate,
            "proposal_idea_id": str(proposal_idea_id).strip(),
            "proposal_type": proposal_type,
            "objective_score": objective_score,
            "accepted": bool(accepted),
            reason_key: str(reason).strip(),
        }
        self._write_json(attempt_path, attempt)

        if accepted:
            self._write_node(
                parent_node_sha=parent,
                node_sha=candidate,
                plan_text=plan_text,
                objective_score=objective_score,
                reason_for_acceptance=reason,
            )
            active = list(current["active_frontier_node_shas"])
            if proposal_type == "exploitation":
                active = [sha for sha in active if sha != parent]
            if candidate not in active:
                active.append(candidate)
            self._write_json(
                self.paths.state,
                {
                    "selected_frontier_node_sha": candidate,
                    "active_frontier_node_shas": active,
                },
            )
        return attempt

    def select(self, node_sha: str) -> Dict[str, Any]:
        node = self._require_sha(node_sha, "frontier node SHA")
        current = self.state()
        if node not in current["active_frontier_node_shas"]:
            raise HitlFrontierError("Only an active frontier node can be selected")
        updated = {**current, "selected_frontier_node_sha": node}
        self._write_json(self.paths.state, updated)
        return updated

    def mirror_nodes_to(self, audit_root: Path) -> None:
        """Mirror the authoritative node tree into a public audit location.

        The public tree deliberately preserves the exact node/attempt file
        structure and JSON payloads. It is a human-readable mirror, never a
        second state store.
        """
        source = self.paths.nodes
        if not source.is_dir():
            raise HitlFrontierError("Cannot mirror missing HITL frontier nodes")
        target = Path(audit_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.with_name(f".{target.name}.staging")
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(source, staging)
        if target.exists():
            shutil.rmtree(target)
        os.replace(staging, target)

    def node(self, node_sha: str) -> Dict[str, Any]:
        node = self._require_sha(node_sha, "frontier node SHA")
        record = self._read_json(self.paths.node_json(node))
        plan = self.paths.node_plan(node)
        if not plan.is_file():
            raise HitlFrontierError(f"Missing saved plan for frontier node {node}")
        return {
            "parent_node_sha": record.get("parent_node_sha"),
            "node_sha": node,
            "plan": plan.read_text(encoding="utf-8"),
            "objective_score": record.get("objective_score"),
            "reason_for_acceptance": record.get("reason_for_acceptance"),
            "attempt_history": self._direction_attempt_history(node),
        }

    def _direction_attempt_history(
        self,
        node_sha: str,
        *,
        visited: set[str] | None = None,
    ) -> List[Dict[str, Any]]:
        """Return one retained direction's attempt history without copying it.

        An accepted exploitation replaces its parent as the current node for the
        same direction, so it inherits prior attempts. An accepted exploration
        begins a distinct direction and therefore starts with its own history.
        The canonical attempt files stay under the node on which each attempt
        was made; inheritance is a read-time view rather than duplicated state.
        """
        node = self._require_sha(node_sha, "frontier node SHA")
        visited = set() if visited is None else set(visited)
        if node in visited:
            raise HitlFrontierError("HITL frontier contains a cyclic exploitation lineage")
        visited.add(node)

        record = self._read_json(self.paths.node_json(node))
        attempts = self._direct_attempt_history(node)
        parent = record.get("parent_node_sha")
        if parent is None:
            return attempts
        parent_sha = self._require_sha(parent, "frontier parent node SHA")
        origin_path = self.paths.attempt_json(parent_sha, node)
        if not origin_path.is_file():
            raise HitlFrontierError(f"Accepted frontier node {node} has no recorded parent attempt")
        origin = self._read_json(origin_path)
        if not bool(origin.get("accepted")):
            raise HitlFrontierError(f"Frontier node {node} is backed by a rejected parent attempt")
        if origin.get("proposal_type") == "exploitation":
            return self._direction_attempt_history(parent_sha, visited=visited) + attempts
        if origin.get("proposal_type") == "exploration":
            return attempts
        raise HitlFrontierError(
            f"Accepted parent attempt for frontier node {node} has an invalid proposal_type"
        )

    def _direct_attempt_history(self, node_sha: str) -> List[Dict[str, Any]]:
        attempts_dir = self.paths.node_dir(node_sha) / "attempts"
        attempts: List[Dict[str, Any]] = []
        if not attempts_dir.is_dir():
            return attempts
        for attempt_path in sorted(attempts_dir.glob("*.json")):
            attempt = self._read_json(attempt_path)
            attempts.append(
                {
                    "proposal_idea_id": attempt.get("proposal_idea_id"),
                    "proposal_type": attempt.get("proposal_type"),
                    "objective_score": attempt.get("objective_score"),
                    "accepted": attempt.get("accepted"),
                    "reason_for_acceptance": attempt.get("reason_for_acceptance"),
                    "reason_for_rejection": attempt.get("reason_for_rejection"),
                }
            )
        return attempts

    def current_for_worker(self) -> Dict[str, Any]:
        selected = self.state()["selected_frontier_node_sha"]
        node = self.node(selected)
        return {
            "node_sha": selected,
            "objective_score": node["objective_score"],
            "reason_for_acceptance": node["reason_for_acceptance"],
            "attempt_history": node["attempt_history"],
        }
