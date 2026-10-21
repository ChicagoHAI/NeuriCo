"""Stage definitions for the ideation pipeline.

Shape (sai-review's discipline: Python orchestrates, the agent does the thinking inside one
workspace per stage):

    context (code: safety_kb -> findings.json, registry_snapshot.json, dedup_candidates.json, context/*.md)
      └─ problem    (agent: skill `problem`,    role ideation.problem)
           └─ ideation   (agent: skill `ideation`,   role ideation.ideation)
                └─ idea_judge (agent: skill `idea-judge`, role ideation.idea_judge)

The problem/ideation split is deliberate: the model first commits to ONE open problem
(``problem.json``) and only then generates ideas for it, so it cannot pick a problem that
happens to fit an idea it already wanted. The judge did not write the ideas it scores.

Ported from sai-review ``src/sai_digest/stages.py`` (see ``NOTICE.md``), trimmed to the
three ideation stages plus the code stage that feeds them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Stage:
    id: str
    kind: str                                   # "code" | "agent"
    after: Tuple[str, ...] = ()                 # upstream stage ids
    skill: str = ""                             # templates/ideation/skills/<skill>.md (agent stages)
    role: str = ""                              # config/agents.yaml role (agent stages)
    inputs: Tuple[Tuple[str, str], ...] = ()    # (artifact name, workspace-relative target)
    outputs: Tuple[Tuple[str, Optional[str]], ...] = ()  # (workspace source, schema or None)
    progress: str = ""
    text_outputs: Tuple[str, ...] = field(default_factory=tuple)


_CONTEXT = (
    ("context/campaign.md", "input/context/campaign.md"),
    ("context/catalog.md", "input/context/catalog.md"),
    ("context/knowledge-base.md", "input/context/knowledge-base.md"),
)

# What the code stage writes into artifacts/ (every agent stage reads a subset).
CONTEXT_ARTIFACTS = ("findings.json", "registry_snapshot.json", "dedup_candidates.json",
                     *[a for a, _ in _CONTEXT])

STAGES: List[Stage] = [
    Stage(id="context", kind="code", progress="collecting findings, runs, inbox and in-flight work"),
    Stage(
        id="problem", kind="agent", after=("context",), skill="problem", role="ideation.problem",
        inputs=(("findings.json", "input/findings.json"),
                ("registry_snapshot.json", "input/registry_snapshot.json"),
                ("dedup_candidates.json", "input/dedup_candidates.json"),
                *_CONTEXT),
        outputs=(("output/problem.json", "problem.schema.json"),),
        progress="choosing one open problem",
    ),
    Stage(
        id="ideation", kind="agent", after=("problem",), skill="ideation", role="ideation.ideation",
        inputs=(("findings.json", "input/findings.json"),
                ("problem.json", "input/problem.json"),
                ("registry_snapshot.json", "input/registry_snapshot.json"),
                *_CONTEXT),
        outputs=(("output/ideas.json", "ideas.schema.json"),),
        progress="generating ideas for the open problem",
    ),
    Stage(
        id="idea_judge", kind="agent", after=("ideation",), skill="idea-judge", role="ideation.idea_judge",
        inputs=(("findings.json", "input/findings.json"),
                ("problem.json", "input/problem.json"),
                ("ideas.json", "input/ideas.json"),
                ("registry_snapshot.json", "input/registry_snapshot.json"),
                ("dedup_candidates.json", "input/dedup_candidates.json"),
                *_CONTEXT),
        outputs=(("output/ideas_ranked.json", "ideas_ranked.schema.json"),),
        progress="judging and ranking ideas",
    ),
]

STAGE_BY_ID: Dict[str, Stage] = {s.id: s for s in STAGES}
AGENT_STAGES = [s for s in STAGES if s.kind == "agent"]
AGENT_STAGE_IDS = tuple(s.id for s in AGENT_STAGES)


def downstream_of(stage_ids) -> set:
    """``stage_ids`` plus every stage that (transitively) depends on them."""
    out = set(stage_ids)
    changed = True
    while changed:
        changed = False
        for s in STAGES:
            if s.id not in out and any(a in out for a in s.after):
                out.add(s.id)
                changed = True
    return out


def artifact_name(workspace_source: str) -> str:
    """Workspace ``output/<x>`` -> artifacts ``<x>`` (nested paths kept)."""
    return workspace_source.split("output/", 1)[-1]
