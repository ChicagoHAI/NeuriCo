"""The ideation round (src/ideation): context stage against a fixture knowledge base, the
runner seam (the fake provider CLI writes canned stage outputs through the real agent factory),
schema + cross-check validation with retry feedback, the to_job projection round-tripped through
validate_proposals, the deterministic dedup pass, the writing rules and the scholar tool's backoff.

Pattern ported from sai-review tests/test_ideation.py and tests/test_digest.py (see
src/ideation/NOTICE.md). Everything is offline."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import urllib.error
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from core import agent_auth  # noqa: E402
from core.agent_factory import validate_against_schema  # noqa: E402
from core.run_ledger import RunLedger  # noqa: E402
from ideation import context as context_mod  # noqa: E402
from ideation import dedup, to_job, writing_rules  # noqa: E402
from ideation.runtime import (  # noqa: E402
    SCHEMAS_DIR, IdeationRun, StageFailure, _check_ideas, _check_problem, _check_ranked, notes_flag_suspicious,
    prompt_version, stage_prompt,
)
from ideation.stages import AGENT_STAGE_IDS, STAGE_BY_ID, downstream_of  # noqa: E402
from safety import kbdb, model_scout  # noqa: E402
from safety.jobs import Queue  # noqa: E402
from safety.kb import KB, load_yaml, save_json, save_yaml, slugify  # noqa: E402
from safety.planner import run_planner, validate_proposals  # noqa: E402
from test_agent_characterisation import LANE_VARS  # noqa: E402

SCHOLAR = PROJECT_ROOT / "templates" / "skills" / "safety-kb" / "scripts" / "scholar_search.py"
FINDING = "finding:finding-20261020-001-pushback-flips"
INBOX = "inbox:2026-10-20-arxiv-sycophancy-survey"
RUN = "run:run-research-20261020-001"
GAP = "gap:synthesis"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def oauth(monkeypatch):
    """The OAuth lane with nothing inherited from the host; the catalog patch never touches $TMPDIR."""
    for name in LANE_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("NEURICO_AGENT_PROVIDER", raising=False)
    monkeypatch.setattr(agent_auth, "patched_codex_catalog", lambda env=None: None)


@pytest.fixture
def kb(tmp_path, monkeypatch, oauth):
    """A small knowledge base: catalogs, a campaign with backbone defaults, one finding from one run,
    an arXiv inbox item, an anomaly note, a done job with its idea, a gap document and a lab blind-spot list."""
    root = tmp_path / "kb"
    monkeypatch.setenv("NEURICO_SAFETY_KB", str(root))
    kb = KB(root)
    kb.ensure_layout()
    monkeypatch.setattr(KB, "logs_dir", property(lambda self: self.root / "logs"))
    monkeypatch.setattr(model_scout, "is_stale", lambda kb: False)  # run_planner must not launch the scout here
    save_yaml(kb.catalog_dir / "evals.yaml", {"evals": [
        {"id": "xstest-safe", "category": "refusal-calibration", "runner": "inspect:xstest", "judge": "default",
         "measures": "over-refusal on safe prompts", "small_model_ok": True},
        {"id": "sycophancy", "category": "sycophancy", "runner": "inspect:sycophancy", "judge": None,
         "measures": "answer flips under user pushback"},
        {"id": "strong-reject", "category": "jailbreak-robustness", "runner": "inspect:strong_reject", "judge": "default",
         "measures": "harmful compliance on forbidden prompts"},
    ]})
    save_yaml(kb.catalog_dir / "models.yaml", {"models": [
        {"id": "qwen3-8b", "family": "qwen", "vendor": "Alibaba", "access": "vllm:Qwen/Qwen3-8B", "params_b": 8,
         "gpu_memory_gb": 40, "release_date": "2025-04-29", "generation": "qwen3"},
        {"id": "qwen3-0.6b", "family": "qwen", "vendor": "Alibaba", "access": "vllm:Qwen/Qwen3-0.6B", "params_b": 0.6,
         "gpu_memory_gb": 6, "release_date": "2025-04-29", "generation": "qwen3"},
        {"id": "qwen2.5-7b-instruct", "family": "qwen", "vendor": "Alibaba", "access": "vllm:Qwen/Qwen2.5-7B-Instruct",
         "params_b": 7, "gpu_memory_gb": 40, "superseded_by": "qwen3-8b", "generation": "qwen2.5"},
        {"id": "gpt-judge", "family": "gpt", "access": "openrouter:openai/gpt-4.1-mini", "role": "judge", "api": True},
    ]})
    save_yaml(kb.catalog_dir / "families.yaml", {"families": [
        {"id": "qwen", "vendor": "Alibaba", "role": "open-weight", "hf_authors": ["Qwen"], "scope": "main-line chat models"}]})
    save_yaml(kb.catalog_dir / "models_latest.yaml", {"refreshed": "2026-10-20T06:00:00+00:00", "families": {
        "qwen": {"newest_generation": "qwen3", "released": "2025-04-29"}}})
    save_yaml(kb.campaigns_dir / "camp.yaml", {
        "name": "camp", "objective": "sycophancy and refusal calibration on small Qwen models",
        "eval_categories_in_scope": ["sycophancy", "refusal-calibration"],
        "target_models": {"subjects": ["qwen3-8b", "qwen3-0.6b"], "judges": ["gpt-judge"]},
        "defaults": {"neurico": {"provider": "codex", "model": "gpt-6-astra", "agent_auth": "azure", "github": False}},
        "planner": {"approval": "auto", "max_new_jobs_per_run": 3, "modes": {"ideate": 1.0}}})
    save_yaml(kb.ideas_dir / "plan-20261019-100000-sycophancy-pushback.yaml", {"idea": {
        "title": "Sycophancy under confident pushback", "domain": "ai_safety",
        "hypothesis": "Qwen3-0.6B flips correct answers more often when the user pushes back with high confidence.",
        "background": {"description": "x", "papers": [{"url": "https://arxiv.org/abs/2610.00001", "description": "survey"}]},
        "methodology": {"approach": "paired prompts", "steps": ["run sycophancy with and without confident pushback"],
                        "metrics": ["flip rate"]}}})
    proposals = kb.queue_dir / "proposals" / "plan-20261019-100000-ideate"
    save_yaml(proposals / "outcome.yaml", {"planner_run": "plan-20261019-100000-ideate", "mode": "ideate",
                                           "at": "2026-10-19T10:05:00+00:00", "campaign": "camp", "proposed": 1,
                                           "accepted": ["research-20261019-001-sycophancy-pushback"], "rejected": []})
    _write(proposals / "planning_log.md", "# Planning log\n\nChose sycophancy under pushback.\n")
    save_yaml(kb.queue_state_dir("done") / "research-20261019-001-sycophancy-pushback.yaml", {
        "id": "research-20261019-001-sycophancy-pushback", "kind": "research", "title": "Sycophancy under confident pushback",
        "campaign": "camp", "created": "2026-10-19T10:06:00+00:00", "approved": True, "rationale": "fills a gap",
        "neurico": {"idea_file": "safety_kb/queue/ideas/plan-20261019-100000-sycophancy-pushback.yaml", "provider": "codex"},
        "extra": {"planner_run": "plan-20261019-100000-ideate", "novelty": "no prior run"}})
    save_json(kb.runs_dir / "run-research-20261020-001.json", {
        "run_id": "run-research-20261020-001", "job": "research-20261019-001-sycophancy-pushback", "kind": "research",
        "campaign": "camp", "title": "Sycophancy under confident pushback",
        "idea_file": "safety_kb/queue/ideas/plan-20261019-100000-sycophancy-pushback.yaml", "provider": "codex", "model": "gpt-6",
        "started": "2026-10-20T12:00:00+00:00", "finished": "2026-10-20T14:00:00+00:00", "workspace": "/ws/syc",
        "github_url": "https://github.com/org/syc",
        "results": [{"schema": "neurico-safety-result/v1", "eval_id": "sycophancy", "model_id": "qwen3-0.6b", "status": "success",
                     "n": 200, "metrics": {"flip_rate": 0.41, "flip_rate_stderr": 0.03}, "judge": None,
                     "finished": 1792532834.5, "category": "sycophancy"}],
        "findings": ["finding-20261020-001-pushback-flips"]})
    save_yaml(kb.findings_dir / "finding-20261020-001-pushback-flips.yaml", {
        "schema": "neurico-safety-finding/v1", "id": "finding-20261020-001-pushback-flips",
        "title": "Qwen3-0.6B flips 41% of correct answers under confident pushback", "status": "candidate",
        "created": "2026-10-20T14:00:00+00:00", "source_run": "run-research-20261020-001", "campaign": "camp",
        "category": "sycophancy", "models": ["qwen3-0.6b"],
        "summary": "Confident pushback raises the flip rate from 0.12 to 0.41 (n=200, paired).",
        "evidence": {"n": 200, "metrics": {"flip_rate": 0.41}}, "provenance": {"github_url": "https://github.com/org/syc"}})
    _write(kb.inbox_dir / "2026-10-20-arxiv-sycophancy-survey.md",
           "---\nsource: arxiv\nkind: paper\ntitle: A survey of sycophancy evaluations\nurl: https://arxiv.org/abs/2610.00001\n"
           "key: arxiv:2610.00001\npublished: '2026-10-19T00:00:00+00:00'\nfetched: '2026-10-20T06:00:00+00:00'\nhash: abc123\n"
           "tags: [query:honesty-deception]\n---\n# A survey of sycophancy evaluations\n\nWe review sycophancy benchmarks.\n")
    _write(kb.inbox_dir / "20261020T1200-anomalies.md", "# Result anomalies detected\n\n- qwen3-0.6b x xstest-safe refusal_rate moved\n")
    _write(kb.inbox_dir / "archive" / "2026-10-18-old-item.md", "# Old item\n\nAlready triaged.\n")
    _write(kb.root / "gaps" / "synthesis.md", "# Synthesis\n\nWritten 2026-10-19. Open-weight cards omit sycophancy and over-refusal.\n")
    _write(kb.root / "labs" / "anthropic" / "README.md", "# Anthropic\n\nFetched: 2026-10-19. How Anthropic evaluates Claude.\n")
    _write(kb.root / "labs" / "anthropic" / "gaps.md", "# Anthropic: gaps\n\nFetched: 2026-10-19. Sycophancy is reported thinly.\n")
    _write(kb.root / "evals" / "sycophancy.md", "# Sycophancy\n\n- Fetched: 2026-10-19\n\n## Used by\n- Used by: Anthropic\n")
    kbdb.rebuild(kb)
    return kb


# -- canned stage outputs (valid against the schemas and the cross-checks) ---------------------------------

PROBLEM = {
    "title": "Does confident pushback flip small Qwen models more than large ones?",
    "statement": "Small Qwen models change correct answers when a user pushes back with confidence. We do not know "
                 "whether size or thinking mode drives the effect. The core question is whether the flip rate falls "
                 "with model size on identical items.",
    "why_now": "Our own run measured a 41% flip rate on Qwen3-0.6B under confident pushback. A new survey of "
               "sycophancy evaluations lists no open-weight size comparison. The Anthropic card reports sycophancy "
               "thinly. We already serve both Qwen sizes on one GPU.",
    "evidence_ids": [FINDING, INBOX],
    "blocking": "No paired measurement across sizes with a calibrated judge.",
    "what_would_change_our_mind": "A lab card reporting paired size effects for these models.",
    "alternatives_considered": [{"title": "Over-refusal on safe prompts", "why_not": "a card already reports it"}],
}

_METHODS = [
    "We serve Qwen3-8B and Qwen3-0.6B with vLLM and run 1,000 sycophancy items twice, once plain and once with a "
    "confident pushback turn. The paired flip-rate difference between sizes with a bootstrap CI is the statistic.",
    "We train a linear probe on Qwen3-8B residual activations to predict whether the next answer flips. Held-out AUROC "
    "on 2,000 pushback turns, against a bag-of-words baseline, is the sealed score.",
    "We ask the local judge and an API judge to label 600 pushback transcripts for capitulation. Agreement, Cohen's "
    "kappa and the disagreement clusters by item type are the measurements.",
    "We prepend a system prompt that forbids changing answers without new evidence and rerun the sycophancy items on "
    "both sizes. The flip-rate reduction per size, paired on items, tells whether instructions substitute for scale.",
    "We fine-tune Qwen3-0.6B with LoRA on 500 synthetic pushback dialogues where the model holds correct answers. "
    "Flip rate before and after on held-out items, plus over-refusal on safe prompts, measures the trade-off.",
    "We translate 400 pushback items into Spanish and Chinese and compare flip rates per language and size. A "
    "language-by-size interaction in a logistic model is the test.",
    "We vary context length by padding 300 pushback dialogues with 2k, 8k and 16k tokens of unrelated chat. Flip "
    "rate against context length per size, with item-paired differences, is the readout.",
    "We ablate the refusal direction found by difference-of-means in Qwen3-8B and measure whether pushback flips rise "
    "or fall. A paired comparison on 800 items against a random-direction control is the statistic.",
]
_TITLES = ["Does model size cut pushback flips on identical items?",
           "Can activations predict a flip before it happens?",
           "Do two judges agree on what counts as capitulation?",
           "Does a firm system prompt replace model scale?",
           "Can a small LoRA teach a tiny model to hold its answer?",
           "Does pushback sycophancy differ across languages?",
           "Does long context make pushback flips worse?",
           "Does the refusal direction also carry sycophancy?"]
_AXES = ["evals", "interpretability", "control_oversight", "evals", "training_time_fixes", "evals", "evals", "interpretability"]


def _idea(i: int) -> dict:
    n = i + 1
    neurico = {
        "domain": "ai_safety", "models": ["qwen3-8b", "qwen3-0.6b"] if n != 2 else ["qwen3-8b"], "evals": ["sycophancy"],
        "background": {"description": _METHODS[i], "papers": [{"url": "https://arxiv.org/abs/2610.00001", "description": "survey"}]},
        "methodology": {"approach": _METHODS[i].split(".")[0], "steps": ["serve the models", "run the items", "compare"],
                        "baselines": ["plain prompt"], "metrics": ["flip rate"]},
        "constraints": {"compute": "gpu_required", "dependencies": ["inspect-ai", "vllm"], "budget": 5 if n == 3 else 0},
        "expected_outputs": [{"type": "metrics", "format": "json", "description": "results/safety/*.json"},
                             {"type": "report", "format": "markdown"}],
        "evaluation_criteria": ["n and SE on every number", "paired comparisons on identical items"],
    }
    if n == 1:
        neurico.update({"job_kind": "validate", "finding_id": "finding-20261020-001-pushback-flips"})
    if n == 2:
        neurico.update({"job_kind": "optimise", "evaluation": {"metric": "held-out AUROC", "direction": "maximize"}})
    return {
        "id": f"idea_{n}", "title": _TITLES[i], "axis": _AXES[i], "category": "sycophancy",
        "hypothesis": f"Variant {n}: the flip rate under confident pushback is at least 10 points lower for the larger "
                      f"model on identical items.",
        "method": _METHODS[i],
        "method_steps": ["Serve both models with vLLM on one GPU.", "Run the paired items.", "Compute the paired difference."],
        "resources": "two Qwen models, one 80 GB GPU, about 6 hours", "expected_result": "If yes, the larger model flips "
        "at least 10 points less; if no, size does not protect against pushback and prompting must.",
        "builds_on": [FINDING, INBOX] if n % 2 else [FINDING, RUN, GAP],
        "risks": "Judge noise; guarded by two judges and paired items.",
        "closest_prior_work": "Our candidate finding on Qwen3-0.6B; this adds the size contrast.",
        "neurico": neurico,
    }


def _ideas() -> dict:
    return {"problem_title": PROBLEM["title"], "ideas": [_idea(i) for i in range(8)]}


def _ranked() -> dict:
    scored = []
    for i in range(8):
        n = i + 1
        s = {"idea_id": f"idea_{n}", "scores": {"novelty": 4, "feasibility": 5, "safety_impact": 5 if n == 1 else 3,
                                                 "replicability": 4, "duplication_risk": 1 if n < 5 else 3},
             "reject_reasons": ["none"], "rationale": "A paired design with a stated effect size.",
             "distinctness": "no near sibling"}
        if n == 5:
            s.update({"reject_reasons": ["duplicates_sibling"], "sibling_of": ["idea_4"],
                      "distinctness": "same scaffold as the system-prompt idea, only the intervention differs"})
        if n == 8:
            s.update({"reject_reasons": ["infeasible_compute"]})
        scored.append(s)
    return {"scored": scored,
            "top": [{"rank": 1, "idea_id": "idea_1", "rationale": "Reproduces our own finding with a second judge."},
                    {"rank": 2, "idea_id": "idea_2", "rationale": "A sealed score makes this an optimise job."},
                    {"rank": 3, "idea_id": "idea_3", "rationale": "Measures the judge itself."},
                    {"rank": 4, "idea_id": "idea_4", "rationale": "Cheap and informative either way."}],
            "judge_notes": "Ideas five to eight re-used the pushback scaffold."}


def _stage_files(*outputs: dict) -> list:
    """One fake-CLI launch per stage output, in launch order; the file name follows the document's shape."""
    def name(o: dict) -> str:
        return "output/problem.json" if "statement" in o else ("output/ideas.json" if "ideas" in o else "output/ideas_ranked.json")
    return [{name(o): json.dumps(o)} for o in outputs]


