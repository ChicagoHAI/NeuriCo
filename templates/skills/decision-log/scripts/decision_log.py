"""
Decision Log - Persistent in-flight record of decisions and observations.

Captures the agent's reasoning trail during a run as a DAG of two node types:

1. Decisions  - choices the agent commits to (use log.add)
2. Observations - findings worth noting (use log.observe)

Both kinds share three states: active / suspect / revoked.
Revoke(A) cascades all descendants to "suspect" (not "revoked"); the agent
then triages each via reconfirm() or another revoke(). No node is ever
deleted - the log is an append-only history of the run's reasoning.

Persistence is automatic: every mutation writes the full graph atomically
to a single JSON file (tmp + os.replace, no torn writes on SIGKILL).

See templates/skills/decision-log/SKILL.md for the full agent-facing contract.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

DECISION_CATEGORIES = {
    "model", "dataset", "hyperparam", "eval", "compute", "method",
    "search", "reading",
    "risk",
    "other",
}

OBSERVATION_CATEGORIES = {
    "paper_finding",       # extracted from reading a paper
    "data_property",       # discovered by inspecting data
    "env_fact",            # system / service / environment state
    "experiment_result",   # output of running something
    "code_artifact",       # property of code we examined
    "other",
}

# Union for persistence (so old files with any valid category still load).
CATEGORIES = DECISION_CATEGORIES | OBSERVATION_CATEGORIES
SCHEMA_VERSION = 1


NODE_TYPES = {"decision", "observation"}


@dataclass
class DecisionNode:
    id: str
    category: str
    question: str
    choice: str
    node_type: str = "decision"        # "decision" | "observation"
    premises: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    rationale: str = ""
    status: str = "active"             # active | suspect | revoked
    revoked_root: str | None = None    # id of the revoke that affected this
    created_at: str = ""


class CycleError(ValueError):
    """Raised when adding a premise edge would create a cycle in the DAG."""


class DecisionLog:
    """
    Persistent log of decisions and observations made during an agent run.

    Owns a single JSON file (auto-created at first write) holding the full
    DAG. Every mutation persists atomically before returning, so the file is
    always in a consistent state.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        """
        Initialize the log.

        Args:
            path: Where to persist the log. If the file exists, its contents
                  are loaded. If None, the log is in-memory only (useful for
                  tests).
        """
        self._nodes: dict[str, DecisionNode] = {}
        self._path: Path | None = Path(path) if path is not None else None
        if self._path is not None and self._path.exists():
            self._load()

    # ---------- writes ----------

    def add(self, *, question: str, choice: str, category: str,
            premises: Iterable[str] = (), alternatives: Iterable[str] = (),
            rationale: str = "", id: str | None = None) -> str:
        if category not in DECISION_CATEGORIES:
            raise ValueError(
                f"unknown decision category {category!r}; "
                f"one of {sorted(DECISION_CATEGORIES)}"
            )
        premises = self._validate_premises(premises)
        slug = self._unique(id or self._slug(choice, category))
        # No cycle is possible at add() — nothing references the new node yet.
        node = DecisionNode(
            id=slug, category=category, question=question, choice=choice,
            premises=premises, alternatives=list(alternatives),
            rationale=rationale, created_at=_now(),
        )
        self._nodes[slug] = node
        self._save()
        return slug

    def observe(self, *, observation: str, category: str,
                about: Iterable[str] = (), source: str = "",
                id: str | None = None) -> str:
        """Log an in-flight observation — a finding the agent thinks matters.

        Observations record what the agent NOTICES (paper findings, data
        properties, environmental facts, experiment results) — distinct from
        DECISIONS, which record what the agent CHOOSES. Observations are
        first-class nodes in the same DAG: a decision can premise on an
        observation, an observation can premise on a decision, and cascade
        on revoke works identically.

        Args:
            observation: what was noticed (the analog of `choice` for decisions)
            category: same taxonomy as add()
            about: ids of nodes this observation pertains to (stored as
                premises; if those nodes are later revoked, this observation
                becomes suspect)
            source: where the observation came from — paper:table, file path,
                experiment id, command (stored as the node's rationale)
            id: optional explicit slug

        Returns the node id.
        """
        if category not in OBSERVATION_CATEGORIES:
            raise ValueError(
                f"unknown observation category {category!r}; "
                f"one of {sorted(OBSERVATION_CATEGORIES)}"
            )
        about = self._validate_premises(about)
        slug = self._unique(id or self._slug(observation, category))
        node = DecisionNode(
            id=slug, node_type="observation", category=category,
            question=f"observation about {category}",
            choice=observation, premises=about, alternatives=[],
            rationale=source, created_at=_now(),
        )
        self._nodes[slug] = node
        self._save()
        return slug

    def update(self, id: str, **kwargs) -> None:
        node = self._nodes[id]
        mutable = {"question", "choice", "premises", "alternatives", "rationale"}
        bad = set(kwargs) - mutable
        if bad:
            raise ValueError(f"can't update fields {bad}; mutable: {mutable}")
        if "premises" in kwargs:
            if node.status != "active":
                raise ValueError(
                    f"can't update premises on {node.status!r} node {id!r}; "
                    f"use reconfirm() for suspect nodes, or add a new node"
                )
            new_p = self._validate_premises(kwargs["premises"])
            self._assert_no_cycle(id, new_p)
            node.premises = new_p
            del kwargs["premises"]
        for k, v in kwargs.items():
            setattr(node, k, v)
        self._save()

    def revoke(self, id: str, reason: str = "") -> list[str]:
        """Revoke `id`; mark all descendants as suspect. Returns the suspect list."""
        target = self._nodes[id]
        if target.status == "revoked":
            return []
        target.status = "revoked"
        target.revoked_root = id
        if reason:
            target.rationale = (target.rationale + f" | revoked: {reason}").strip(" |")
        suspects: list[str] = []
        for d in self._descendants(id):
            n = self._nodes[d]
            if n.status == "active":
                n.status = "suspect"
                n.revoked_root = id
                suspects.append(d)
        self._save()
        return suspects

    def triage_order(self) -> list[str]:
        """Return suspect ids in topological order — upstream first.

        Agents should triage in this order so each `reconfirm()` can point at
        premises that are already settled (active again or replaced). The
        order is deterministic: ties broken by id sort.
        """
        suspects = {n.id for n in self.suspects()}
        if not suspects:
            return []
        deps = {sid: {p for p in self._nodes[sid].premises if p in suspects}
                for sid in suspects}
        out: list[str] = []
        remaining = set(suspects)
        while remaining:
            ready = sorted(s for s in remaining if not (deps[s] & remaining))
            if not ready:
                ready = sorted(remaining)   # guard; shouldn't fire on a DAG
            out.extend(ready)
            remaining.difference_update(ready)
        return out

    def reconfirm(self, id: str, premises: list[str] | None = None,
                  rationale: str = "") -> None:
        """Agent confirms a suspect still holds. Optionally rewrites premises.

        If `premises` is None, dead premises (revoked) are dropped automatically.
        """
        node = self._nodes[id]
        if node.status != "suspect":
            raise ValueError(f"can only reconfirm suspect nodes; {id!r} is {node.status}")
        if premises is None:
            premises = [p for p in node.premises if self._nodes[p].status == "active"]
        else:
            for p in premises:
                if p not in self._nodes:
                    raise ValueError(f"premise {p!r} does not exist")
                if self._nodes[p].status != "active":
                    raise ValueError(f"premise {p!r} is not active")
            self._assert_no_cycle(id, premises)
        node.premises = list(premises)
        node.status = "active"
        node.revoked_root = None
        if rationale:
            node.rationale = (node.rationale + f" | reconfirm: {rationale}").strip(" |")
        self._save()

    # ---------- reads ----------

    def get(self, id: str) -> DecisionNode:
        return self._nodes[id]

    def find(self, query: str = "", category: str | None = None,
             active_only: bool = True, node_type: str | None = None) -> list[DecisionNode]:
        if node_type is not None and node_type not in NODE_TYPES:
            raise ValueError(f"unknown node_type {node_type!r}; one of {sorted(NODE_TYPES)}")
        out: list[DecisionNode] = []
        for n in self._nodes.values():
            if active_only and n.status != "active":
                continue
            if category and n.category != category:
                continue
            if node_type and n.node_type != node_type:
                continue
            if query and query.lower() not in f"{n.question} {n.choice} {n.rationale}".lower():
                continue
            out.append(n)
        return out

    def observations(self, active_only: bool = True) -> list[DecisionNode]:
        return self.find(active_only=active_only, node_type="observation")

    def decisions(self, active_only: bool = True) -> list[DecisionNode]:
        return self.find(active_only=active_only, node_type="decision")

    def suspects(self) -> list[DecisionNode]:
        return [n for n in self._nodes.values() if n.status == "suspect"]

    def subtree(self, id: str) -> list[str]:
        """Transitive descendants (does not include `id` itself)."""
        return list(self._descendants(id))

    def premises_of(self, id: str, recursive: bool = False) -> list[str]:
        if not recursive:
            return list(self._nodes[id].premises)
        seen, out, stack = set(), [], list(self._nodes[id].premises)
        while stack:
            p = stack.pop()
            if p in seen:
                continue
            seen.add(p)
            out.append(p)
            stack.extend(self._nodes[p].premises)
        return out

    def export(self, fmt: str = "json") -> str:
        if fmt == "json":
            return json.dumps({k: asdict(v) for k, v in self._nodes.items()}, indent=2)
        if fmt == "dot":
            color = {"active": "black", "suspect": "orange", "revoked": "red"}
            shape = {"decision": "box", "observation": "ellipse"}
            lines = ["digraph decisions {"]
            for n in self._nodes.values():
                lines.append(
                    f'  "{n.id}" [color={color[n.status]},shape={shape[n.node_type]},'
                    f'label="{n.id}\\n{n.choice}"];'
                )
                for p in n.premises:
                    lines.append(f'  "{p}" -> "{n.id}";')
            lines.append("}")
            return "\n".join(lines)
        if fmt == "md":
            lines = ["# Decision Log", ""]
            for n in self._nodes.values():
                marker = "OBSERVATION" if n.node_type == "observation" else "DECISION"
                lines.append(f"## {n.id}  [{marker}, {n.status}]")
                if n.node_type == "observation":
                    lines.append(f"- About: {n.question}")
                    lines.append(f"- Observation: {n.choice}")
                    lines.append(f"- Category: {n.category}")
                    if n.premises:
                        lines.append(f"- Pertains to: {', '.join(n.premises)}")
                    if n.rationale:
                        lines.append(f"- Source: {n.rationale}")
                else:
                    lines.append(f"- Question: {n.question}")
                    lines.append(f"- Choice: {n.choice}")
                    lines.append(f"- Category: {n.category}")
                    if n.premises:
                        lines.append(f"- Premises: {', '.join(n.premises)}")
                    if n.rationale:
                        lines.append(f"- Why: {n.rationale}")
                lines.append("")
            return "\n".join(lines)
        raise ValueError(f"unknown fmt {fmt!r}")

    # ---------- persistence ----------

    def _load(self) -> None:
        data = json.loads(self._path.read_text())
        version = data.get("_schema_version", 1)
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema version {version} at {self._path}; "
                f"this code expects {SCHEMA_VERSION}"
            )
        self._nodes = {
            nid: DecisionNode(**fields)
            for nid, fields in data.get("nodes", {}).items()
        }

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_schema_version": SCHEMA_VERSION,
            "nodes": {nid: asdict(n) for nid, n in self._nodes.items()},
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=False))
        os.replace(tmp, self._path)

    # ---------- internals ----------

    def _validate_premises(self, premises: Iterable[str]) -> list[str]:
        """Materialize premises, reject unknown/non-active/duplicates."""
        premises = list(premises)
        if len(set(premises)) != len(premises):
            raise ValueError(f"duplicate premise in list: {premises}")
        for p in premises:
            if p not in self._nodes:
                raise ValueError(f"premise {p!r} does not exist")
            if self._nodes[p].status != "active":
                raise ValueError(
                    f"premise {p!r} is {self._nodes[p].status!r}; can only build on active premises"
                )
        return premises

    def _slug(self, choice: str, category: str) -> str:
        base = f"{category}-{choice}".lower()
        cleaned = "".join(c if c.isalnum() or c == "-" else "-" for c in base)
        while "--" in cleaned:
            cleaned = cleaned.replace("--", "-")
        return cleaned.strip("-")[:40] or category

    def _unique(self, slug: str) -> str:
        if slug not in self._nodes:
            return slug
        i = 2
        while f"{slug}-{i}" in self._nodes:
            i += 1
        return f"{slug}-{i}"

    def _descendants(self, id: str) -> Iterable[str]:
        seen, queue = {id}, [id]
        while queue:
            cur = queue.pop(0)
            for nid, n in self._nodes.items():
                if cur in n.premises and nid not in seen:
                    seen.add(nid)
                    queue.append(nid)
                    yield nid

    def _assert_no_cycle(self, id: str, premises: Iterable[str]) -> None:
        descendants = set(self._descendants(id))
        descendants.add(id)
        for p in premises:
            if p in descendants:
                raise CycleError(f"adding premise {p!r} to {id!r} would create a cycle")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


