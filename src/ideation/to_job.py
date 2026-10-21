"""Ranked ideas -> NeuriCo idea YAMLs and planner job specs.

``ideas_ranked.top`` joined with ``ideas.json`` gives, for each top idea (at most the campaign's
``planner.max_new_jobs_per_run``):

* ``queue/ideas/<planner_run>-<slug>.yaml``: NeuriCo's idea schema (v1.2), a pure projection of the
  idea's ``neurico`` block (sai-review's ``to_neurico``), domain ``ai_safety``; the judge's scores,
  the distinctness line, the closest prior work and the feed ids travel under ``metadata``.
* ``queue/proposals/<planner_run>/<n>-<slug>.yaml``: the job spec in exactly the shape the interim
  ideator wrote and ``safety.planner.validate_proposals`` accepts: ``kind``, ``title``, ``priority``,
  ``novelty``, ``finding_criterion``, ``rationale``, ``resources``, ``neurico`` (idea file plus the
  campaign's backbone defaults), ``finding_id`` for validate jobs, and ``extra`` (scores, canonical
  keys, idea id). ``validate_proposals`` moves ``novelty`` / ``finding_criterion`` into ``extra`` and
  stays the single gate into the queue.
* ``queue/proposals/<planner_run>/planning_log.md``: the problem, every scored idea with its codes
  (rejected ideas are kept on record), the ranking and the judge's notes.

Priority: rank 1 -> 90, each further rank -6, plus 2 x (safety_impact - 3), clamped to 10..90, so
the judge's order is the queue's order within a round and a round never outranks a human's 90+.

Ported in part from sai-review ``src/sai_digest/neurico.py`` (see ``NOTICE.md``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from safety.kb import KB, PROJECT_ROOT, save_yaml, slugify

from .dedup import idea_keys

DEFAULT_DOMAIN = "ai_safety"
DEFAULT_GPU_GB = 40.0
PRIORITY_TOP, PRIORITY_STEP, PRIORITY_MIN, PRIORITY_MAX = 90, 6, 10, 90
RESULT_SCHEMA_NOTE = "results/safety/*.json in the neurico-safety-result/v1 schema"


def job_kind(idea: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """(kind, finding_id): the idea's explicit ``neurico.job_kind``, else validate when it names a
    finding to reproduce, optimise when it carries a sealed ``evaluation``, else explore."""
    n = idea.get("neurico") or {}
    finding = n.get("finding_id") or None
    kind = n.get("job_kind")
    if not kind:
        kind = "validate" if finding else ("optimise" if n.get("evaluation") else "explore")
    if kind == "validate" and not finding:
        kind = "explore"
    return kind, (finding if kind == "validate" else None)


def priority_for(rank: int, scores: Dict[str, Any]) -> int:
    impact = int((scores or {}).get("safety_impact") or 3)
    value = PRIORITY_TOP - PRIORITY_STEP * (max(1, int(rank)) - 1) + 2 * (impact - 3)
    return max(PRIORITY_MIN, min(PRIORITY_MAX, value))


def gpu_memory_for(idea: Dict[str, Any], models: Dict[str, Any], campaign: Dict[str, Any]) -> float:
    """The GPU reservation: the largest catalog ``gpu_memory_gb`` among the idea's subject models,
    else the campaign's subjects, else a default; 0 for cpu-only ideas."""
    n = idea.get("neurico") or {}
    compute = (n.get("constraints") or {}).get("compute")
    if compute == "cpu_only":
        return 0.0
    named = [float(models[m].get("gpu_memory_gb") or 0) for m in (n.get("models") or []) if m in models]
    named = [g for g in named if g > 0]
    if named:
        return max(named)
    subjects = ((campaign.get("target_models") or {}).get("subjects") or [])
    fallback = [float(models[m].get("gpu_memory_gb") or 0) for m in subjects if m in models]
    fallback = [g for g in fallback if g > 0]
    return max(fallback) if fallback else DEFAULT_GPU_GB