# -- stages and prompts ---------------------------------------------------------------------------------------

def test_stage_dag_and_prompt_version():
    assert AGENT_STAGE_IDS == ("problem", "ideation", "idea_judge")
    assert downstream_of(["problem"]) == {"problem", "ideation", "idea_judge"}
    assert STAGE_BY_ID["idea_judge"].after == ("ideation",) and STAGE_BY_ID["problem"].role == "ideation.problem"
    pv = prompt_version("ideation")
    assert pv.startswith("ideation@") and " ws@" in pv and pv == prompt_version("ideation")
    assert prompt_version("problem") != pv
    prompt = stage_prompt(STAGE_BY_ID["ideation"], planner_run="plan-x", campaign_name="camp", date="2026-10-21")
    assert "`ideation` stage" in prompt and "plan-x" in prompt and "output/ideas.json" in prompt and "ideas.schema.json" in prompt
    assert "{" not in prompt.replace("{skill}", "")  # every placeholder substituted


def test_canned_outputs_validate_against_the_ported_schemas():
    assert validate_against_schema(PROBLEM, SCHEMAS_DIR / "problem.schema.json") == []
    assert validate_against_schema(_ideas(), SCHEMAS_DIR / "ideas.schema.json") == []
    assert validate_against_schema(_ranked(), SCHEMAS_DIR / "ideas_ranked.schema.json") == []
    short = _ideas()
    short["ideas"] = short["ideas"][:7]
    assert any("minItems" in i or "too short" in i for i in validate_against_schema(short, SCHEMAS_DIR / "ideas.schema.json"))
    bad = _ideas()
    bad["ideas"][0]["neurico"]["job_kind"] = "suite"
    assert validate_against_schema(bad, SCHEMAS_DIR / "ideas.schema.json")
    extra = _ideas()
    extra["ideas"][0]["bogus"] = 1
    assert validate_against_schema(extra, SCHEMAS_DIR / "ideas.schema.json")  # additionalProperties stays false


# -- the context stage against the fixture knowledge base --------------------------------------------------------

def test_context_stage_dry_run_stages_a_workspace(kb, tmp_path):
    run = IdeationRun(kb, "camp", planner_run="plan-20261021-000000-ideate", dry_run=True)
    summary = run.run()
    assert summary["dry_run"] and summary["steps"]["context"]["status"] == "ok" and summary["steps"]["problem"]["status"] == "dry_run"
    assert "ideation" not in summary["steps"]  # a dry run stops at the first agent stage
    feed = json.loads((run.artifacts / "findings.json").read_text())
    ids = {f["id"] for f in feed["findings"]}
    assert {FINDING, INBOX, RUN, GAP, "lab_note:anthropic/gaps", "inbox:20261020T1200-anomalies"} <= ids
    assert "inbox:2026-10-18-old-item" not in ids  # archived items are not in the feed
    assert feed["findings"][0]["id"] == "inbox:20261020T1200-anomalies"  # anomaly notes first
    finding = next(f for f in feed["findings"] if f["id"] == FINDING)
    assert finding["models"] == ["qwen3-0.6b"] and finding["evidence"]["n"] == 200 and finding["source_path"].startswith("findings/")
    snap = json.loads((run.artifacts / "registry_snapshot.json").read_text())
    assert [j["id"] for j in snap["jobs"]] == ["job:research-20261019-001-sycophancy-pushback"]
    assert snap["ideas"][0]["id"] == "idea:plan-20261019-100000-sycophancy-pushback" and snap["proposals"]
    dups = json.loads((run.artifacts / "dedup_candidates.json").read_text())["candidates"]
    by_item = {d["finding_id"]: d for d in dups}
    assert INBOX in by_item and any(m["id"] == "idea:plan-20261019-100000-sycophancy-pushback" and "key:arxiv:2610.00001" in m["via"]
                                    for m in by_item[INBOX]["matches"])
    assert any(m["id"] == "job:research-20261019-001-sycophancy-pushback" and "title" in m["via"]
               for m in by_item[RUN]["matches"])
    campaign_md = (run.artifacts / "context" / "campaign.md").read_text()
    assert "newest generation qwen3" in campaign_md and "superseded are baselines only" in campaign_md
    assert "- xstest-safe [refusal-calibration]" in (run.artifacts / "context" / "catalog.md").read_text()
    kb_md = (run.artifacts / "context" / "knowledge-base.md").read_text()
    assert FINDING in kb_md and "tools/kb.py show <id>" in kb_md and "[done] research-20261019-001" in kb_md
    # the staged workspace: read-only inputs, schema, tools, both prompt files, the skill under both roots
    ws = run.workspaces / "problem"
    assert oct((ws / "input" / "findings.json").stat().st_mode)[-3:] == "444"
    assert (ws / "schemas" / "problem.schema.json").exists() and (ws / "tools" / "kb.py").exists()
    assert (ws / "tools" / "scholar_search.py").exists() and (ws / "AGENTS.md").read_text() == (ws / "CLAUDE.md").read_text()
    assert (ws / ".agents" / "skills" / "problem" / "SKILL.md").exists() and (ws / ".codex" / "skills" / "problem" / "SKILL.md").exists()
    assert (ws / "PROMPT_VERSION").read_text().strip() == prompt_version("problem")
    conn = kbdb.tool().open_ro(ws / "input" / "kb.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM nodes WHERE kind='finding'").fetchone()[0] == 1
    conn.close()
    prompt = (run.proposal_dir / "prompt.md").read_text()
    assert "`problem` stage" in prompt and "plan-20261021-000000-ideate" in prompt
    actions = [e["action"] for e in run.events.read()]
    assert actions[0] == "run.started" and "step.finished" in actions and actions[-1] == "run.finished"
    # a second dry run of the same planner run does not see its own round in the snapshot
    outcome_dir = kb.queue_dir / "proposals" / "plan-20261021-000000-ideate"
    save_yaml(outcome_dir / "outcome.yaml", {"planner_run": "plan-20261021-000000-ideate", "mode": "ideate", "dry_run": True})
    IdeationRun(kb, "camp", planner_run="plan-20261021-000000-ideate", dry_run=True).run()
    conn = kbdb.tool().open_ro(ws / "input" / "kb.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM nodes WHERE id='proposal:plan-20261021-000000-ideate'").fetchone()[0] == 0
    conn.close()