def to_idea_yaml(idea: Dict[str, Any], *, problem: Dict[str, Any], planner_run: str, campaign_name: str,
                 scored: Optional[Dict[str, Any]] = None, rank: Optional[int] = None,
                 author: str = "neurico-ideation") -> Dict[str, Any]:
    """NeuriCo idea document (schema v1.2). Pure: every field is already on the idea; this re-shapes."""
    n = idea.get("neurico") or {}
    bg = n.get("background") or {}
    meth = n.get("methodology") or {}
    cons = n.get("constraints") or {}
    kind, finding = job_kind(idea)
    doc: Dict[str, Any] = {"idea": {
        "title": idea["title"][:200],
        "domain": n.get("domain") or DEFAULT_DOMAIN,
        "hypothesis": idea["hypothesis"],
        "background": {
            "description": bg.get("description") or idea.get("method", ""),
            "papers": [{"url": p["url"], "description": p.get("description", "")}
                       for p in bg.get("papers", []) if isinstance(p, dict) and p.get("url")],
        },
        "methodology": {
            "approach": meth.get("approach") or idea.get("method", ""),
            "steps": list(meth.get("steps") or idea.get("method_steps") or []),
            "baselines": list(meth.get("baselines") or []),
            "metrics": list(meth.get("metrics") or []),
        },
        "constraints": {k: v for k, v in cons.items() if v not in (None, "", [], 0)},
        "expected_outputs": list(n.get("expected_outputs") or []),
        "evaluation_criteria": list(n.get("evaluation_criteria") or []),
    }}
    if bg.get("datasets"):
        doc["idea"]["background"]["datasets"] = bg["datasets"]
    if bg.get("code_references"):
        doc["idea"]["background"]["code_references"] = bg["code_references"]
    if n.get("evaluation"):
        doc["idea"]["evaluation"] = n["evaluation"]
    if finding:
        doc["idea"]["validation"] = {"finding_id": finding,
                                     "instructions": "Reproduce the finding on fresh samples with a different judge (and "
                                                     "provider where possible); write validation/verdict.yaml with finding_id, "
                                                     "verdict (reproduced | refuted | inconclusive), summary and evidence "
                                                     "(numbers with n and CIs)."}
    doc["metadata"] = {
        "author": author, "source": "ideation", "planner_run": planner_run, "campaign": campaign_name,
        "idea_id": idea.get("id"), "problem_title": problem.get("title"), "axis": idea.get("axis"),
        "category": idea.get("category"), "job_kind": kind,
        "source_ids": list(idea.get("builds_on") or []),
        "expected_result": idea.get("expected_result"), "risks": idea.get("risks"),
        "closest_prior_work": idea.get("closest_prior_work"), "resources": idea.get("resources"),
        "scores": (scored or {}).get("scores"), "distinctness": (scored or {}).get("distinctness"),
        "judge_rationale": (scored or {}).get("rationale"), "rank": rank,
    }
    return doc


def to_job_spec(idea: Dict[str, Any], *, idea_file: str, rank: int, scored: Dict[str, Any], top: Dict[str, Any],
                campaign: Dict[str, Any], models: Dict[str, Any], problem: Dict[str, Any]) -> Dict[str, Any]:
    """The proposal YAML ``validate_proposals`` reads (the interim ideator's format)."""
    kind, finding = job_kind(idea)
    n = idea.get("neurico") or {}
    scores = scored.get("scores") or {}
    defaults = dict(((campaign.get("defaults") or {}).get("neurico")) or {})
    neurico = {"idea_file": idea_file, **{k: v for k, v in defaults.items() if k != "idea_file"}}
    novelty = (idea.get("closest_prior_work") or "").strip()
    novelty += f" Judge: novelty {scores.get('novelty')}/5, duplication risk {scores.get('duplication_risk')}/5 (lower is better)."
    if scored.get("distinctness"):
        novelty += f" Distinct from its nearest sibling: {scored['distinctness']}"
    spec: Dict[str, Any] = {
        "kind": kind,
        "title": idea["title"],
        "priority": priority_for(rank, scores),
        "novelty": novelty.strip(),
        "finding_criterion": idea.get("expected_result", ""),
        "rationale": f"Rank {rank} for the problem '{problem.get('title')}'. {top.get('rationale', '')}".strip(),
        "resources": {"gpu_memory_gb": gpu_memory_for(idea, models, campaign),
                      "api_budget_usd": float((n.get("constraints") or {}).get("budget") or 0.0)},
        "neurico": neurico,
        "extra": {"idea_id": idea.get("id"), "axis": idea.get("axis"), "scores": scores,
                  "distinctness": scored.get("distinctness"), "reject_reasons": scored.get("reject_reasons"),
                  "builds_on": list(idea.get("builds_on") or []), "canonical_keys": idea_keys(idea),
                  "problem_title": problem.get("title"), "models": list(n.get("models") or []),
                  "evals": list(n.get("evals") or [])},
    }
    if finding:
        spec["finding_id"] = finding
    return spec