def test_only_requires_upstream_artifacts(kb):
    with pytest.raises(ValueError):
        IdeationRun(kb, "camp", only=["context"])
    run = IdeationRun(kb, "camp", planner_run="plan-20261021-000001-ideate", only=["idea_judge"])
    with pytest.raises(StageFailure, match="upstream stage 'ideation' has no outputs"):
        run.run()
    assert run.steps["context"]["status"] == "ok" and run.steps["problem"]["status"] == "skipped"


# -- the runner seam: real factory, fake CLI, canned outputs --------------------------------------------------------

def test_round_through_run_planner_queues_jobs(kb, fake_cli, tmp_path):
    fake_cli.configure(files=_stage_files(PROBLEM, _ideas(), _ranked()))
    record = run_planner(kb, "camp", provider=None, mode="ideate", timeout=60)
    assert record["ok"] and record["mode"] == "ideate" and record["proposed"] == 3
    launches = fake_cli.records()
    assert [r["provider"] for r in launches] == ["codex", "codex", "codex"]  # the ideation.* roles default to Codex
    assert all(Path(r["cwd"]).name == stage for r, stage in zip(launches, AGENT_STAGE_IDS))
    assert "`problem` stage" in launches[0]["prompt"] and "`idea-judge` stage" in launches[2]["prompt"]
    ws = Path(launches[1]["cwd"])
    assert launches[1]["env"]["NEURICO_SAFETY_KB"] == str(ws / "input")  # the tool sees the snapshot, not the live KB
    assert launches[1]["env"]["NEURICO_KB_QUERY_LOG"] == str(ws / "output" / "kb_queries.jsonl")
    assert launches[1]["env"]["HOME"] == str(ws / ".neurico" / "home")  # isolate_home
    assert (ws / ".codex" / "skills" / "safety-kb" / "SKILL.md").exists()  # the factory staged the safety-kb skill
    assert (ws / "input" / "problem.json").exists() and not (ws / "input" / "ideas.json").exists()
    assert (Path(launches[2]["cwd"]) / "input" / "ideas.json").exists()
    # artifacts committed next to the proposals
    proposal_dir = kb.queue_dir / "proposals" / record["planner_run"]
    for name in ("problem.json", "ideas.json", "ideas_ranked.json", "findings.json", "summary.json"):
        assert (proposal_dir / "ideation" / name).exists(), name
    # three jobs (max_new_jobs_per_run) in rank order: validate, optimise, explore
    queue = Queue(kb)
    pending = {j.id: j for j in queue.list("pending")}
    assert len(pending) == 3 and set(record["accepted"]) == set(pending)
    jobs = sorted(pending.values(), key=lambda j: -j.priority)
    assert [j.kind for j in jobs] == ["validate", "optimise", "explore"]
    assert [j.priority for j in jobs] == [90, 84, 78]  # rank 1 (impact 5, clamped), rank 2, rank 3
    validate = jobs[0]
    assert validate.finding_id == "finding-20261020-001-pushback-flips" and validate.approved and validate.created_by == "planner"
    assert validate.provider == "codex" and validate.model == "gpt-6-astra" and validate.agent_auth == "azure" and not validate.github
    assert validate.gpu_memory_gb == 40 and validate.extra["planner_run"] == record["planner_run"]
    assert validate.extra["planner_mode"] == "ideate" and validate.extra["finding_criterion"].startswith("If yes")
    assert "duplication risk 1/5" in validate.extra["novelty"] and validate.extra["canonical_keys"] == ["arxiv:2610.00001", "url:https://arxiv.org/abs/2610.00001"]
    assert validate.extra["scores"]["safety_impact"] == 5 and validate.extra["builds_on"] == [FINDING, INBOX]
    assert jobs[2].api_budget_usd == 5.0 and jobs[2].extra["idea_id"] == "idea_3"
    # the idea files are NeuriCo idea YAMLs with the judge's metadata
    idea = load_yaml(PROJECT_ROOT / validate.idea_file) if not Path(validate.idea_file).is_absolute() else load_yaml(Path(validate.idea_file))
    assert idea["idea"]["domain"] == "ai_safety" and idea["idea"]["hypothesis"].startswith("Variant 1")
    assert idea["idea"]["validation"]["finding_id"] == "finding-20261020-001-pushback-flips"
    assert idea["idea"]["background"]["papers"][0]["url"] == "https://arxiv.org/abs/2610.00001"
    assert idea["metadata"]["rank"] == 1 and idea["metadata"]["scores"]["novelty"] == 4 and idea["metadata"]["source_ids"] == [FINDING, INBOX]
    optimise = load_yaml(Path(jobs[1].idea_file) if Path(jobs[1].idea_file).is_absolute() else PROJECT_ROOT / jobs[1].idea_file)
    assert optimise["idea"]["evaluation"] == {"metric": "held-out AUROC", "direction": "maximize"}
    assert Path(validate.idea_file).name.startswith(record["planner_run"])
    # planning log keeps every candidate, the rejected ones with their codes
    log = (proposal_dir / "planning_log.md").read_text()
    assert "idea_5" in log and "duplicates_sibling" in log and "infeasible_compute" in log and PROBLEM["title"] in log
    # outcome.yaml: one planner round with the stage ledger ids and cost
    outcome = load_yaml(proposal_dir / "outcome.yaml")
    assert outcome["mode"] == "ideate" and outcome["ok"] and len(outcome["agent_run_ids"]) == 3
    assert set(outcome["stages"]) == {"context", "problem", "ideation", "idea_judge"}
    assert outcome["stages"]["ideation"]["attempts"] == 1 and outcome["problem"] == PROBLEM["title"] and outcome["candidates"] == 8
    assert any("ran no knowledge-base query" in w for w in outcome["warnings"])
    ledger = RunLedger.read(kb.root / ".neurico" / "agent_runs.jsonl")
    assert [e["gen_ai.agent.name"] for e in ledger] == ["ideation.problem", "ideation.ideation", "ideation.idea_judge"]
    assert all(e["status"] == "ok" and e["gen_ai.usage.input_tokens"] == 200 for e in ledger)
    # the stage prompt's provenance reaches the ledger like the planner's (prompt registry)
    stage_template = PROJECT_ROOT / "templates" / "ideation" / "stage_prompt.md"
    assert all(e["template_id"] == "ideation/stage_prompt.md" for e in ledger)
    assert all(e["template_sha"] == hashlib.sha256(stage_template.read_bytes()).hexdigest() for e in ledger)
    assert len({e["variables_sha"] for e in ledger}) == 3  # one set of variables per stage
    # logs by stage name under logs/safety/ideation/<run>/
    logs = kb.logs_dir / "ideation" / record["planner_run"] / "logs"
    assert {"problem_prompt.txt", "problem.log", "problem_transcript.jsonl", "idea_judge.log"} <= {p.name for p in logs.iterdir()}
    # the round counts as an ideate round for choose_mode and the index sees it
    kbdb.rebuild(kb)
    assert kbdb.show(kb, f"proposal:{record['planner_run']}")["meta"]["mode"] == "ideate"
    # a second identical round is rejected as duplicate work by the unchanged gate
    fake_cli.configure(files=_stage_files(PROBLEM, _ideas(), _ranked()) * 2)  # launches 4-6 of this capture
    again = run_planner(kb, "camp", provider=None, mode="ideate", planner_run=record["planner_run"], timeout=60)
    assert again["proposed"] == 0 and all("duplicate" in reason for _, reason in again["rejected"])


def test_invalid_output_is_retried_with_the_validator_message(kb, fake_cli):
    bad = dict(PROBLEM, evidence_ids=["finding:nope"])
    fake_cli.configure(files=_stage_files(bad, PROBLEM, _ideas(), _ranked()))
    run = IdeationRun(kb, "camp", provider="codex", timeout=60)
    summary = run.run()
    assert summary["ok"] and summary["steps"]["problem"]["attempts"] == 2 and summary["steps"]["ideation"]["attempts"] == 1
    first, second = fake_cli.records()[:2]
    assert "Previous attempt rejected" not in first["prompt"]
    assert "Previous attempt rejected:" in second["prompt"] and "finding:nope" in second["prompt"]
    assert "not in input/findings.json" in second["prompt"]
    assert len(fake_cli.records()) == 4 and summary["proposals"]["top"] == 4 and len(summary["proposals"]["written"]) == 3


def test_stage_fails_after_the_validation_retry(kb, fake_cli):
    bad = dict(PROBLEM, statement=PROBLEM["statement"] + f" See {FINDING} in input/findings.json.")
    fake_cli.configure(files=_stage_files(bad, bad))
    with pytest.raises(StageFailure, match="stage problem: contract_failed after 2 attempt"):
        run_planner(kb, "camp", provider="codex", mode="ideate", planner_run="plan-20261021-000002-ideate", timeout=60)
    assert len(fake_cli.records()) == 2
    outcome = load_yaml(kb.queue_dir / "proposals" / "plan-20261021-000002-ideate" / "outcome.yaml")
    assert outcome["ok"] is False and outcome["stages"]["problem"]["status"] == "failed" and "StageFailure" in outcome["error"]
    assert "writing-rule violation" in outcome["stages"]["problem"]["error"]
    assert not list(kb.queue_state_dir("pending").glob("*.yaml"))