def planning_log(problem: Dict[str, Any], ideas: Dict[str, Any], ranked: Dict[str, Any], written: List[Dict[str, Any]],
                 *, planner_run: str) -> str:
    by_id = {i["id"]: i for i in ideas.get("ideas", [])}
    lines = [f"# Planning log: {planner_run} (ideate)", "",
             "Three agent stages: problem selection, idea generation, independent judging "
             "(src/ideation/; artifacts in ideation/ next to this file).", "",
             f"## Open problem: {problem.get('title')}", "", problem.get("statement", ""), "",
             f"**Why now.** {problem.get('why_now', '')}", "", f"**Blocking.** {problem.get('blocking', '')}", "",
             f"**What would change our mind.** {problem.get('what_would_change_our_mind', '')}", "",
             f"Evidence: {', '.join(problem.get('evidence_ids') or [])}", ""]
    alts = problem.get("alternatives_considered") or []
    if alts:
        lines += ["Alternatives considered:"] + [f"- {a.get('title')}: {a.get('why_not', '')}" for a in alts] + [""]
    lines += ["## Queued from this round", ""]
    lines += [f"- {w['n']}. [{w['kind']}, p{w['priority']}] {w['title']} -> {w['idea_file']}" for w in written] or ["(none)"]
    lines += ["", f"## Every candidate ({len(ideas.get('ideas', []))} ideas, judge's scores)", "",
              "| idea | axis | title | novelty | feasibility | impact | replicability | dup risk | reject reasons |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in ranked.get("scored", []):
        idea = by_id.get(s["idea_id"], {})
        sc = s.get("scores", {})
        codes = ", ".join(r for r in (s.get("reject_reasons") or []) if r != "none") or "none"
        lines.append(f"| {s['idea_id']} | {idea.get('axis', '')} | {idea.get('title', '')} | {sc.get('novelty')} | "
                     f"{sc.get('feasibility')} | {sc.get('safety_impact')} | {sc.get('replicability')} | "
                     f"{sc.get('duplication_risk')} | {codes} |")
    lines += ["", "## Ranking", ""]
    for t in ranked.get("top", []):
        lines.append(f"{t['rank']}. {by_id.get(t['idea_id'], {}).get('title', t['idea_id'])} ({t['idea_id']}): {t.get('rationale', '')}")
    for s in ranked.get("scored", []):
        if s.get("distinctness") or s.get("rationale"):
            lines.append(f"- {s['idea_id']}: {s.get('rationale', '')} Distinctness: {s.get('distinctness', '')}")
    if ranked.get("judge_notes"):
        lines += ["", "## Judge notes", "", ranked["judge_notes"]]
    return "\n".join(lines) + "\n"


def write_proposals(kb: KB, campaign: Dict[str, Any], planner_run: str, artifacts: Path,
                    *, max_jobs: Optional[int] = None) -> Dict[str, Any]:
    """Write the idea files, proposal YAMLs and planning log for the top ideas; returns what was written."""
    artifacts = Path(artifacts)
    problem = json.loads((artifacts / "problem.json").read_text(encoding="utf-8"))
    ideas = json.loads((artifacts / "ideas.json").read_text(encoding="utf-8"))
    ranked = json.loads((artifacts / "ideas_ranked.json").read_text(encoding="utf-8"))
    by_id = {i["id"]: i for i in ideas["ideas"]}
    scored = {s["idea_id"]: s for s in ranked["scored"]}
    models = kb.models()
    limit = int(max_jobs if max_jobs is not None else (campaign.get("planner") or {}).get("max_new_jobs_per_run", 3))
    proposal_dir = kb.queue_dir / "proposals" / planner_run
    proposal_dir.mkdir(parents=True, exist_ok=True)
    kb.ideas_dir.mkdir(parents=True, exist_ok=True)
    written: List[Dict[str, Any]] = []
    for n, top in enumerate(sorted(ranked["top"], key=lambda t: t["rank"]), start=1):
        if n > limit:
            break
        idea = by_id[top["idea_id"]]
        slug = slugify(idea["title"], 40)
        idea_path = kb.ideas_dir / f"{planner_run}-{slug}.yaml"
        save_yaml(idea_path, to_idea_yaml(idea, problem=problem, planner_run=planner_run, campaign_name=campaign.get("name", ""),
                                          scored=scored.get(top["idea_id"]), rank=top["rank"]))
        try:
            idea_file = str(idea_path.relative_to(PROJECT_ROOT))
        except ValueError:
            idea_file = str(idea_path)
        spec = to_job_spec(idea, idea_file=idea_file, rank=top["rank"], scored=scored.get(top["idea_id"], {}), top=top,
                           campaign=campaign, models=models, problem=problem)
        spec_path = proposal_dir / f"{n}-{slug}.yaml"
        save_yaml(spec_path, spec)
        written.append({"n": n, "idea_id": top["idea_id"], "kind": spec["kind"], "priority": spec["priority"],
                        "title": idea["title"], "idea_file": idea_file, "proposal": str(spec_path)})
    (proposal_dir / "planning_log.md").write_text(planning_log(problem, ideas, ranked, written, planner_run=planner_run),
                                                  encoding="utf-8")
    return {"proposal_dir": str(proposal_dir), "written": written, "problem": problem.get("title"),
            "candidates": len(ideas["ideas"]), "top": len(ranked["top"])}