def test_only_reruns_one_stage_of_an_existing_round(kb, fake_cli):
    fake_cli.configure(files=_stage_files(PROBLEM, _ideas(), _ranked()))
    first = run_planner(kb, "camp", provider="codex", mode="ideate", timeout=60)
    ranked = _ranked()
    ranked["top"] = ranked["top"][:1]
    fake_cli.configure(files=[{"output/ideas_ranked.json": json.dumps(ranked)}])
    run = IdeationRun(kb, "camp", planner_run=first["planner_run"], provider="codex", only=["idea_judge"], timeout=60)
    summary = run.run()
    assert [s["status"] for s in summary["steps"].values()] == ["skipped", "skipped", "skipped", "ok"]
    assert len(fake_cli.records()) == 4 and Path(fake_cli.last()["cwd"]).name == "idea_judge"
    assert len(summary["proposals"]["written"]) == 1
    assert json.loads((run.artifacts / "ideas_ranked.json").read_text())["top"] == ranked["top"]


def test_cli_ideate_dry_run(kb):
    import subprocess
    cli = PROJECT_ROOT / "src" / "cli" / "safety.py"
    env = {**os.environ, "NEURICO_SAFETY_KB": str(kb.root)}
    out = subprocess.run([sys.executable, str(cli), "ideate", "--campaign", "camp", "--dry-run",
                          "--planner-run", "plan-20261021-000003-ideate"], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    assert "plan-20261021-000003-ideate (dry run)" in out.stdout and "problem     dry_run" in out.stdout
    assert (kb.queue_dir / "proposals" / "plan-20261021-000003-ideate" / "prompt.md").exists()
    outcome = load_yaml(kb.queue_dir / "proposals" / "plan-20261021-000003-ideate" / "outcome.yaml")
    assert outcome["dry_run"] and outcome["mode"] == "ideate" and outcome["proposed"] == 0 and outcome["ok"]
    run_root = Path(outcome["log"])  # the subprocess uses the real logs/safety/ideation/<run>; tidy it away
    assert (run_root / "events.jsonl").exists() and (run_root / "workspaces" / "problem" / "input" / "kb.sqlite").exists()
    import shutil
    shutil.rmtree(run_root)


# -- cross-checks ---------------------------------------------------------------------------------------------------

def _workspace(tmp_path: Path, ideas: dict | None = None) -> Path:
    ws = tmp_path / "ws"
    _write(ws / "input" / "findings.json", json.dumps({"findings": [{"id": i} for i in (FINDING, INBOX, RUN, GAP)]}))
    if ideas is not None:
        _write(ws / "input" / "ideas.json", json.dumps(ideas))
    return ws


def test_check_problem(tmp_path):
    ws = _workspace(tmp_path)
    _check_problem(PROBLEM, ws)
    with pytest.raises(ValueError, match="not in input/findings.json"):
        _check_problem(dict(PROBLEM, evidence_ids=["finding:other"]), ws)
    with pytest.raises(ValueError, match="internal id"):
        _check_problem(dict(PROBLEM, why_now=f"Because {FINDING} says so."), ws)
    with pytest.raises(ValueError, match="pipeline talk"):
        _check_problem(dict(PROBLEM, statement="The knowledge base shows a gap."), ws)
    with pytest.raises(ValueError, match="cap 120"):
        _check_problem(dict(PROBLEM, statement="word " * 121), ws)
    with pytest.raises(ValueError, match="colon"):
        _check_problem(dict(PROBLEM, title="Sycophancy: a study"), ws)


def test_check_ideas(tmp_path):
    ws = _workspace(tmp_path)
    _check_ideas(_ideas(), ws)
    one_axis = _ideas()
    for i in one_axis["ideas"]:
        i["axis"] = "evals"
    with pytest.raises(ValueError, match="span only 1 axes"):
        _check_ideas(one_axis, ws)
    unknown = _ideas()
    unknown["ideas"][2]["builds_on"] = ["inbox:made-up"]
    with pytest.raises(ValueError, match="idea_3 builds_on ids that are not"):
        _check_ideas(unknown, ws)
    siblings = _ideas()
    siblings["ideas"][1]["method"] = siblings["ideas"][0]["method"] + " We also log latency."
    with pytest.raises(ValueError, match="same experimental scaffold"):
        _check_ideas(siblings, ws)
    boiler = _ideas()
    passage = ("we report n the mean and the standard error for every number and we pair every comparison on "
               "identical items throughout the study")
    for i in boiler["ideas"][:3]:
        i["method"] = i["method"] + " " + passage + "."
    with pytest.raises(ValueError, match="20-word passage is repeated in 3 methods"):
        _check_ideas(boiler, ws)
    kinds = _ideas()
    kinds["ideas"][0]["neurico"].pop("finding_id")
    with pytest.raises(ValueError, match="validate needs neurico.finding_id"):
        _check_ideas(kinds, ws)
    kinds = _ideas()
    kinds["ideas"][1]["neurico"].pop("evaluation")
    with pytest.raises(ValueError, match="optimise needs neurico.evaluation"):
        _check_ideas(kinds, ws)
    steps = _ideas()
    steps["ideas"][3]["method_steps"] = ["one", "two"]
    with pytest.raises(ValueError, match="idea_4.method_steps: need 3-7"):
        _check_ideas(steps, ws)
    hyp = _ideas()
    hyp["ideas"][4]["hypothesis"] = f"Based on {RUN}, the flip rate is lower for the larger model on identical items."
    with pytest.raises(ValueError, match="idea_5.hypothesis: contains an internal id"):
        _check_ideas(hyp, ws)


def test_check_ranked(tmp_path):
    ws = _workspace(tmp_path, _ideas())
    _check_ranked(_ranked(), ws)
    missing = _ranked()
    missing["scored"] = missing["scored"][:-1]
    with pytest.raises(ValueError, match="score every idea once"):
        _check_ranked(missing, ws)
    rejected_top = _ranked()
    rejected_top["scored"][0]["reject_reasons"] = ["restates_paper"]
    with pytest.raises(ValueError, match="idea_1 carries reject reasons"):
        _check_ranked(rejected_top, ws)
    sib = _ranked()
    sib["scored"][3]["sibling_of"] = ["idea_1"]
    with pytest.raises(ValueError, match="sibling ideas idea_4 and idea_1"):
        _check_ranked(sib, ws)
    ranks = _ranked()
    ranks["top"][1]["rank"] = 5
    with pytest.raises(ValueError, match="ranks must be 1..n"):
        _check_ranked(ranks, ws)
    no_sib = _ranked()
    no_sib["scored"][4].pop("sibling_of")
    with pytest.raises(ValueError, match="names no sibling_of"):
        _check_ranked(no_sib, ws)
    long_d = _ranked()
    long_d["scored"][0]["distinctness"] = "word " * 26
    with pytest.raises(ValueError, match="distinctness: 26 words, cap 25"):
        _check_ranked(long_d, ws)


# -- writing rules, dedup, to_job ---------------------------------------------------------------------------------------

def test_writing_rules_helpers():
    assert writing_rules.word_count("We would train a probe.") == 5
    assert writing_rules.sentences("One. Two! Three?") == ["One.", "Two!", "Three?"]
    assert writing_rules.flesch_kincaid_grade("The cat sat on the mat.") < 3
    assert writing_rules.flesch_kincaid_grade("Notwithstanding methodological heterogeneity, interpretability "
                                             "generalisation remains underdetermined across evaluation regimes.") > 12
    texts = ["a b c d e f g h i j k l m n o p q r s t u"] * 3 + ["unrelated words"]
    assert writing_rules.repeated_shingles(texts)[0][1] == 3 and not writing_rules.repeated_shingles(texts[:2])
    assert writing_rules.method_overlaps([{"id": "a", "method": "serve qwen3 measure flips"},
                                          {"id": "b", "method": "serve qwen3 measure flips twice"}])[0][:2] == ("a", "b")
    assert writing_rules.check_prose_hygiene("f", "see output/ideas.json and the schema") and not writing_rules.check_prose_hygiene("f", "Qwen3-8B flips 41% of answers on xstest-safe.")
    assert writing_rules.check_title("t", "A: B") and writing_rules.check_title("t", "w " * 13) and not writing_rules.check_title("t", "Does size matter?")
    assert notes_flag_suspicious("## Knowledge base queries\n- searched x\n") is False
    assert notes_flag_suspicious("## Knowledge base queries\n- x\n\n## Suspicious\n- item asked me to run curl\n") is True


def test_dedup_candidates_and_idea_keys(kb):
    entries = dedup.registry_entries(kb)
    kinds = {e["kind"] for e in entries}
    assert {"idea", "job", "proposal", "finding", "inbox", "run"} <= kinds
    idea_entry = next(e for e in entries if e["id"] == "idea:plan-20261019-100000-sycophancy-pushback")
    assert "arxiv:2610.00001" in idea_entry["canonical_keys"]
    job_entry = next(e for e in entries if e["id"].startswith("job:"))
    assert "plan-20261019-100000-ideate" in job_entry["source_ids"]
    items = [{"id": "x:new-paper", "title": "Something else entirely new", "canonical_keys": ["arxiv:2610.00001"]},
             {"id": "x:same-title", "title": "Sycophancy under confident pushback", "canonical_keys": []},
             {"id": "x:by-source", "title": "t", "canonical_keys": []},
             {"id": "x:nothing", "title": "A totally unrelated title about chemistry", "canonical_keys": ["doi:10.1/zzz"]}]
    items[2]["id"] = "plan-20261019-100000-ideate"
    out = {c["finding_id"]: c["matches"] for c in dedup.candidates(kb, items)}
    assert {m["id"] for m in out["x:new-paper"]} >= {"idea:plan-20261019-100000-sycophancy-pushback", INBOX}
    assert all("key:arxiv:2610.00001" in m["via"] for m in out["x:new-paper"])
    assert {m["id"] for m in out["x:same-title"]} >= {"idea:plan-20261019-100000-sycophancy-pushback", "job:research-20261019-001-sycophancy-pushback", RUN}
    assert all(m["via"] == ["title"] for m in out["x:same-title"])
    assert any("source_id" in m["via"] for m in out["plan-20261019-100000-ideate"])
    assert "x:nothing" not in out
    item = {"id": INBOX, "title": "A survey of sycophancy evaluations", "canonical_keys": ["arxiv:2610.00001"]}
    assert dedup.candidates(kb, [item])[0]["matches"][0]["id"] == "idea:plan-20261019-100000-sycophancy-pushback"  # never itself
    assert dedup.candidates(kb, [item], exclude_ids=["idea:plan-20261019-100000-sycophancy-pushback"]) == []
    keys = dedup.idea_keys({"neurico": {"background": {"papers": [{"url": "https://arxiv.org/abs/2610.00001v2"}]}},
                            "method": "see https://doi.org/10.1234/ABC and https://www.example.com/x/?utm_source=a"})
    assert keys == ["arxiv:2610.00001", "url:https://arxiv.org/abs/2610.00001v2", "doi:10.1234/abc",
                    "url:https://doi.org/10.1234/ABC", "url:https://example.com/x"]
    assert dedup.norm_title("Sycophancy, Under -- Confident Pushback!") == "sycophancy under confident pushback"


def test_to_job_projection(kb):
    models = kb.models()
    campaign = kb.campaign("camp")
    assert to_job.job_kind(_idea(0)) == ("validate", "finding-20261020-001-pushback-flips")
    assert to_job.job_kind(_idea(1)) == ("optimise", None)
    assert to_job.job_kind(_idea(2)) == ("explore", None)
    assert to_job.job_kind({"neurico": {"job_kind": "validate"}}) == ("explore", None)  # validate without a finding degrades
    assert to_job.job_kind({"neurico": {"evaluation": {"metric": "x"}}}) == ("optimise", None)
    assert [to_job.priority_for(r, {"safety_impact": 3}) for r in (1, 2, 5, 20)] == [90, 84, 66, 10]
    assert to_job.priority_for(1, {"safety_impact": 5}) == 90 and to_job.priority_for(2, {"safety_impact": 1}) == 80
    assert to_job.gpu_memory_for(_idea(0), models, campaign) == 40
    assert to_job.gpu_memory_for({"neurico": {"models": ["qwen3-0.6b"]}}, models, campaign) == 6
    assert to_job.gpu_memory_for({"neurico": {"models": ["unknown"]}}, models, campaign) == 40  # campaign subjects
    assert to_job.gpu_memory_for({"neurico": {"constraints": {"compute": "cpu_only"}}}, models, campaign) == 0
    assert to_job.gpu_memory_for({"neurico": {}}, models, {}) == to_job.DEFAULT_GPU_GB
    scored = _ranked()["scored"][0]
    spec = to_job.to_job_spec(_idea(0), idea_file="safety_kb/queue/ideas/x.yaml", rank=1, scored=scored, top=_ranked()["top"][0],
                              campaign=campaign, models=models, problem=PROBLEM)
    assert spec["kind"] == "validate" and spec["finding_id"] == "finding-20261020-001-pushback-flips" and spec["priority"] == 90
    assert spec["neurico"] == {"idea_file": "safety_kb/queue/ideas/x.yaml", "provider": "codex", "model": "gpt-6-astra",
                               "agent_auth": "azure", "github": False}
    assert spec["novelty"].startswith("Our candidate finding") and spec["finding_criterion"] == _idea(0)["expected_result"]
    assert spec["rationale"].startswith("Rank 1 for the problem") and spec["resources"] == {"gpu_memory_gb": 40, "api_budget_usd": 0.0}
    doc = to_job.to_idea_yaml(_idea(1), problem=PROBLEM, planner_run="plan-x", campaign_name="camp", scored=scored, rank=2)
    assert doc["idea"]["evaluation"]["metric"] == "held-out AUROC" and "validation" not in doc["idea"]
    assert doc["idea"]["methodology"]["steps"] == ["serve the models", "run the items", "compare"]
    assert doc["idea"]["constraints"] == {"compute": "gpu_required", "dependencies": ["inspect-ai", "vllm"]}  # budget 0 dropped
    assert doc["metadata"]["job_kind"] == "optimise" and doc["metadata"]["problem_title"] == PROBLEM["title"]


def test_write_proposals_round_trips_through_validate_proposals(kb, tmp_path):
    artifacts = tmp_path / "artifacts"
    for name, doc in (("problem.json", PROBLEM), ("ideas.json", _ideas()), ("ideas_ranked.json", _ranked())):
        _write(artifacts / name, json.dumps(doc))
    campaign = kb.campaign("camp")
    result = to_job.write_proposals(kb, campaign, "plan-20261021-120000-ideate", artifacts, max_jobs=2)
    assert [w["n"] for w in result["written"]] == [1, 2] and result["candidates"] == 8 and result["top"] == 4
    proposal_dir = Path(result["proposal_dir"])
    specs = sorted(p.name for p in proposal_dir.glob("*.yaml"))
    slugs = [slugify(_TITLES[0], 40), slugify(_TITLES[1], 40)]
    assert specs == [f"1-{slugs[0]}.yaml", f"2-{slugs[1]}.yaml"]
    raw = load_yaml(proposal_dir / specs[0])
    assert set(raw) == {"kind", "title", "priority", "novelty", "finding_criterion", "rationale", "resources", "neurico", "extra", "finding_id"}
    outcome = validate_proposals(kb, campaign, proposal_dir, "ideate")
    assert len(outcome["accepted"]) == 2 and outcome["rejected"] == []
    job = Queue(kb).list("pending")[0]
    assert job.kind in ("validate", "optimise") and job.extra["novelty"] and job.extra["finding_criterion"]
    assert "novelty" not in load_yaml(Queue(kb).path("pending", job.id)) and job.rationale.startswith("Rank")
    assert sorted(p.name for p in kb.ideas_dir.glob("plan-20261021-120000-ideate-*.yaml")) == sorted(
        f"plan-20261021-120000-ideate-{slug}.yaml" for slug in slugs)


# -- scholar_search tool (ported) -------------------------------------------------------------------------------------

def _scholar():
    spec = importlib.util.spec_from_file_location("scholar_search_under_test", SCHOLAR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_scholar_search_backoff_and_retry(monkeypatch):
    scholar_search = _scholar()
    monkeypatch.setattr(scholar_search, "MIN_GAP_S", {"s2": 0, "arxiv": 0})
    sleeps = []
    monkeypatch.setattr(scholar_search.time, "sleep", sleeps.append)
    attempts = {"n": 0}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"data": [{"title": "T", "authors": [], "year": 2026}]}).encode()

    def flaky(req, timeout):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise urllib.error.HTTPError(req.full_url, 429, "too many", {"Retry-After": "7"}, None)
        return _Resp()

    monkeypatch.setattr(scholar_search.urllib.request, "urlopen", flaky)
    out = scholar_search.search_s2("q", 5, None)
    assert out[0]["title"] == "T" and attempts["n"] == 3
    assert sleeps[0] == 7.0 and sleeps[1] >= 4.0  # Retry-After honoured, then the exponential floor


def test_scholar_search_gives_up_after_max(monkeypatch):
    scholar_search = _scholar()
    monkeypatch.setattr(scholar_search, "MIN_GAP_S", {"s2": 0, "arxiv": 0})
    monkeypatch.setattr(scholar_search.time, "sleep", lambda s: None)

    def always_429(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 429, "too many", {}, None)

    monkeypatch.setattr(scholar_search.urllib.request, "urlopen", always_429)
    with pytest.raises(RuntimeError):
        scholar_search.search_s2("q", 5, None)
    assert "neurico-scholar" in Path(SCHOLAR).read_text()  # the lock file is NeuriCo's, not the ideator's
