#!/usr/bin/env python3
"""Autonomous world_model.json reconstruction harness (fast/cheap edition).

The expensive part of an agentic reconstruction is the tool loop: the model
making dozens of Read/Glob/Grep calls, each re-reading the cached context. So the
harness now does the evidence gathering DETERMINISTICALLY in Python (scan the run
folder, read the key artifacts) and hands the content to the model inline. The
model does no tool calls — it just reasons over the bundle and emits the world
model. That collapses ~78 turns to ~1 and drops cache-read tokens ~40x.

It defaults to Sonnet (the reconstruction is structured extraction, not deep
reasoning) and prints the real cost from Claude Code's JSON envelope.

Usage:
  python reconstruct_world_model.py --run-dir /path/to/run        # one run
  python reconstruct_world_model.py --run-dir /path/to/run --dry-run
  python reconstruct_world_model.py --all /path/to/runs-root      # every run
  python reconstruct_world_model.py --run-dir /path/to/run --model opus   # override

Output (under <repo>/data/runs/<run-id>/):
  evidence_inventory.json   (built in Python)
  world_model.json          (only if it validates)
  world_model.invalid.json + validation_report.json   (on quarantine)
"""

import argparse
import collections
import concurrent.futures
import copy
import datetime
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from validate_world_model import (  # noqa: E402
    validate, is_blank,
    LINK_RELATIONS, LINK_BASIS, LINK_COMPATIBILITY, ENTITY_COLLECTIONS,
)

PROMPT_FILE = os.path.join(REPO, "prompts", "world-model-reconstruction-prompt.md")
FLOW_RULES_FILE = os.path.join(REPO, "prompts", "flow-chart-rules.md")
DECISION_RULES_FILE = os.path.join(REPO, "prompts", "decision-identification-rules.md")
PROMPT_VERSION = "world-model-reconstruction v3 findings-spine"
REVIEW_PROMPT_VERSION = "adversarial-review v1"
DEFAULT_MODEL = "sonnet"

# Artifacts whose CONTENT the model reasons over — the architecture's known files.
ARTIFACT_READ_LIST = [
    ".neurico/idea.yaml", ".neurico/pipeline_state.json", ".neurico/pipeline_results.json",
    "planning.md", "REPORT.md", "README.md", "resources.md", "literature_review.md",
    "results/config.json", "results/summary.json", "paper_draft/main.tex",
]
# Paper sections carry the prose a decision is justified in — read so the model can
# anchor decisions to the written paper (see paperRef in _TASK_DEC). They go FIRST:
# `results/*.json` matches the dozens of results/model_outputs/*.json (fnmatch '*'
# spans '/'), which otherwise floods TOTAL_CAP and starves these small, high-value
# section files.
ARTIFACT_GLOBS = ["paper_draft/sections/*.tex",
                  "results/analysis/*.csv", "results/analysis/*.json", "results/*.json"]
# Source code IS the ground truth for implementation/coding decisions (feature
# representation, classifier choice, significance tests, judge temperature/prompts,
# seeds, thresholds). fnmatch's "*" spans "/", so these also catch nested files
# under the named research dirs. NOTE: no bare "*.py" — it would slurp the agent
# skill scaffolding under .claude/.codex/.gemini (noise that also crowds out the
# real code); those dirs are skipped below regardless.
CODE_GLOBS = ["src/*.py", "code/*.py", "scripts/*.py",
              "src/*.R", "code/*.R", "src/*.sql", "code/*.sql"]
EXPECTED_ARTIFACTS = ["planning.md", "REPORT.md", "results/config.json", ".neurico/idea.yaml"]
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "papers", "datasets",
             ".claude", ".codex", ".gemini"}
PER_FILE_CAP = 18000   # chars per artifact
TOTAL_CAP = 180000     # chars for the whole bundle
CODE_TOTAL_CAP = 110000  # chars budget for source code (on top of TOTAL_CAP)
FILE_LIST_CAP = 40000  # chars for the "files present" listing — a run with cloned
                       # code repos can have 10k+ files; the model only needs a
                       # representative sample to ground evidence paths.
BUNDLE_CAP = 520000    # hard ceiling on the assembled bundle (~130k tokens) so no
                       # single oversized run can blow past the model context window
                       # (the original "Prompt is too long" failure mode).
REPAIR_PREVIOUS_CAP = 60000  # chars of the prior world_model shown to a repair
                             # call — must comfortably exceed a full model (~20-40k)
                             # so repair edits in place instead of regenerating short
TRANSCRIPT_GLOBS = ["logs/*transcript*.jsonl"]
TRANSCRIPT_DIGEST_CAP = 13000  # chars for the execution-trace digest. Generation
                               # time is driven by OUTPUT length (incident count),
                               # not this input, so the real speed lever is the
                               # fast-return flag precision below, not this cap.

HARNESS_INSTRUCTIONS = """\
You are running headless, with no human and NO TOOLS. Everything you need has been
extracted from the run folder and is in the EVIDENCE BUNDLE below. Do NOT attempt
to read files or call any tool — work only from the bundle.

RUN_ID: {run_id}

Produce TWO things and output them as EXACTLY ONE JSON object with these two keys,
and nothing else (no prose, no markdown fence):

  {{"world_model": <v3 world_model object — findings are the spine; every decision carries `finding` (an F-id or "global") and `layer`>, "flow": {{"elements": [...], "edges": [...]}}}}

1) world_model — follow the RECONSTRUCTION PROMPT below. (Do NOT output the evidence
   inventory; it's already built.) Never invent paths, numbers, or rationale; if an
   artifact you'd want isn't in the bundle, treat it as missing (a note finding).

2) flow — a human-readable process chart that follows the FLOW CHART RULES below:
   - 8–15 meaningful, project-SPECIFIC nodes with verb-first operation titles,
     NEVER raw log events or generic words. EVERY node title must come from THIS
     run's bundle (its idea, planning.md, REPORT.md, artifacts).
   - The flow chart rules contain ILLUSTRATIVE example node names from UNRELATED
     example projects — do NOT copy them. If a title mentions a model, dataset,
     metric, or domain that does not appear in THIS run's bundle, it is wrong.
   - elements: each {{ "id" (kebab-case), "clock" (integer t-order), "type" (an
     element-library type, e.g. intent|plan|literature_search|dataset_search|
     decision|method_design|implementation|experiment_matrix|model_run|analysis|
     evaluation|report_writing|validation|risk|result|branch), "title", "summary",
     "sourceRefs": [{{ "type": "artifact", "path": "<a real file from the bundle>",
     "note": "" }}] }}
   - edges: each {{ "from", "to", "type" }} with a typed edge: leads_to | depends_on
     | produced | used_by | branches_to | validates | failed_then | recovered_by |
     informs. Use branches_to for parallel tracks, alternatives, or factorial arms.
   - Do NOT provide x/y — layout is computed for you. Lay out by logic, not time.

===== FLOW CHART RULES =====
{flow_rules}

===== RECONSTRUCTION PROMPT =====
{prompt}
"""

REPAIR_INSTRUCTIONS = """\
Your world_model JSON failed deterministic validation. Return a MINIMAL PATCH that
fixes ONLY these problems — do NOT re-output the whole world model. Output ONE JSON
object containing only the fields/entities you are changing:

  - scalar fields to fix (e.g. "narrative", "current_best", "crux"): include them directly.
  - to fix specific entities, include ONLY those entities, each WITH its existing "id",
    under the right array key: "hypotheses", "findings", "decisions", "incidents",
    "experiments", or "assessments". Entities you omit are kept unchanged.
  - "cruxEvidence", "open_questions", or "panel_layout": include the full corrected
    array if it changed.

Do not invent file paths (every evidence.path must be a real file from the bundle's
file list). Output ONLY the JSON patch object — no prose, no markdown fence.

PROBLEMS:
{errors}

YOUR CURRENT world_model (fix against this — return ONLY the patch):
{previous}
"""

# --- Pass 2: PI review (paper-reading importance + the front-page go/no-go) ---

REVIEW_INSTRUCTIONS = """\
You are a research PI reviewing a FINISHED autonomous run as if grading a student's
project. The reconstructed WORLD MODEL below lists the run's findings and EVERY
decision behind them (the extractor was exhaustive, so most are routine method/coding
choices). The EVIDENCE BUNDLE contains the paper the run produced — its abstract and
sections — plus the REPORT. Read it the way a reviewer reads a paper: what are the
findings/insights, are they sound, and which decisions actually determine whether they
hold?

You are headless with NO TOOLS. Work only from the EVIDENCE BUNDLE and the WORLD MODEL.

RUN_ID: {run_id}

Output EXACTLY ONE JSON object and nothing else (no prose, no markdown fence):

  {{"runQuality": {{"verdict": "trustworthy|mixed|unconvincing",
                   "rationale": "2-3 sentences a reviewer would write: are the insights good, and what is the single load-bearing risk?"}},
    "decisions": [ <one entry for EACH decision you SELECT as critical/high/medium; omit the routine ones — they default to low> ]}}

== decisions — importance by SELECTION, not scoring ==
Do NOT rate decisions on an absolute scale — that collapses everything to "medium".
Instead work FINDING BY FINDING. For each finding (and for the abstract's headline
claims), identify the SMALL SET of decisions it is LOAD-BEARING on — in EITHER sense:
  (a) VALIDITY — a different reasonable choice would change whether the result HOLDS
      (design, measurement, controls, scope); OR
  (b) CLAIM / INTERPRETATION — a different reasonable choice would change WHAT the run
      claims or HOW it frames the result (definitive vs suggestive, which result is
      headlined, how the verdict is framed, whether something even counts as a finding).
A result can be valid yet rest on a load-bearing interpretation choice; weigh both senses.
Selecting is the judgment; the rest are routine.
List ONLY the decisions you SELECT as load-bearing — one entry each:
  critical — load-bearing (validity OR claim) for a HEADLINE finding or the abstract's main claim; a wrong call here breaks the paper's contribution
  high     — load-bearing (validity OR claim) for some finding, or for a secondary claim
  medium   — supports a finding but is NOT load-bearing (a different choice would dent it, not break it)
EVERY decision you do NOT list defaults to LOW (routine — most decisions ARE low; do NOT
emit entries for them). You will typically list 10-30 across the whole run.
Scan the WHOLE decision list before you finish — it is ordered by layer, so do not stop
after the first findings; consider forks across every layer, not only the foundational ones.
Each entry:
  {{"decisionId": "<a D-id from the WORLD MODEL>",
    "importance": "critical|high|medium",
    "importanceRationale": "one line: which finding/claim it is load-bearing on (validity or interpretation)" }}
Do NOT invent decision ids.

===== WORLD MODEL =====
{world_model}
"""

# --- Graph + sequence review: reconcile F/H/E edges and order each finding's decisions ---
# The fan-out passes build findings, hypotheses, experiments, and decisions independently
# and CONCURRENTLY, so cross-entity links are produced blind (positional id guesses) and a
# true link can simply be missed (no recall guarantee). This dedicated pass sees the FINAL,
# assembled node list with real ids and re-derives the COMPLETE graph authoritatively, and
# orders each finding's decisions into the causal chain that built it. Edges-only: it never
# rewrites node content.
GRAPH_SEQUENCE_INSTRUCTIONS = """\
You are reviewing a finished research run's reconstructed world model. Do TWO things,
working ONLY from the NODE LIST below — never invent ids, never add nodes:

1) Rebuild the GRAPH of relationships among findings (F), hypotheses (H), and
   experiments (E). Emit the COMPLETE, correct edge set (it REPLACES whatever exists).
   Allowed edges — ONLY these relations, ONLY these directions:
   - finding SUPPORTS / REFUTES the hypothesis its result bears on   (source=F, target=H)
   - finding PRODUCED_BY the experiment that generated its number     (source=F, target=E)
   - experiment MOTIVATED_BY the hypothesis it was run to test        (source=E, target=H)
   One edge per real relationship; OMIT any edge you cannot justify from the node text.
   basis="explicit" if a node states it, else "inferred".

2) Order each finding's DECISIONS into the causal chain a reader should follow — the
   order in which the reasoning actually built that finding (commonly what-to-test ->
   how-it-was-scoped -> how-it-was-built -> what-it-means, but follow the ACTUAL
   dependencies in the node text, not a fixed template). List every decision exactly
   once, grouped under its OWN `finding` value (an F-id, or "global").

RUN_ID: {run_id}

Output ONLY this JSON (no prose, no markdown fence):
{{"links":[{{"source":"F2","relation":"supports|refutes|produced_by|motivated_by","target":"H1","basis":"explicit|inferred","rationale":"one clause on why this edge holds"}}],
 "decisionSequence":[{{"finding":"F1","ordered":["D5","D2","D9"]}},{{"finding":"global","ordered":["D1"]}}]}}

===== NODE LIST =====
{nodes}
"""

# --- Flow recovery: a dedicated flow-only pass when Pass 1 produced no usable flow ---

FLOW_INSTRUCTIONS = """\
You are producing ONLY the process flow chart for a finished research run. A world
model has already been reconstructed (below); build a human-readable flow chart that
matches it, following the FLOW CHART RULES.

You are headless with NO TOOLS. Work only from the WORLD MODEL and EVIDENCE BUNDLE.
Ground every node title in THIS run's content (its idea, planning, report, artifacts,
and the world model's decisions/experiments). NEVER copy the illustrative example
node names from the rules.

RUN_ID: {run_id}

Output EXACTLY ONE JSON object and nothing else (no prose, no markdown fence):

  {{"elements": [ ... ], "edges": [ ... ]}}

- 8-15 meaningful, project-SPECIFIC nodes with verb-first operation titles.
- elements: each {{ "id" (kebab-case, unique), "clock" (integer t-order), "type" (an
  element-library type: intent|plan|constraint|research|literature_search|
  dataset_search|data_inspection|decision|method_design|branch|implementation|
  experiment_matrix|model_run|execution|analysis|evaluation|report_writing|
  validation|risk|result), "title", "summary",
  "sourceRefs": [{{ "type":"artifact", "path":"<a real file from the bundle>", "note":"" }}] }}
- edges: each {{ "from", "to", "type" }} referencing existing element ids, with a
  typed edge: leads_to | depends_on | produced | used_by | branches_to | validates |
  failed_then | recovered_by | informs.
- Do NOT provide x/y — layout is computed for you. Lay out by logic, not time.

===== FLOW CHART RULES =====
{flow_rules}

===== WORLD MODEL (align the flow to this) =====
{world_model}
"""

FLOW_REPAIR_INSTRUCTIONS = """\
Your flow JSON was unusable: {reason}. Re-output ONLY the corrected JSON object
{{"elements": [...], "edges": [...]}} — nothing else. Every element needs a non-empty
"id" and "title"; every edge's "from"/"to" must reference an existing element id; do
not include x/y.

YOUR PREVIOUS OUTPUT:
{previous}
"""


def _bundle_block(bundle):
    """The shared evidence bundle, formatted IDENTICALLY for every call so it forms a
    common prompt PREFIX. Anthropic's prompt cache is prefix-matched, so placing the
    big bundle first lets calls 2..N within a run read it from cache (≈90% cheaper
    input + faster prefill) instead of re-sending it. Quality-neutral: same content,
    and instructions-last is the recommended long-context structure."""
    return f"===== EVIDENCE BUNDLE (shared; do not echo) =====\n{bundle}\n\n"


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(obj, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, path)


# --- repair patches: merge a small correction into a prior result, so a repair
# regenerates only the broken items (~100 tokens) instead of the whole document
# (~9000 tokens). Quality is identical; only the wasted decode is removed. ---

# Top-level world-model arrays whose entries carry a stable "id"; a patch replaces
# the entry with the matching id and appends genuinely new ones, leaving the rest.
_WM_ID_ARRAYS = ("hypotheses", "experiments", "findings", "decisions", "assessments", "incidents")
_WM_WHOLESALE = ("cruxEvidence", "open_questions", "panel_layout")


def _merge_by_id(existing, items, id_key="id"):
    base = list(existing) if isinstance(existing, list) else []
    index = {x.get(id_key): i for i, x in enumerate(base) if isinstance(x, dict)}
    for item in items:
        if not isinstance(item, dict):
            continue
        key = item.get(id_key)
        if key in index:
            base[index[key]] = item
        else:
            base.append(item)
    return base


def apply_patch(world_model, patch):
    """Merge a minimal world-model repair patch. Returns the merged dict, or None if
    the patch isn't a usable object. Id-keyed arrays are merged entry-by-entry; other
    fields override. A full-model patch also merges correctly (degrades gracefully)."""
    if not isinstance(patch, dict):
        return None
    if isinstance(patch.get("world_model"), dict):  # tolerate an envelope
        patch = patch["world_model"]
    wm = copy.deepcopy(world_model)
    for key, val in patch.items():
        if key in _WM_ID_ARRAYS and isinstance(val, list):
            wm[key] = _merge_by_id(wm.get(key), val)
        elif key == "sections" and isinstance(val, dict):
            sections = wm.get("sections") if isinstance(wm.get("sections"), dict) else {}
            sections.update(val)
            wm["sections"] = sections
        else:  # scalar fields and wholesale arrays (cruxEvidence/open_questions/…)
            wm[key] = val
    return wm


def _heal_entity_links(world_model, fixes):
    """Drop links that would fail validation so one stray edge (a hallucinated
    relation like 'follows', a dangling/self/type-incompatible target, a duplicate)
    can't quarantine an otherwise-complete model. Mirrors check_entity_links' hard
    rules exactly, so what survives is guaranteed to pass. A missing/odd `basis` is
    defaulted to 'inferred' rather than dropped (trivially fixable, not a real fault).
    Links are optional enrichment — losing a bad one is far cheaper than a rebuild."""
    entities = {}
    for collection, kind in ENTITY_COLLECTIONS.items():
        for item in world_model.get(collection) or []:
            if isinstance(item, dict) and item.get("id"):
                entities[item["id"]] = {"kind": kind, "item": item}

    for source_id, entry in entities.items():
        links = entry["item"].get("links")
        if links is None:
            continue
        if not isinstance(links, list):
            entry["item"]["links"] = []
            fixes.append(f"{source_id}: dropped non-list links")
            continue
        kept, seen = [], set()
        for link in links:
            if not isinstance(link, dict):
                fixes.append(f"{source_id}: dropped malformed link")
                continue
            if link.get("basis") not in LINK_BASIS:
                link["basis"] = "inferred"
            relation, target = link.get("relation"), link.get("target")
            target_entry = entities.get(target)
            compat = LINK_COMPATIBILITY.get(relation)
            reason = None
            if relation not in LINK_RELATIONS:
                reason = f"bad relation {relation!r}"
            elif is_blank(link.get("rationale")):
                reason = "blank rationale"
            elif target == source_id:
                reason = "self-link"
            elif target_entry is None:
                reason = f"missing target {target!r}"
            elif compat and (entry["kind"] not in compat[0] or target_entry["kind"] not in compat[1]):
                reason = f"{entry['kind']} --{relation}--> {target_entry['kind']} not allowed"
            elif (relation, target) in seen:
                reason = "duplicate"
            if reason:
                fixes.append(f"{source_id}: dropped link ({reason})")
                continue
            seen.add((relation, target))
            kept.append(link)
        entry["item"]["links"] = kept


def normalize_world_model(world_model):
    """Self-heal deterministic cross-reference mistakes BEFORE validation, so a
    single mislabeled id (the most common quarantine cause) doesn't burn a full
    rebuild. Cheap, in-place, no model call. Currently heals `cruxEvidence`:

      - id exists but `type` is wrong  → fix the type from the id's real collection
        (F*→finding, D*→decision, I*→incident)
      - id points at nothing real (e.g. a hypothesis H*, or a dropped id) → remove
        the ref (cruxEvidence is optional; a bad link is worse than a missing one)
      - duplicate refs → de-duplicated

    Returns the list of human-readable fixes applied, for logging."""
    fixes = []

    # Backfill the uniform node envelope across every entity collection: `type` (from
    # the collection), and the provenance arrays `affects` / `basedOn` (default []).
    # Deterministic and additive — the model need not emit them, and type-specific
    # fields stay flat, so this never breaks the viewer. `ts` is mirrored from
    # updated_at when only the latter is present, so every node has a uniform stamp.
    for key, kind in (("hypotheses", "hypothesis"), ("experiments", "experiment"),
                      ("findings", "finding"), ("decisions", "decision"),
                      ("assessments", "assessment"), ("incidents", "incident")):
        for node in world_model.get(key) or []:
            if not isinstance(node, dict):
                continue
            if not node.get("type"):
                node["type"] = kind
            for arr in ("affects", "basedOn"):
                if not isinstance(node.get(arr), list):
                    node[arr] = []
            if not node.get("ts") and node.get("updated_at"):
                node["ts"] = node["updated_at"]

    # Self-heal experiment status synonyms — the model routinely writes "completed" /
    # "success" / "in progress" instead of the enum (done|failed|running). A trivial
    # synonym must never quarantine an expensive build, so map the common ones here.
    _exp_status_synonyms = {
        "completed": "done", "complete": "done", "finished": "done", "success": "done",
        "succeeded": "done", "passed": "done", "ok": "done",
        "error": "failed", "errored": "failed", "crashed": "failed", "failure": "failed", "aborted": "failed",
        "in_progress": "running", "in progress": "running", "in-progress": "running",
        "ongoing": "running", "active": "running", "started": "running",
    }
    for exp in world_model.get("experiments") or []:
        if isinstance(exp, dict):
            s = (exp.get("status") or "").strip().lower()
            if s in _exp_status_synonyms and exp.get("status") != _exp_status_synonyms[s]:
                fixes.append(f"{exp.get('id')}: normalized status {exp.get('status')!r} -> {_exp_status_synonyms[s]!r}")
                exp["status"] = _exp_status_synonyms[s]
            # An investigation needs a `name` (identity). The model occasionally drops it;
            # backfill from legacy agent / rationale / result so a missing name degrades to
            # an ugly-but-valid label instead of quarantining an expensive build.
            if is_blank(exp.get("name")):
                fallback = (exp.get("agent") or (exp.get("rationale") or "").strip()
                            or (exp.get("result") or "").strip() or exp.get("id") or "investigation")
                exp["name"] = fallback[:80]
                fixes.append(f"{exp.get('id')}: backfilled missing name")

    _heal_entity_links(world_model, fixes)

    # Provenance guard: a finding's `produced_by` must target an investigation that
    # actually produced a result — never one merely run by the resource_finder (gathers
    # inputs) or paper_writer (writes up outputs). Checks both the new `ranBy` provenance
    # field and the legacy `agent` field so pre-v3 models still self-heal. A wrong
    # provenance link is worse than a missing one, so drop the violators.
    nonrunner_ids = {e.get("id") for e in world_model.get("experiments") or []
                     if isinstance(e, dict) and (e.get("ranBy") or e.get("agent")) in ("resource_finder", "paper_writer")}
    if nonrunner_ids:
        for finding in world_model.get("findings") or []:
            if not isinstance(finding, dict) or not isinstance(finding.get("links"), list):
                continue
            kept = []
            for link in finding["links"]:
                if (isinstance(link, dict) and link.get("relation") == "produced_by"
                        and link.get("target") in nonrunner_ids):
                    fixes.append(f"{finding.get('id')}: dropped produced_by {link.get('target')} "
                                 f"(an input-gathering/write-up stage, not a result-producing investigation)")
                    continue
                kept.append(link)
            finding["links"] = kept

    collection_of = {}
    for key, kind in (("findings", "finding"), ("decisions", "decision"), ("incidents", "incident")):
        for item in world_model.get(key) or []:
            if isinstance(item, dict) and item.get("id"):
                collection_of[item["id"]] = kind

    crux_evidence = world_model.get("cruxEvidence")
    if isinstance(crux_evidence, list):
        healed, seen = [], set()
        for ref in crux_evidence:
            if not isinstance(ref, dict):
                continue
            rid, rtype = ref.get("id"), ref.get("type")
            real_type = collection_of.get(rid)
            if real_type is None:
                fixes.append(f"dropped cruxEvidence {rtype}:{rid} (no such finding/decision/incident)")
                continue
            if real_type != rtype:
                fixes.append(f"cruxEvidence {rid}: type {rtype}→{real_type}")
                ref = {**ref, "type": real_type}
            dedup_key = (ref["type"], rid)
            if dedup_key in seen:
                fixes.append(f"dropped duplicate cruxEvidence {ref['type']}:{rid}")
                continue
            seen.add(dedup_key)
            healed.append(ref)
        world_model["cruxEvidence"] = healed
    return fixes


# --- deterministic evidence gathering (replaces the agent's tool loop) ---

def list_run_files(run_dir):
    out = []
    for root, dirs, files in os.walk(run_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, run_dir)
            try:
                out.append((rel, os.path.getsize(full)))
            except OSError:
                pass
    return sorted(out)


def read_capped(path, cap):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read(cap + 1)
    except OSError:
        return None
    return text[:cap] + "\n…[truncated]" if len(text) > cap else text


def _compact_params(tool_name, params):
    """One-line summary of a tool call's salient parameter."""
    if not isinstance(params, dict):
        return ""
    for key in ("command", "file_path", "absolute_path", "path", "old_string", "url", "query"):
        if params.get(key):
            val = str(params[key]).replace("\n", " ")
            return val[:200]
    return ""


def build_transcript_digest(run_dir):
    """Compact, ordered execution trace from the run's transcripts.

    The reconstruction model is told NOT to read raw transcripts (token
    discipline), and a clean final workspace has no memory of recovered faults
    (a missing dependency installed and forgotten). Those silent
    Action->Failure->Recovery->Retry->Success loops live ONLY in the transcript.
    This digest surfaces them cheaply: the ordered tool-call sequence + result
    status + duration, so the model can spot a fast-returning call followed by an
    install/download/fix and a re-run of the same target — a recovered fault.

    stdout/stderr is frequently NOT captured by the run harness, so an inner
    failure can still be marked status=success at the tool layer. Detection must
    lean on the fix-then-retry SHAPE and suspicious-short durations, not status.
    """
    present = {rel for rel, _ in list_run_files(run_dir)}
    transcripts = sorted(
        rel for rel in present
        if any(fnmatch.fnmatch(rel, pat) for pat in TRANSCRIPT_GLOBS)
    )
    if not transcripts:
        return "", []

    sections, read = [], []
    for rel in transcripts:
        recs, ln = [], 0
        try:
            with open(os.path.join(run_dir, rel), encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    ln += 1
                    raw = raw.strip()
                    if not raw.startswith("{"):
                        continue
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    obj["_ln"] = ln
                    recs.append(obj)
        except OSError:
            continue

        uses = {r.get("tool_id"): r for r in recs if r.get("type") == "tool_use"}

        def _secs(use, res):
            try:
                a = datetime.datetime.fromisoformat(use["timestamp"].replace("Z", "+00:00"))
                b = datetime.datetime.fromisoformat(res["timestamp"].replace("Z", "+00:00"))
                return (b - a).total_seconds()
            except (KeyError, ValueError, TypeError):
                return None

        lines = []
        for r in recs:
            if r.get("type") != "tool_result":
                continue
            use = uses.get(r.get("tool_id"))
            if not use:
                continue
            name = use.get("tool_name", "?")
            # Keep the fault-bearing call types; drop pure status/topic chatter.
            if name not in ("run_shell_command", "write_file", "replace", "read_file"):
                if r.get("status") != "error":
                    continue
            dur = _secs(use, r)
            param = _compact_params(name, use.get("parameters"))
            flag = ""
            # Flag only a real SCRIPT/TEST run (python file.py, pytest, npm test)
            # that returned almost instantly — a likely crash on import/setup.
            # Deliberately NOT `python -c "..."` inline probes: those are cheap by
            # nature, and flagging them floods the digest with false positives that
            # push the model to over-report incidents (and lengthen generation).
            runs_script = bool(re.search(
                r"(python3?|node|Rscript)\s+[^\s-][\w./-]*\.(py|js|R)\b|\bpytest\b|\bnpm (run|test)\b",
                param))
            if r.get("status") == "error":
                flag = "  <<TOOL_ERROR"
            elif name == "run_shell_command" and runs_script and dur is not None and dur < 10:
                flag = "  <<fast-return (ran a script but exited in <10s — possible silent fail)"
            durtxt = f"{dur:.0f}s" if dur is not None else "?"
            lines.append(f"L{use['_ln']:<4} {use.get('timestamp','')[11:19]} {durtxt:>5} {name}: {param}{flag}")

        if lines:
            read.append(rel)
            sections.append(f"\n### {rel}\n" + "\n".join(lines))

    if not sections:
        return "", []

    header = (
        "## Execution trace (ordered tool calls, for detecting SILENT recovered faults)\n"
        "Look for fix-then-retry loops: a run_shell_command that returns fast or errors, "
        "followed by an install/download/path-fix and a RE-RUN of the same target -> that is "
        "a recovered execution fault (incident kind=recovered). The agent's reports usually "
        "do NOT mention these; only this trace does. stdout is not captured, so infer the "
        "failure from the shape, not from status (a step can read success yet have failed).\n"
        + "Reference these items in evidence as itemId 'L<line>'.\n"
    )
    digest = header + "".join(sections)
    if len(digest) > TRANSCRIPT_DIGEST_CAP:
        # Cut at the last newline before the cap so a trace line (and its L<n>
        # reference) is never split mid-way.
        digest = digest[:TRANSCRIPT_DIGEST_CAP]
        nl = digest.rfind("\n")
        if nl > 0:
            digest = digest[:nl]
    return digest, read


def build_evidence_bundle(run_dir):
    files = list_run_files(run_dir)
    present = [rel for rel, _ in files]
    present_set = set(present)
    missing = [p for p in EXPECTED_ARTIFACTS if p not in present_set]

    to_read = [p for p in ARTIFACT_READ_LIST if p in present_set]
    for pattern in ARTIFACT_GLOBS:
        for rel in present:
            if fnmatch.fnmatch(rel, pattern) and rel not in to_read:
                to_read.append(rel)

    parts, contents, total = [], [], 0
    for rel in to_read:
        body = read_capped(os.path.join(run_dir, rel), PER_FILE_CAP)
        if body is None or total + len(body) > TOTAL_CAP:
            continue
        total += len(body)
        contents.append(rel)
        parts.append(f"\n## === {rel} ===\n{body}")

    # Source code, read into its own budget. This is where coding decisions live;
    # without it the model can only infer them from prose. Skip files already read.
    code_to_read = []
    for pattern in CODE_GLOBS:
        for rel in present:
            if fnmatch.fnmatch(rel, pattern) and rel not in code_to_read and rel not in contents:
                code_to_read.append(rel)
    code_parts, code_read, code_total = [], [], 0
    for rel in sorted(code_to_read):
        body = read_capped(os.path.join(run_dir, rel), PER_FILE_CAP)
        if body is None or code_total + len(body) > CODE_TOTAL_CAP:
            continue
        code_total += len(body)
        code_read.append(rel)
        code_parts.append(f"\n## === {rel} ===\n{body}")

    transcript_digest, transcripts_read = build_transcript_digest(run_dir)

    inventory = {
        "runId": os.path.basename(run_dir),
        "generatedBy": "deterministic Python scan (harness)",
        "generatedAt": now_iso(),
        "files_present": present,
        "expected_but_missing": missing,
        "artifacts_read": contents,
        "code_read": code_read,
        "transcripts_digested": transcripts_read,
    }
    # The file listing is capped: runs with cloned code repos can have 10k+ files,
    # and an uncapped list alone can exceed the model's context window.
    file_lines = [f"- {rel} ({size} bytes)" for rel, size in files]
    file_list, used, shown = [], 0, 0
    for line in file_lines:
        if used + len(line) + 1 > FILE_LIST_CAP:
            break
        file_list.append(line)
        used += len(line) + 1
        shown += 1
    if shown < len(file_lines):
        file_list.append(f"- … ({len(file_lines) - shown} more files omitted)")

    bundle = (
        "## Files present in the run folder\n"
        + "\n".join(file_list)
        + "\n\n## Expected-but-missing\n"
        + ("\n".join(f"- {m}" for m in missing) or "- (none)")
        + "\n\n## Artifact contents (this is ALL the content you get)\n"
        + "".join(parts)
        + ("\n\n## Source code (the implementation — cite these paths for coding decisions)\n"
           + "".join(code_parts) if code_parts else "")
        + ("\n\n" + transcript_digest if transcript_digest else "")
    )
    # Final safety net: never exceed the context window, whatever a run throws at us.
    if len(bundle) > BUNDLE_CAP:
        bundle = bundle[:BUNDLE_CAP] + "\n\n[... bundle truncated to fit the model context window ...]"
    return bundle, inventory


# --- flow chart (LLM-generated, laid out deterministically) ---

def layout_flow(elements):
    """Assign x/y: columns by clock rank (logical order), stack parallel nodes."""
    ranks = sorted({el.get("clock", 0) for el in elements})
    rank_of = {clock: i for i, clock in enumerate(ranks)}
    columns = {}
    for el in elements:
        columns.setdefault(rank_of.get(el.get("clock", 0), 0), []).append(el)
    laid = []
    for col_index in sorted(columns):
        for row, el in enumerate(columns[col_index]):
            placed = dict(el)
            placed["x"] = 80 + col_index * 340
            placed["y"] = 150 + row * 185
            laid.append(placed)
    return laid


def process_flow(flow):
    """Validate/normalize the model's flow into the frontend's element+graph shape.
    Returns (flow_dict, None) on success, or (None, reason) explaining the reject so
    the caller can log it and attempt a dedicated flow pass instead of silently
    dropping the Flow tab."""
    if not isinstance(flow, dict):
        return None, "model output had no 'flow' object"
    raw_elements = flow.get("elements")
    if not isinstance(raw_elements, list) or not raw_elements:
        return None, "flow.elements is missing or not a non-empty list"
    elements = []
    for el in raw_elements:
        if not isinstance(el, dict) or not el.get("id") or not el.get("title"):
            continue
        refs = []
        for ref in (el.get("sourceRefs") or []):
            if isinstance(ref, dict) and (ref.get("path") or ref.get("file")):
                refs.append({"file": ref.get("path") or ref.get("file"), "itemId": None,
                             "eventType": "artifact", "kind": "artifact", "note": ref.get("note", "")})
        elements.append({
            "id": el["id"], "clock": el.get("clock", 0), "type": el.get("type", "result"),
            "title": el["title"], "summary": el.get("summary", ""),
            "support": el.get("support", ""), "pattern": el.get("pattern", "semantic step"),
            "status": el.get("status", "completed"), "sourceRefs": refs,
        })
    if not elements:
        return None, "no flow element had both a non-empty id and title"
    valid = {el["id"] for el in elements}
    edges = []
    for edge in (flow.get("edges") or []):
        if isinstance(edge, dict) and edge.get("from") in valid and edge.get("to") in valid:
            edges.append({"id": f"{edge['from']}->{edge['to']}", "from": edge["from"],
                          "to": edge["to"], "type": edge.get("type", "leads_to")})
    return {"elements": layout_flow(elements), "edges": edges}, None


# --- entity graph (the Flow tab = findings/hypotheses/experiments, not a process flow) ---

def build_entity_flow(world_model):
    """Project the world model's findings / hypotheses / experiments and their reconciled
    links into the flow shape (elements + edges), so the existing Flow renderer draws the
    SCIENTIFIC graph: hypotheses → experiments → findings, with supports/refutes/
    produced_by/motivated_by edges. Laid out in three columns by clock rank."""
    elements = []
    for h in (world_model.get("hypotheses") or []):
        if isinstance(h, dict) and h.get("id"):
            elements.append({"id": h["id"], "clock": 0, "type": "hypothesis",
                             "title": (h.get("statement") or h["id"])[:90],
                             "summary": h.get("statement", ""), "status": h.get("status", "")})
    for e in (world_model.get("experiments") or []):
        if isinstance(e, dict) and e.get("id"):
            elements.append({"id": e["id"], "clock": 1, "type": "experiment",
                             "title": (e.get("name") or e.get("agent") or e["id"])[:90],
                             "summary": (e.get("design") or e.get("result") or e.get("rationale") or "")[:240],
                             "status": e.get("status", "")})
    for f in (world_model.get("findings") or []):
        if isinstance(f, dict) and f.get("id"):
            elements.append({"id": f["id"], "clock": 2, "type": "finding",
                             "title": (f.get("text") or f["id"])[:90],
                             "summary": (f.get("insight") or f.get("text") or ""), "status": f.get("kind", "")})
    valid = {el["id"] for el in elements}
    # Display direction: the stored links point "backwards" (F->H, F->E, E->H). Reverse
    # motivated_by / produced_by so the graph reads left-to-right as the scientific method
    # — H -motivates-> E -produces-> F — and keep supports/refutes as the F->H feedback edge.
    edge_display = {
        "motivated_by": (True, "motivates"),
        "produced_by": (True, "produces"),
        "supports": (False, "supports"),
        "refutes": (False, "refutes"),
    }
    edges, seen = [], set()
    for coll in ("hypotheses", "experiments", "findings"):
        for item in (world_model.get(coll) or []):
            if not isinstance(item, dict):
                continue
            src = item.get("id")
            for link in (item.get("links") or []):
                tgt = link.get("target")
                if src not in valid or tgt not in valid:
                    continue
                reverse, dtype = edge_display.get(link.get("relation"), (False, link.get("relation") or "leads_to"))
                a, b = (tgt, src) if reverse else (src, tgt)
                key = (a, b, dtype)
                if key in seen:
                    continue
                seen.add(key)
                edges.append({"from": a, "to": b, "type": dtype})
    return {"elements": elements, "edges": edges}


# --- model invocation ---

def extract_json(text):
    text = (text or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except ValueError:
            pass
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
    return None


def isolated_claude_env():
    """Environment for the nested `claude` CLI with the PARENT Claude Code session
    stripped out.

    CRITICAL: without this, the headless reconstruction inherits the caller's
    CLAUDE_CODE_SESSION_ID (and MCP/agent/task context) and JOINS that live
    session — posting into an existing chat/channel instead of running as a clean
    standalone call. The reconstruction must never touch the user's conversation.
    Auth (ANTHROPIC_*) and PATH/HOME are preserved so the CLI can still run.
    """
    env = dict(os.environ)
    for key in list(env):
        if (key.startswith("CLAUDE_CODE") or key.startswith("CLAUDE_AGENT")
                or key.startswith("MCP_")
                or key in {"CLAUDECODE", "AI_AGENT", "CLAUDE_EFFORT"}):
            del env[key]
    return env


def invoke_claude(prompt, model, timeout):
    if not shutil.which("claude"):
        raise RuntimeError("`claude` CLI not found on PATH. Install Claude Code, or run with --dry-run.")
    # Force a single, tool-free assistant turn. The whole evidence bundle is inline,
    # so the model must reason and answer in one shot — never start an agentic
    # Read/Glob/Bash loop (the adversarial review prompt otherwise tempts the model
    # into exploring the run folder, which turns a ~1-min call into many minutes).
    cmd = ["claude", "-p", "--output-format", "json", "--model", model,
           "--max-turns", "1", "--disallowedTools",
           "Bash,Read,Edit,Write,Glob,Grep,WebFetch,WebSearch,Task,NotebookEdit"]
    # The model occasionally emits a stray tool_use block (→ error_max_turns) or hits a
    # transient API error. These are stochastic, so retry once before giving up — a single
    # flaky call shouldn't waste an expensive multi-call run.
    last_detail = ""
    for _ in range(2):
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              timeout=timeout, env=isolated_claude_env())
        # With --output-format json, claude reports API errors in STDOUT (is_error/result),
        # not stderr — surface that so failures aren't a blank "exited 1:".
        detail = (proc.stderr or "").strip()
        if not detail and proc.stdout:
            try:
                detail = json.loads(proc.stdout).get("result", "") or proc.stdout.strip()
            except ValueError:
                detail = proc.stdout.strip()
        if proc.returncode != 0:
            last_detail = f"claude exited {proc.returncode}: {detail[:600]}"
            continue
        try:
            envelope = json.loads(proc.stdout)
        except ValueError:
            return proc.stdout, None
        if envelope.get("is_error"):
            last_detail = f"claude API error: {envelope.get('result', '')[:600]}"
            continue
        return envelope.get("result", proc.stdout), envelope.get("total_cost_usd")
    raise RuntimeError(last_detail or "claude failed after retry")


def stamp(world_model, model):
    block = world_model.setdefault("reconstruction", {})
    block["promptVersion"] = PROMPT_VERSION
    block["model"] = model
    block["generatedAt"] = now_iso()


def read_flow_llm(data_dir):
    try:
        with open(os.path.join(data_dir, "flow-llm.json"), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {"elements": [], "edges": []}


# --- Pass 2 validation (mirrors the world-model validator's discipline) ---

IMPORTANCE_LEVELS = {"low", "medium", "high", "critical"}
RUN_VERDICTS = {"trustworthy", "mixed", "unconvincing"}


def _blank(value):
    return not isinstance(value, str) or not value.strip()


def validate_review(review, run_dir, decision_ids):
    """Hard checks fed back into the Pass-2 repair loop. Returns a list of problem
    strings (empty == valid)."""
    problems = []
    if not isinstance(review, dict):
        return ["output was not a JSON object with a 'decisions' array"]
    decisions = review.get("decisions")
    if not isinstance(decisions, list):
        return ["missing 'decisions' array"]

    seen = set()
    importance_by_id = {}
    for entry in decisions:
        if not isinstance(entry, dict):
            problems.append("a decisions entry is not an object")
            continue
        did = entry.get("decisionId")
        if did not in decision_ids:
            problems.append(f"decisions references unknown decisionId: {did!r}")
        if did in seen:
            problems.append(f"decisions has a duplicate decisionId: {did!r}")
        seen.add(did)
        importance_by_id[did] = entry.get("importance")
        if entry.get("importance") not in IMPORTANCE_LEVELS:
            problems.append(f"decision {did}: bad/missing importance {entry.get('importance')!r}")
        if _blank(entry.get("importanceRationale")):
            problems.append(f"decision {did}: importanceRationale is required")

    # NOTE: the reviewer SELECTS load-bearing decisions; omitted ones intentionally default
    # to low in _finalize_review. So there is no "missing entries" requirement — that is what
    # used to mask the truncation (model returns the first N, rest silently low).

    # (Front-page selection is NOT here — it's a separate abstract-only Pass-1 call stored on
    # world_model.frontPageDecisions; Pass 2 only assigns importance + the run-quality verdict.)

    # runQuality: a verdict + rationale a reviewer would write.
    rq = review.get("runQuality")
    if not isinstance(rq, dict):
        problems.append("missing 'runQuality' object")
    else:
        if rq.get("verdict") not in RUN_VERDICTS:
            problems.append(f"runQuality.verdict must be one of {sorted(RUN_VERDICTS)}, got {rq.get('verdict')!r}")
        if _blank(rq.get("rationale")):
            problems.append("runQuality.rationale is required")
    return problems


_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_HIGH_LEVEL_LAYERS = {"hypothesis", "experiment_design", "interpretation"}


def _finalize_review(obj, world_model):
    """Turn the reviewer's (possibly imperfect) first reply into a guaranteed-valid
    overlay — deterministically, with NO further model call. This is what makes Pass 2
    robust: the model only has to produce a rough draft; code does the fixing.

      - one importance entry per world-model decision (model's if valid, else 'low');
      - paperRef floor: a decision the paper discusses is bumped to >= high;
      - runQuality coerced to a valid verdict + rationale.
    (Front-page selection is a SEPARATE Pass-1 call — world_model.frontPageDecisions — not
    part of the review overlay.)
    """
    wm = {d["id"]: d for d in (world_model.get("decisions") or [])
          if isinstance(d, dict) and d.get("id")}
    model_by_id = {}
    for e in (obj.get("decisions") or []):
        if isinstance(e, dict) and e.get("decisionId") in wm and e["decisionId"] not in model_by_id:
            model_by_id[e["decisionId"]] = e

    decisions, bumped = [], 0
    for did, d in wm.items():
        e = model_by_id.get(did) or {}
        imp = e.get("importance") if e.get("importance") in IMPORTANCE_LEVELS else "low"
        rationale = (e.get("importanceRationale") or "").strip() or "Routine — not selected as load-bearing."
        if d.get("paperRef") and _RANK[imp] < _RANK["high"]:
            imp, rationale = "high", (rationale + " [discussed in the paper]")
            bumped += 1
        decisions.append({"decisionId": did, "importance": imp, "importanceRationale": rationale})

    rq = obj.get("runQuality") if isinstance(obj.get("runQuality"), dict) else {}
    verdict = rq.get("verdict") if rq.get("verdict") in RUN_VERDICTS else "mixed"
    rq_rationale = (rq.get("rationale") or "").strip() or "Reviewer verdict not produced; defaulted."
    return ({"runQuality": {"verdict": verdict, "rationale": rq_rationale},
             "decisions": decisions}, bumped)


def _review_view(world_model):
    """Compact projection of the world model for the reviewer: enough to judge importance
    (each finding + each decision's id/finding/layer/question/chosen/rationale) WITHOUT the
    bulky options/evidence/paperRef objects. The full model is ~130k chars and was being
    truncated at REPAIR_PREVIOUS_CAP (60k) — which cut off the entire INTERPRETATION tail
    (D25+), so the reviewer never saw it. Compacting (~4x smaller) fits every decision."""
    findings = [{"id": f.get("id"), "kind": f.get("kind"), "text": f.get("text"),
                 "insight": f.get("insight")}
                for f in (world_model.get("findings") or []) if isinstance(f, dict)]
    decisions = [{"id": d.get("id"), "finding": d.get("finding"), "layer": d.get("layer"),
                  "question": d.get("question"), "chosen": d.get("chosen"),
                  "statedRationale": d.get("statedRationale"), "hasPaperRef": bool(d.get("paperRef"))}
                 for d in (world_model.get("decisions") or []) if isinstance(d, dict)]
    return {"abstract": world_model.get("abstract"), "headline": world_model.get("headline"),
            "narrative": world_model.get("narrative"), "findings": findings, "decisions": decisions}


def run_review(run_dir, data_dir, model, bundle, world_model, timeout, max_repairs):
    """Pass 2: PI review. Reads the paper (in the bundle) + world model and assigns
    paper-reading `importance` to every decision, picks the abstract-grounded front-page
    decisions, and writes a run-quality verdict → decision-review.json.

    Robustness: the model only needs to produce a rough draft (a dict with a `decisions`
    list). `_finalize_review` then deterministically repairs it into a valid overlay — no
    fragile LLM 'patch' round-trip. Returns 0 on success, 1 on quarantine."""
    run_id = os.path.basename(run_dir)
    decision_ids = {d.get("id") for d in (world_model.get("decisions") or [])
                    if isinstance(d, dict) and d.get("id")}
    if not decision_ids:
        print(f"[review] {run_id}: world model has no decisions to review — skipping Pass 2", flush=True)
        return 0
    prompt = _bundle_block(bundle) + REVIEW_INSTRUCTIONS.format(
        run_id=run_id,
        world_model=json.dumps(_review_view(world_model), ensure_ascii=False)[:REPAIR_PREVIOUS_CAP])

    # Re-run the SAME full prompt until it yields a usable draft (a dict with a decisions
    # list). No 'minimal patch' call — that was the deterministic crash point.
    total_cost, obj, last_text = 0.0, None, ""
    for attempt in range(max_repairs + 1):
        try:
            last_text, cost = invoke_claude(prompt, model, timeout)
            total_cost += cost or 0
            cand = extract_json(last_text)
            if isinstance(cand, dict) and isinstance(cand.get("decisions"), list) and cand["decisions"]:
                obj = cand
                break
        except RuntimeError as exc:
            print(f"[review] {run_id}: call failed ({str(exc)[:120]}) — retrying", flush=True)
        if attempt < max_repairs:
            print(f"[review-retry {attempt + 1}/{max_repairs}] {run_id}: no usable draft — regenerating", flush=True)

    if obj is None:
        write_json(os.path.join(data_dir, "review.invalid.json"), {"raw": str(last_text)[:8000]})
        print(f"[QUARANTINE] {run_id}: review produced no usable draft after retries — "
              f"decision-review.json left unwritten (cost ${total_cost:.2f})", flush=True)
        return 1

    overlay, bumped = _finalize_review(obj, world_model)
    write_json(os.path.join(data_dir, "decision-review.json"), overlay)
    decs = overlay["decisions"]
    key = sum(1 for r in decs if r["importance"] in ("high", "critical"))
    selected = sum(1 for r in decs if r["importance"] in ("critical", "high", "medium"))
    # key-set layer breakdown — so interpretation coverage (the binding constraint) is visible.
    layer_of = {d["id"]: d.get("layer") for d in (world_model.get("decisions") or []) if isinstance(d, dict)}
    key_layers = collections.Counter(layer_of.get(r["decisionId"]) for r in decs
                                     if r["importance"] in ("high", "critical"))
    print(f"[ok] {run_id}: review written — {selected} selected / {len(decs)} ({key} key), "
          f"key layers {dict(key_layers)}, verdict {overlay['runQuality']['verdict']} "
          f"— cost ${total_cost:.2f} ({model})", flush=True)
    return 0


# --- Finding filter: which findings to SHOW BY DEFAULT (claim-level spine) vs hide ---
# A simple, reliable overlay: ONE call over the full paper + every finding returns a
# show_by_default flag per finding, so the UI can default to the claim-level spine and
# reveal the routine result-rows / robustness notes / method details on demand. Mirrors
# the decision-review overlay: the model produces a rough draft, code completes it
# deterministically (fail-open) → finding-review.json. Hidden findings are NOT removed
# from world_model.json (that would orphan decision.finding) — this is a VIEW overlay.
FINDING_FILTER_INSTRUCTIONS = """\
You are a research-run FINDING FILTER. Decide which findings a human reviewer should see
BY DEFAULT. The reviewer wants to quickly judge whether the run made good SCIENTIFIC
JUDGMENTS — they do NOT want to wade through every result row, metric fragment, method
detail, or robustness note by default.

You see the full paper / report (in the EVIDENCE BUNDLE above) and the run's FINDINGS list
below. For EACH finding, return show_by_default: true or false. Do NOT rank, do NOT assign
importance, do NOT rewrite or create findings — only classify the ones listed.

Core principle: show a finding by default ONLY if it is a CLAIM-LEVEL judgment that helps a
reviewer evaluate the run's reasoning. Hide it if it is mainly evidence, a single table-row /
condition-level result, a method / implementation detail, a robustness note, or a sub-result
that mostly supports a higher-level finding.

show_by_default: TRUE if ANY of these hold:
 1. It resolves or substantially changes a major hypothesis (supported / refuted / mixed / conditional / negative).
 2. It is part of the paper's central story — remove it and the abstract / headline / conclusion would have to change.
 3. It is an interpretation-level judgment (e.g. "the effect is a measurement artifact", "X is a steering knob, not a quality lever", "this is the real headline").
 4. It identifies a crux or validity risk (two metrics measure different constructs; the result hinges on whether a metric is valid; the design does / doesn't isolate the intended variable).
 5. It changes the paper's practical recommendation ("use X when Y matters", "don't report metric Z alone", "avoid X when novelty matters").

show_by_default: FALSE if ANY of these hold:
 1. It is only a single table-row / condition-level number (e.g. "condition A scores 5.94", "B has p=0.006").
 2. It is mainly evidence for a broader finding (one condition's effect supporting a trade-off; inter-judge agreement supporting a higher claim; a robustness check supporting a main result).
 3. It is a method / implementation detail (seed, cache hits, provider, max tokens, schema, retries, normalization, bootstrap count).
 4. It is a robustness / reproducibility note that does NOT change the credibility of a central result (length-covariate robustness, exact cache reproduction, runtime / cost).
 5. It duplicates a higher-level finding — keep the broader, more interpretive one shown and hide the narrower one.

The test is NOT "is this true?" — it is "should a reviewer judging the run's RESEARCH
JUDGMENT see this by default?". When genuinely unsure, prefer show_by_default: true.

RUN_ID: {run_id}

Output EXACTLY ONE JSON object, nothing else (no prose, no markdown fence):
{{"findings":[{{"id":"F1","show_by_default":true,"reason":"one short clause"}}]}}
Use ONLY the F-ids listed; return one entry per finding.

===== FINDINGS =====
{findings}
"""


def _finding_filter_prompt(run_id, findings, bundle):
    rows = []
    for f in findings or []:
        if not isinstance(f, dict) or not f.get("id"):
            continue
        line = f"- {f['id']} [{f.get('kind') or 'result'}]: {(f.get('text') or '')[:300]}"
        if f.get("insight"):
            line += f"\n    insight: {str(f['insight'])[:240]}"
        rows.append(line)
    return (_bundle_block(bundle)
            + FINDING_FILTER_INSTRUCTIONS.format(run_id=run_id, findings="\n".join(rows) or "(none)"))


def finalize_finding_filter(obj, world_model):
    """Complete the filter's reply into a guaranteed one-entry-per-finding overlay.
    Fail-open: a finding the model omitted or garbled defaults to SHOWN (never silently
    vanishes). Findings cited by cruxEvidence are force-shown."""
    findings = [f for f in (world_model.get("findings") or [])
                if isinstance(f, dict) and f.get("id")]
    model_by_id = {}
    for entry in (obj or {}).get("findings") or []:
        if isinstance(entry, dict) and entry.get("id") and entry["id"] not in model_by_id:
            model_by_id[entry["id"]] = entry
    forced = {ev.get("id") for ev in (world_model.get("cruxEvidence") or [])
              if isinstance(ev, dict) and ev.get("type") == "finding" and ev.get("id")}
    out = []
    for f in findings:
        fid = f["id"]
        entry = model_by_id.get(fid) or {}
        show = entry.get("show_by_default")
        if not isinstance(show, bool):
            show = True  # fail-open: unseen / garbled → show
        reason = (entry.get("reason") or "").strip()
        if fid in forced and not show:
            show, reason = True, (reason + " [force-shown: cited as crux evidence]").strip()
        out.append({"id": fid, "show_by_default": show,
                    "reason": reason or ("Claim-level — shown by default." if show
                                         else "Routine / supporting detail — hidden by default.")})
    return {"findings": out}


def run_finding_filter(run_dir, data_dir, model, bundle, world_model, timeout, max_repairs):
    """Soft overlay pass: classify each finding show_by_default (claim-level vs routine)
    over the full paper + every finding → finding-review.json. Non-blocking: it always
    returns 0, and on any failure the overlay fails open (everything shown = today's
    behavior)."""
    run_id = os.path.basename(run_dir)
    findings = [f for f in (world_model.get("findings") or [])
                if isinstance(f, dict) and f.get("id")]
    if not findings:
        print(f"[findings] {run_id}: no findings to filter — skipping", flush=True)
        return 0
    prompt = _finding_filter_prompt(run_id, findings, bundle)
    obj, total_cost = None, 0.0
    for attempt in range(max_repairs + 1):
        try:
            text, cost = invoke_claude(prompt, model, timeout)
        except Exception as exc:  # noqa: BLE001 — soft pass; degrade to show-all
            print(f"[findings] {run_id}: call failed ({exc}) — overlay fails open to show-all", flush=True)
            break
        total_cost += cost or 0
        cand = extract_json(text)
        if isinstance(cand, dict) and isinstance(cand.get("findings"), list):
            obj = cand
            break
        print(f"[findings] {run_id}: non-JSON reply — retry {attempt + 1}/{max_repairs}", flush=True)
    overlay = finalize_finding_filter(obj, world_model)
    write_json(os.path.join(data_dir, "finding-review.json"), overlay)
    shown = sum(1 for f in overlay["findings"] if f["show_by_default"])
    print(f"[ok] {run_id}: finding-review.json written — {shown}/{len(overlay['findings'])} "
          f"shown by default (cost ${total_cost:.2f})", flush=True)
    return 0


def _graph_review_nodes(world_model):
    """Compact node list for the graph/sequence review: ids + just enough text to judge
    relationships and ordering, kept small so the call is cheap."""
    H = [{"id": h.get("id"), "statement": h.get("statement"), "status": h.get("status")}
         for h in (world_model.get("hypotheses") or []) if isinstance(h, dict) and h.get("id")]
    E = [{"id": e.get("id"), "name": e.get("name") or e.get("agent"), "mode": e.get("mode"),
          "status": e.get("status"), "result": (e.get("result") or "")[:320]}
         for e in (world_model.get("experiments") or []) if isinstance(e, dict) and e.get("id")]
    F = [{"id": f.get("id"), "kind": f.get("kind"), "text": (f.get("text") or "")[:320],
          "insight": (f.get("insight") or None)}
         for f in (world_model.get("findings") or []) if isinstance(f, dict) and f.get("id")]
    D = [{"id": d.get("id"), "finding": d.get("finding"), "layer": d.get("layer"),
          "question": (d.get("question") or "")[:200], "chosen": (d.get("chosen") or "")[:160]}
         for d in (world_model.get("decisions") or []) if isinstance(d, dict) and d.get("id")]
    return ("HYPOTHESES:\n" + json.dumps(H, ensure_ascii=False)
            + "\n\nEXPERIMENTS:\n" + json.dumps(E, ensure_ascii=False)
            + "\n\nFINDINGS:\n" + json.dumps(F, ensure_ascii=False)
            + "\n\nDECISIONS (grouped by their `finding`):\n" + json.dumps(D, ensure_ascii=False))


def apply_graph_review(world_model, review):
    """Replace the F/H/E graph links with the reviewed edge set, and set decision.sequence
    from the reviewed per-finding order. Decision-owned links are left untouched. The
    caller MUST run normalize_world_model afterwards (it heals any invalid edge). Returns
    human-readable notes for logging."""
    notes = []
    # 1) Reset graph-layer links (findings/hypotheses/experiments), then attach the review's.
    by_id = {}
    for coll in ("hypotheses", "experiments", "findings"):
        for item in (world_model.get(coll) or []):
            if isinstance(item, dict):
                item["links"] = []
                if item.get("id"):
                    by_id[item["id"]] = item
    applied = 0
    for link in (review.get("links") or []):
        if not isinstance(link, dict):
            continue
        src = by_id.get(link.get("source"))
        if src is None:
            continue
        src["links"].append({
            "relation": link.get("relation"),
            "target": link.get("target"),
            "basis": link.get("basis") if link.get("basis") in ("explicit", "inferred") else "inferred",
            "rationale": link.get("rationale") or "reconciled by graph review",
        })
        applied += 1
    notes.append(f"attached {applied} F/H/E links (pre-heal)")

    # 2) Decision sequence: within-finding ordinal from the review's ordered lists.
    seq = {}
    for grp in (review.get("decisionSequence") or []):
        if not isinstance(grp, dict):
            continue
        for i, did in enumerate(grp.get("ordered") or []):
            if did not in seq:
                seq[did] = i
    fallback = (max(seq.values()) + 1) if seq else 0
    ordered = 0
    decisions = world_model.get("decisions") or []
    for d in decisions:
        if isinstance(d, dict) and d.get("id"):
            if d["id"] in seq:
                d["sequence"] = seq[d["id"]]
                ordered += 1
            else:
                d["sequence"] = fallback  # unsequenced → after the ordered ones in its group
    notes.append(f"sequenced {ordered}/{len(decisions)} decisions")
    return notes


def review_graph_and_sequence(run_id, model, world_model, timeout, max_repairs):
    """Dedicated review pass (Links + decision order): reconcile the F/H/E relationship
    graph and order each finding's decisions causally. Mutates world_model IN PLACE; the
    caller re-normalizes/validates and writes. Returns the total cost (0 on skip/failure —
    a failed review leaves the existing links/sequence untouched, never corrupts)."""
    if not (world_model.get("findings") or world_model.get("hypotheses")):
        print(f"[graph-review] {run_id}: no findings/hypotheses to relate — skipping", flush=True)
        return 0.0
    prompt = GRAPH_SEQUENCE_INSTRUCTIONS.format(run_id=run_id, nodes=_graph_review_nodes(world_model))
    total, obj = 0.0, None
    for attempt in range(max_repairs + 1):
        try:
            text, cost = invoke_claude(prompt, model, timeout)
            total += cost or 0
            cand = extract_json(text)
            if isinstance(cand, dict) and ("links" in cand or "decisionSequence" in cand):
                obj = cand
                break
        except RuntimeError as exc:
            print(f"[graph-review] {run_id}: call failed ({str(exc)[:120]}) — retrying", flush=True)
        if attempt < max_repairs:
            print(f"[graph-review-retry {attempt + 1}/{max_repairs}] {run_id}: no usable output", flush=True)
    if obj is None:
        print(f"[graph-review] {run_id}: no usable output after retries — links/sequence left as-is "
              f"(cost ${total:.2f})", flush=True)
        return total
    for note in apply_graph_review(world_model, obj):
        print(f"[graph-review] {run_id}: {note}", flush=True)
    return total


def recover_flow(run_dir, data_dir, model, bundle, world_model, timeout, max_repairs):
    """Dedicated flow-only generation, used when Pass 1 produced no usable flow (the
    model sometimes returns the world model without a valid `flow`). Writes
    flow-llm.json and returns the processed flow on success, else None. Cheap: one
    small call + an optional repair, so the Flow tab is never silently empty."""
    run_id = os.path.basename(run_dir)
    flow_rules = open(FLOW_RULES_FILE, encoding="utf-8").read() if os.path.exists(FLOW_RULES_FILE) else ""
    prompt = _bundle_block(bundle) + FLOW_INSTRUCTIONS.format(
        run_id=run_id, flow_rules=flow_rules,
        world_model=json.dumps(_review_view(world_model), ensure_ascii=False)[:REPAIR_PREVIOUS_CAP])
    print(f"[flow] {run_id}: running a dedicated flow pass to recover the flow chart…", flush=True)
    text, _ = invoke_claude(prompt, model, timeout)
    attempt = 0
    while True:
        obj = extract_json(text)
        flow, reason = process_flow(obj if isinstance(obj, dict) else None)
        if flow:
            write_json(os.path.join(data_dir, "flow-llm.json"), flow)
            print(f"[ok] {run_id}: flow recovered ({len(flow['elements'])} nodes) → flow-llm.json", flush=True)
            return flow
        if attempt >= max_repairs:
            write_json(os.path.join(data_dir, "flow-llm.invalid.json"),
                       obj if isinstance(obj, dict) else {"raw": str(text)[:8000]})
            print(f"[warn] {run_id}: flow still unusable after {max_repairs} repairs ({reason}); "
                  f"Flow tab stays empty. See {data_dir}/flow-llm.invalid.json", flush=True)
            return None
        attempt += 1
        print(f"[flow-repair {attempt}/{max_repairs}] {run_id}: {reason}", flush=True)
        previous = (json.dumps(obj, ensure_ascii=False) if isinstance(obj, dict) else (text or ""))[:REPAIR_PREVIOUS_CAP]
        text, _ = invoke_claude(FLOW_REPAIR_INSTRUCTIONS.format(reason=reason, previous=previous), model, timeout)


# --- fan-out Pass 1: generate the world model in parallel sections, then synthesize ---
# The monolithic Pass 1 decodes the whole ~9k-token world model serially. Fan-out
# splits it into independent section-calls that run CONCURRENTLY (wall-clock = the
# slowest section, not the sum), then a small synthesis call fills the cross-referenced
# summary (narrative/crux/cruxEvidence). Id prefixes partition cleanly (H/E/D/AS/F/I),
# so there are no id collisions to reconcile. Quality is preserved or improved: each
# call gives full attention to one facet. Cost rises (the bundle is re-sent per call).

_SECTION_PREFACE = (
    "You are reconstructing PART of a finished research run's world model, headless "
    "with NO TOOLS. Work only from the EVIDENCE BUNDLE. Ground every claim in a real "
    "artifact path from the bundle's file list, or a transcript itemId (L<n>) from the "
    "digest; never invent paths or numbers. Output ONLY the JSON described — no prose, "
    "no markdown fence.\n\nRUN_ID: {run_id}\n\n"
)

_TASK_HYP = """Reconstruct the run's HYPOTHESES and EXPERIMENTS. Output ONLY:
{"hypotheses":[{"id":"H1","statement":"...","status":"supported|uncertain|refuted|alive|dead","affects":[],"basedOn":["<idea.yaml/planning.md path it derives from>"],"evidence":[{"type":"artifact|transcript_item","path":"<real file>","itemId":"L<n> or null","note":"..."}],"updated_at":"ISO"}],
 "experiments":[{"id":"E1","mode":"empirical_experiment|computational_analysis|formal_derivation|literature_synthesis|qualitative_analysis|simulation|observation|other","name":"<what this investigation IS, in the run's own terms>","design":"<domain-neutral: what was varied/examined/derived, at what scope>","hypothesis":"H1,H2 or ''","status":"done|failed|running","result":"...","ranBy":"<pipeline stage that ran it, e.g. experiment_runner — provenance, optional>","affects":["<files this investigation produced, e.g. results/analysis/summary.json>"],"basedOn":["<inputs/datasets/sources/assumptions it consumed>"],"ts":"ISO"}]}
Decompose hypotheses from .neurico/idea.yaml + planning.md (include the alternative explanations the plan raises). Back each status with the actual numbers in results/.
EXPERIMENTS are domain-general INVESTIGATIONS — the actual things the run DID to test its questions, NOT the pipeline's agent stages. Emit ONE experiment per distinct investigation the run actually performed: a benchmark/eval, a comparison or ablation arm, an interpretability analysis (e.g. activation patching), a formal derivation/proof, a literature synthesis, a qualitative coding, a simulation. NEVER emit "resource_finder"/"experiment_runner"/"paper_writer" as experiments — those are pipeline roles; record the stage that ran an investigation in `ranBy` (provenance) instead. EVERY experiment MUST set `name` (its identity, REQUIRED), `mode` (REQUIRED), `status`, and (when 'done') a concrete `result` with the numbers/outcome — never a bare {id} stub and never omit name/mode. Example: {"id":"E1","mode":"empirical_experiment","name":"GSM8K grounding eval (unguided vs guided)","design":"40 prompts, 3 models, pairwise win-rate","hypothesis":"H2","status":"done","result":"guided wins 79%","ranBy":"experiment_runner","affects":["results/gsm8k.json"],"basedOn":["datasets/gsm8k"],"ts":"ISO"}. `affects` = files it produced ([] for hypotheses); `basedOn` = inputs it consumed. Use ONLY id prefixes H and E. Every hypothesis needs >=1 evidence entry citing a real path."""

# v3 (6-18): bottom-up decision extraction, but RUBRIC-TARGETED at layers and
# the prose where each layer's trace lives — replacing the single skim pass that starved
# interpretation/hypothesis. Phrased DOMAIN-NEUTRAL so it generalizes across every NeuriCo
# domain (eval, interpretability, qualitative). Each rubric demands a verbatim `anchor`
# (Docent-style grounding): no textual trace, no decision.
LAYER_RUBRICS = {
    "hypothesis": {
        "label": "HYPOTHESIS",
        "sources": ".neurico/idea.yaml and planning.md",
        "focus": ("how the run chose WHAT to test \u2014 how each hypothesis or research question was "
                  "operationalized into something concrete and testable, how the scope of a claim was "
                  "set, and which alternative explanations it pursued versus set aside."),
    },
    "experiment_design": {
        "label": "EXPERIMENT-DESIGN",
        "sources": "planning.md, any results/config files, and the methods part of REPORT.md",
        "focus": ("how the experiment was SET UP \u2014 what data / material / subjects were used, what "
                  "conditions or comparisons were run, what was included versus cut from scope. State "
                  "this DOMAIN-NEUTRALLY (what was compared, on what, at what scope); do NOT assume "
                  "benchmarks, sample sizes, or statistics \u2014 a run may be qualitative or interpretability."),
    },
    "interpretation": {
        "label": "INTERPRETATION",
        "sources": "REPORT.md and paper_draft/sections/discussion*, conclusion*, results*",
        "focus": ("how the run READ its RESULTS \u2014 how each result was framed, what claim was drawn "
                  "from it, what caveat or limitation was attached, whether an effect was called "
                  "meaningful / suggestive / definitive, whether to report a result versus flag it as a "
                  "problem, or whether something counts as a real finding. These forks live in the "
                  "DISCUSSION / CONCLUSION / LIMITATIONS prose \u2014 read it line by line."),
    },
}

# The fixed JSON shape every layer rubric emits (single-brace literal; __LAYER__ is
# substituted per layer, brace-safe via .replace).
_LAYER_DEC_SCHEMA = ('{"decisions":[{"id":"D1","finding":"<an F-id from the FINDINGS list, or '
    "'global'>" '","layer":"__LAYER__","question":"a self-contained question naming the fork",'
    '"options":[{"text":"the chosen reading / approach","status":"chosen","source":"artifact",'
    '"path":"<source file>"},{"text":"a realistic alternative it passed over","status":"alternative",'
    '"source":"inferred"}],"chosen":"...","statedRationale":"... or null","inferredRationale":'
    '"... or null","by":"agent","shouldEngage":true,"shouldEngageReason":"scope_choice|validity_risk|'
    'cost_risk|human_preference|irreversible_action|routine_no","evidence":[{"type":"artifact",'
    '"path":"<source file>","itemId":null,"note":"...","anchor":"<SHORT substring copied EXACTLY '
    'from the source prose, <=120 chars, that states or directly evidences this fork>"}],'
    '"relatedErrors":[],"ts":"ISO"}]}')


def _layer_dec_task(layer):
    spec = LAYER_RUBRICS[layer]
    return (
        f"Reconstruct the run's {spec['label']} DECISIONS \u2014 {spec['focus']}\n"
        f"Read primarily: {spec['sources']}.\n"
        f"Output ONLY: {_LAYER_DEC_SCHEMA.replace('__LAYER__', layer)}\n"
        f'Every entry is a real FORK (a judgment a reader could reasonably have made differently) '
        f'and MUST use layer="{layer}".\n'
        "GROUNDING (hard rule): each decision MUST carry an `anchor` in its evidence \u2014 a substring "
        "copied CHARACTER-FOR-CHARACTER from one of the source files that states or directly evidences "
        "the fork. If you cannot quote a phrase that shows the fork, DO NOT emit it \u2014 never infer a "
        "fork with no textual trace. Tag `finding` = the F-id this fork most directly concerns, or "
        '"global". Do NOT assign importance (the Pass-2 reviewer ranks decisions). statedRationale is '
        "null when the run gave none \u2014 do not fabricate. Be thorough: the discussion/conclusion "
        "prose usually holds many such forks. Use ONLY id prefix D (numbering is provisional)."
    )

_TASK_FINDINGS = """Reconstruct the run's FINDINGS — the SPINE of the world model. Output ONLY:
{"findings":[{"id":"F1","text":"the atomic learning, WITH its number","insight":"the implication / so-what, or null","kind":"result|dead_end|note","category":null,"affects":[],"basedOn":["<results/artifact files this finding is read from>"],"evidence":[{"type":"artifact|transcript_item","path":"<real file>","itemId":"L<n> or null","note":"..."}],"links":[{"relation":"supports|refutes|produced_by","target":"<H-id or E-id>","basis":"explicit|inferred","rationale":"..."}],"ts":"ISO"}]}
Findings are atomic learnings — one per distinct result, dead-end, or note (include mismatch findings: claim vs stats vs artifacts). A finding is gradeable: include weak/unsupported results as kind:note|dead_end — "should this even count as a finding?" is exactly what review wants surfaced. Set `insight` to the implication a paper's discussion would claim, or null when the finding carries no claim beyond the raw number. Link each finding to the hypothesis it supports/refutes and to the investigation (experiment) that produced it. CRITICAL for `produced_by`: target the specific INVESTIGATION (experiment E-id) whose `name`/`result` actually contains this finding's outcome/numbers — match by task/topic (a GSM8K finding → the GSM8K eval, a patching finding → the patching analysis); check each experiment's `name` and `result` before linking, do not guess the E-id. NEVER target an input-gathering or write-up stage. Use ONLY id prefix F. Every finding needs >=1 evidence citing a real path. Do NOT emit incidents — failures are modeled as interpretation-layer decisions in the decisions pass (the Errors view is dormant in v3)."""

def _section_prompt(run_id, task, rules, bundle):
    # Bundle FIRST (shared, cacheable prefix), then the section-specific instructions.
    return (_bundle_block(bundle)
            + _SECTION_PREFACE.format(run_id=run_id) + task + "\n\n"
            + (f"===== RELEVANT RULES =====\n{rules}\n" if rules else ""))


# One focused call PER source file reliably surfaces far more coding decisions than
# a single "read all the code" pass, which skims. Each call sees the whole (cached)
# bundle but is told to mine exactly one file. Ids are provisional — reassigned on merge.
_TASK_CODE_DEC = """Extract EVERY implementation/coding decision embodied in this ONE source file: {path}
Each decision belongs to a FINDING (listed after this task) or to "global", and is almost always layer:"method". Output ONLY: {{"decisions":[{{"id":"D1","finding":"<an F-id from the FINDINGS list, or 'global'>","layer":"method|experiment_design","question":"a self-contained Which/What/Should…? about a coding choice","options":[{{"text":"the chosen value/approach, verbatim from the code","status":"chosen","source":"artifact","path":"{path}"}},{{"text":"a realistic alternative it passed over","status":"alternative","source":"inferred"}}],"chosen":"...","statedRationale":"a code comment/docstring that justifies it, or null","inferredRationale":"your read of why, or null","by":"agent","shouldEngage":false,"shouldEngageReason":"routine_no|validity_risk|scope_choice|cost_risk|human_preference|irreversible_action","evidence":[{{"type":"artifact","path":"{path}","itemId":null,"note":"what in the file shows this","anchor":"a SHORT substring copied EXACTLY from {path} (the precise line/call/assignment this decision is about, <=120 chars, copied character-for-character so it can be string-matched in the file) — e.g. \\"most_common(5)\\" or \\"figsize=(10, 6)\\""}}],"relatedErrors":[],"ts":"ISO"}}]}}
A coding decision is any fork where a different reasonable implementation would change the result, its validity, or reproducibility: library/algorithm choice, feature representation, hyperparameter VALUES (temperature, max_tokens, n, k, learning rate), thresholds, the statistical test, sampling/seed/determinism, normalization, data-cleaning/filtering rules, error-handling/fallback, and prompt/rubric TEXT for any model call in the file. layer is "method" for these, or "experiment_design" for a sampling/seed/condition choice. TAG `finding` = the F-id this code most directly serves (the result it computes or produces); use "global" only when it underpins the whole run. IMPORTANT: if a coding choice serves no finding AND is not a genuine global fork, OMIT it — do not pad. Read the file line by line; several decisions per file is expected. Do NOT assign importance — the Pass-2 PI reviewer ranks decisions by paper-reading; your job is COMPLETENESS. Every decision MUST cite {path} as artifact evidence. Use ONLY id prefix D (numbering is provisional)."""


def _findings_block(findings):
    """The FINDINGS list a decision pass tags against. Concatenated (not .format'd) so
    finding text containing braces is safe."""
    rows = []
    for f in findings or []:
        if isinstance(f, dict) and f.get("id"):
            rows.append(f'- {f["id"]}: {(f.get("text") or "")[:200]}')
    if not rows:
        return ('===== FINDINGS (none reconstructed) =====\n'
                'No findings were recovered — tag every decision finding:"global".')
    return ("===== FINDINGS — tag each decision with one of these F-ids, or \"global\" =====\n"
            + "\n".join(rows))


def _layer_decisions_prompt(run_id, findings, layer, rules, bundle):
    return (_bundle_block(bundle)
            + _SECTION_PREFACE.format(run_id=run_id) + _layer_dec_task(layer) + "\n\n"
            + _findings_block(findings) + "\n\n"
            + (f"===== RELEVANT RULES =====\n{rules}\n" if rules else ""))


def _code_section_prompt(run_id, path, findings, rules, bundle):
    return (_bundle_block(bundle)
            + _SECTION_PREFACE.format(run_id=run_id)
            + _TASK_CODE_DEC.format(path=path) + "\n\n"
            + _findings_block(findings) + "\n\n"
            + (f"===== RELEVANT RULES =====\n{rules}\n" if rules else ""))


def _merge_decisions(*decision_lists):
    """Concatenate decision lists, drop near-duplicate questions (first wins, so the
    main pass outranks per-file passes), and reassign stable D-ids in order."""
    seen, out = set(), []
    for lst in decision_lists:
        for d in lst or []:
            if not isinstance(d, dict):
                continue
            key = re.sub(r"[^a-z0-9]+", "", (d.get("question") or "").lower())[:80]
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            out.append(d)
    for i, d in enumerate(out, 1):
        d["id"] = f"D{i}"
    return out


def _synthesis_prompt(run_id, h_list, e_list, d_list, f_list, bundle):
    task = (
        "Synthesize the run's TOP-LEVEL summary from its already-reconstructed parts "
        "(listed below). Output ONLY:\n"
        '{"narrative":"3-6 sentences on where the run stands",'
        '"headline":"ONE sentence naming the single most important result, with its key number",'
        '"keyFacts":["4-6 short at-a-glance scope facts, e.g. \'3 pre-registered experiments\', \'40 prompts\', \'3 models compared\'"],'
        '"methodology":["4-6 short bullets: dataset(s), each experiment\'s design, models/judges, key controls — one clause each, paper-methods style"],'
        '"current_best":"champion result WITH numbers",'
        '"crux":"the single most trust-relevant open issue",'
        '"cruxEvidence":[{"type":"finding|decision","id":"<a real id from the lists>"}],'
        '"entityLinks":[{"source":"F1","relation":"supports|refutes|produced_by|motivated_by|depends_on","target":"H1","basis":"explicit|inferred","rationale":"why this relationship is warranted"}],'
        '"open_questions":["..."],'
        '"future_work":["3-6 short limitation / next-step bullets"],'
        '"panel_layout":["crux","current_best","narrative","hypotheses","leaderboard","findings","decisions","open_questions","experiments"],'
        '"sections":{"leaderboard":{"title":"...","kind":"table","data":{"columns":["..."],"rows":[["..."]]}}}}\n'
        "cruxEvidence and every entityLinks source/target MUST reference ids that appear "
        "in the lists below (findings F*, decisions D*, hypotheses H*, experiments E*). Use "
        "canonical link directions only: finding supports/refutes hypothesis; finding "
        "produced_by experiment; decision or experiment motivated_by a prior entity; "
        "decision/experiment/finding depends_on another entity. Do not emit reverse "
        "duplicates. current_best and headline must include real numbers from the run's "
        "results. sections is optional."
    )
    return (
        _bundle_block(bundle)
        + "You are reconstructing the summary of a research run, headless with NO TOOLS. "
        "Ground everything in the EVIDENCE BUNDLE and the parts below; never invent "
        "numbers. Output ONLY the JSON — no prose, no fence.\n\n"
        f"RUN_ID: {run_id}\n\n{task}\n\n"
        f"HYPOTHESES: {json.dumps(h_list, ensure_ascii=False)}\n"
        f"EXPERIMENTS: {json.dumps(e_list, ensure_ascii=False)}\n"
        f"FINDINGS: {json.dumps(f_list, ensure_ascii=False)}\n"
        f"DECISIONS: {json.dumps(d_list, ensure_ascii=False)}\n"
    )


# --- Front-page selection: ~3 decisions for a QUICK, abstract-only annotation pass. A
# separate, deliberately ABSTRACT-ONLY call (it sees only the abstract + the decision list,
# NOT the full paper) so its picks are things a reviewer who read only the abstract could
# actually judge. The goal is a BROAD READ on how well the run was done — not a deep audit.
# Fires in parallel with synthesis (right after decisions exist), so it adds ~0 wall-clock.
FRONTPAGE_INSTRUCTIONS = """\
A reviewer will read ONLY the ABSTRACT below, then inspect a SMALL set of decisions to get a
BROAD READ on how well this run was done — for quick annotation. From the DECISIONS list,
choose ABOUT 3 (up to 5) decisions that BOTH:
  (1) a reviewer can SOUNDLY JUDGE FROM THE ABSTRACT ALONE — but FAVOR experiment-design forks:
      what was tested, on which dataset / benchmark / baseline, under what conditions, at what
      scope / sample size, what was run vs cut. Pick the framing / interpretation forks only
      when they are clearly load-bearing — do NOT fill the slots with framing or paper-writing
      choices. Still SKIP deep method / implementation / statistical choices that need the
      methods or results to evaluate (a reviewer can't judge those from the abstract); AND
  (2) together give the broadest read on the run's quality — span its key dimensions, weighted
      toward experiment design (was the experiment well chosen and scoped? sound baselines /
      conditions? reasonable sample size?), then whether the interpretation was honest, ideally
      each from a DIFFERENT finding rather than several about the same one.
Order them most-telling first.

Output ONLY this JSON (no prose, no markdown fence): {{"frontPageDecisions":["D..","D.."]}}
Use ONLY ids from the DECISIONS list; never invent ids; pick fewer if fewer qualify.

RUN_ID: {run_id}

===== ABSTRACT =====
{abstract}

===== DECISIONS (id · finding · layer · question · chose) =====
{decisions}
"""


def _frontpage_prompt(run_id, abstract, decisions):
    rows = "\n".join(
        f"- {d.get('id')} · {d.get('finding') or 'global'} · {d.get('layer') or '?'} · "
        f"{(d.get('question') or '')[:150]} · chose: {(d.get('chosen') or '')[:110]}"
        for d in decisions)
    return FRONTPAGE_INSTRUCTIONS.format(run_id=run_id, abstract=(abstract or "(no abstract available)")[:6000],
                                         decisions=rows or "(none)")


def select_front_page(obj, valid_ids):
    """Keep the model's valid, unique picks (≤5, in order). Returns a possibly-short list;
    an empty list is fine — the UI falls back to top decisions by importance at serve time."""
    seen, out = set(), []
    for did in ((obj or {}).get("frontPageDecisions") or []):
        if isinstance(did, str) and did in valid_ids and did not in seen:
            seen.add(did)
            out.append(did)
        if len(out) >= 5:
            break
    return out


def apply_entity_links(world_model, links):
    """Attach synthesis-produced cross-entity links after fan-out ids are final."""
    by_id = {}
    for key in _WM_ID_ARRAYS:
        for item in world_model.get(key) or []:
            if isinstance(item, dict) and item.get("id"):
                by_id[item["id"]] = item
    for link in links or []:
        if not isinstance(link, dict):
            continue
        source = by_id.get(link.get("source"))
        if source is None:
            continue
        payload = {key: link.get(key) for key in ("relation", "target", "basis", "rationale")}
        source.setdefault("links", []).append(payload)


def _warm_cache(bundle, model, timeout):
    """Prime Anthropic's prompt cache with the (large, shared) bundle PREFIX before the
    concurrent section calls fire — otherwise the parallel calls all race to create the
    cache at once and none benefits. After this, each section reads the bundle from
    cache. Quality-neutral (server-side cache only); best-effort. Returns its cost."""
    try:
        text, cost = invoke_claude(_bundle_block(bundle) + "Reply with exactly: READY",
                                   model, min(timeout, 180))
        return cost or 0
    except Exception:  # noqa: BLE001
        return 0


def _invoke_section(label, prompt, model, timeout, max_repairs):
    """Call the model for one section; retry on a non-JSON reply. Returns (dict, cost)."""
    text, cost = invoke_claude(prompt, model, timeout)
    total = cost or 0
    obj = extract_json(text)
    tries = 0
    while not isinstance(obj, dict) and tries < max_repairs:
        tries += 1
        print(f"[fanout] {label}: non-JSON reply — retrying ({tries}/{max_repairs})", flush=True)
        text, cost = invoke_claude(prompt, model, timeout)
        total += cost or 0
        obj = extract_json(text)
    return (obj if isinstance(obj, dict) else {}), total


def _run_sections(run_id, sections, model, timeout, max_repairs):
    """Run a batch of section prompts concurrently. Returns ({label: obj}, total_cost)."""
    out, total = {}, 0.0
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(sections), 8)) as ex:
        futures = {ex.submit(_invoke_section, label, prompt, model, timeout, max_repairs): label
                   for label, prompt in sections.items()}
        for fut in concurrent.futures.as_completed(futures):
            label = futures[fut]
            obj, cost = fut.result()
            total += cost
            out[label] = obj
            print(f"[fanout] {run_id}: section '{label}' done", flush=True)
    return out, total


def _brief(items, *keys):
    out = []
    for it in items or []:
        if isinstance(it, dict):
            entry = {"id": it.get("id")}
            for k in keys:
                if it.get(k):
                    entry[k] = it.get(k)
            out.append(entry)
    return out


CODE_SWEEP_MAX_FILES = 16  # backstop so a sprawling repo can't fan out unboundedly

def _normalize_for_anchor(text):
    """Lowercase + keep only [a-z0-9] so a verbatim prose quote still matches its source
    despite LaTeX markup / whitespace differences (the .tex files carry \\emph{}, etc.)."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def audit_decision_anchors(world_model, run_dir):
    """Docent-style grounding audit (SOFT): for each decision-evidence `anchor`, check it
    resolves (normalized substring) in its cited file. Flags unresolved ones with
    anchorResolved=False and returns (checked, resolved) so the pipeline logs the rate. Does
    NOT drop — we measure the hallucination surface first, then decide whether to hard-drop."""
    cache, checked, resolved = {}, 0, 0
    for d in world_model.get("decisions") or []:
        for ev in (d.get("evidence") or []):
            anchor, path = ev.get("anchor"), ev.get("path")
            if not anchor or not path:
                continue
            checked += 1
            if path not in cache:
                try:
                    with open(os.path.join(run_dir, path), encoding="utf-8", errors="replace") as fh:
                        cache[path] = _normalize_for_anchor(fh.read())
                except OSError:
                    cache[path] = ""
            norm = _normalize_for_anchor(anchor)
            if norm and norm in cache[path]:
                resolved += 1
            else:
                ev["anchorResolved"] = False
    return checked, resolved


def run_pass1_fanout(run_id, run_dir, data_dir, wm_path, bundle, model, max_repairs, timeout, inventory=None):
    """Parallel-section variant of Pass 1. Same output contract as run_pass1:
    (world_model, flow) on success, or (None, None) after quarantine.

    v3: findings are the spine, so the fan-out runs in TWO phases. Phase A builds the
    backbone (hypotheses+experiments, findings, flow) in parallel. Phase B then builds
    the decisions GIVEN those findings — both the run-wide pass and the per-file code
    sweep are told to tag every decision with `finding` (an F-id or "global") and
    `layer`. Decisions from the two sources are merged."""
    decision_rules = open(DECISION_RULES_FILE, encoding="utf-8").read() if os.path.exists(DECISION_RULES_FILE) else ""

    total_cost = 0.0
    print(f"[fanout] {run_id}: warming the prompt cache with the shared bundle…", flush=True)
    total_cost += _warm_cache(bundle, model, timeout)

    # --- Phase A: the backbone (hyp+exp, findings) ---
    # The Flow tab is the F/H/E entity graph, built deterministically during graph review.
    # Pass 1 therefore does NOT generate a process flow — otherwise any build that doesn't
    # reach graph review (interrupted/failed) would leave a misleading "old" process flow
    # on disk. With graph review off (--no-graph-review), the flow safety net in
    # reconstruct() recovers a process flow instead.
    phase_a = {
        "hyp+exp": _section_prompt(run_id, _TASK_HYP, "", bundle),
        "findings": _section_prompt(run_id, _TASK_FINDINGS, "", bundle),
    }
    print(f"[fanout] {run_id}: phase A — backbone ({len(phase_a)} sections)…", flush=True)
    results_a, cost_a = _run_sections(run_id, phase_a, model, timeout, max_repairs)
    total_cost += cost_a
    hyp = results_a.get("hyp+exp", {})
    fin = results_a.get("findings", {})
    flow, flow_reason = None, "Flow tab is the F/H/E entity graph, built in graph review"
    findings = fin.get("findings", []) if isinstance(fin, dict) else []

    # --- Phase B: decisions, tagged against the findings just built ---
    # v3 (6-18): three RUBRIC-TARGETED layer passes (hypothesis / experiment_design /
    # interpretation), each reading the prose where its forks leave a trace, plus the
    # per-file code sweep (method). Replaces the single skim pass that starved interp/hyp.
    code_files = (inventory or {}).get("code_read", [])[:CODE_SWEEP_MAX_FILES]
    rubric_layers = ("hypothesis", "experiment_design", "interpretation")
    phase_b = {f"dec:{layer}": _layer_decisions_prompt(run_id, findings, layer, decision_rules, bundle)
               for layer in rubric_layers}
    for rel in code_files:
        phase_b[f"code:{rel}"] = _code_section_prompt(run_id, rel, findings, decision_rules, bundle)
    print(f"[fanout] {run_id}: phase B — 3 layer rubrics + {len(code_files)} code-sweep files, "
          f"tagged against {len(findings)} findings…", flush=True)
    results_b, cost_b = _run_sections(run_id, phase_b, model, timeout, max_repairs)
    total_cost += cost_b

    layer_decisions = []
    for layer in rubric_layers:
        layer_decisions.extend((results_b.get(f"dec:{layer}") or {}).get("decisions", []))
    code_decisions = []
    for rel in code_files:
        code_decisions.extend((results_b.get(f"code:{rel}") or {}).get("decisions", []))
    merged_decisions = _merge_decisions(layer_decisions, code_decisions)
    print(f"[fanout] {run_id}: {len(layer_decisions)} layer-rubric + "
          f"{len(code_decisions)} code-sweep → {len(merged_decisions)} decisions after merge", flush=True)
    dec = {"decisions": merged_decisions}

    # Synthesis + front-page selection fire IN PARALLEL (both need only the now-final
    # decisions): synthesis sees the full bundle; the front-page call is abstract-only (the
    # paper's own abstract + ALL decisions) and picks the ~3 a reviewer could judge from the
    # abstract — for a quick, broad read on run quality.
    abstract_text = read_capped(os.path.join(run_dir, "paper_draft", "sections", "abstract.tex"), 8000) or ""
    fp_candidates = [d for d in merged_decisions if isinstance(d, dict) and d.get("id")]
    print(f"[fanout] {run_id}: synthesizing narrative / crux + front-page selection "
          f"(over {len(fp_candidates)} decisions)…", flush=True)
    batch = {"synthesis": _synthesis_prompt(
        run_id,
        _brief(hyp.get("hypotheses"), "statement", "status"),
        _brief(hyp.get("experiments"), "agent", "rationale", "result", "status"),
        _brief(dec.get("decisions"), "question", "chosen", "finding", "layer"),
        _brief(findings, "text", "insight", "kind"),
        bundle)}
    if abstract_text and fp_candidates:
        batch["frontpage"] = _frontpage_prompt(run_id, abstract_text, fp_candidates)
    results_s, scost = _run_sections(run_id, batch, model, timeout, max_repairs)
    total_cost += scost
    synth = results_s.get("synthesis", {})
    front_page = select_front_page(results_s.get("frontpage"), {d.get("id") for d in fp_candidates})
    print(f"[fanout] {run_id}: front-page decisions = {front_page or '(none — UI will fall back)'}", flush=True)

    world_model = {
        "schemaVersion": 3, "runId": run_id, "reconstructed": True,
        "updated_at": now_iso(),
        "narrative": synth.get("narrative", ""), "current_best": synth.get("current_best", ""),
        "headline": synth.get("headline", ""),
        # The front-page abstract is the paper's OWN abstract (server reads sections/abstract.tex
        # at serve time); the reconstruction no longer generates one.
        "keyFacts": synth.get("keyFacts", []), "methodology": synth.get("methodology", []),
        "future_work": synth.get("future_work", []),
        "crux": synth.get("crux", ""), "cruxEvidence": synth.get("cruxEvidence", []),
        "hypotheses": hyp.get("hypotheses", []), "experiments": hyp.get("experiments", []),
        "findings": findings, "open_questions": synth.get("open_questions", []),
        "decisions": dec.get("decisions", []),
        # ~3 decisions a reviewer can judge from the abstract alone — a quick, broad read on
        # run quality, chosen by the abstract-only front-page call.
        "frontPageDecisions": front_page,
        # v3: assessments/incidents are dormant — kept as empty arrays for back-compat.
        "assessments": [], "incidents": [],
        "panel_layout": synth.get("panel_layout", []), "sections": synth.get("sections", {}),
    }
    apply_entity_links(world_model, synth.get("entityLinks", []))

    checked, resolved = audit_decision_anchors(world_model, run_dir)
    if checked:
        print(f"[fanout] {run_id}: anchor grounding — {resolved}/{checked} decision anchors "
              f"resolve ({100 * resolved // checked}%)", flush=True)

    # Validate the assembled model, patch-repairing only the broken entities (same as
    # the monolithic path), so fan-out meets the identical quality bar.
    attempt = 0
    while True:
        for fix in normalize_world_model(world_model):
            print(f"[normalize] {run_id}: {fix}", flush=True)
        stamp(world_model, model)
        write_json(os.path.join(data_dir, "world_model.candidate.json"), world_model)
        report = validate(world_model, run_dir=run_dir, data_dir=data_dir)
        print(f"[validate] {run_id}: {len(report.errors)} errors, {len(report.warnings)} warnings "
              f"(fanout cost so far ${total_cost:.2f})", flush=True)
        if report.ok():
            write_json(wm_path, world_model)
            if flow:
                write_json(os.path.join(data_dir, "flow-llm.json"), flow)
                print(f"[ok] {run_id}: world_model.json + flow ({len(flow['elements'])} nodes) written "
                      f"— fanout cost ${total_cost:.2f} ({model})", flush=True)
            else:
                print(f"[ok] {run_id}: world_model.json written ({flow_reason}) "
                      f"— fanout cost ${total_cost:.2f} ({model})", flush=True)
            for warning in report.warnings:
                print(f"    warn {warning['code']}: {warning['msg']}", flush=True)
            return world_model, flow
        if attempt >= max_repairs:
            quarantine(run_id, data_dir, report.errors, world_model, total_cost)
            return None, None
        attempt += 1
        print(f"[repair {attempt}/{max_repairs}] {run_id}: {len(report.errors)} validation errors (patch)", flush=True)
        errors = "\n".join(f"- {e['code']}: {e['msg']}" for e in report.errors)
        text, cost = invoke_claude(REPAIR_INSTRUCTIONS.format(
            errors=errors, previous=json.dumps(world_model, ensure_ascii=False)[:REPAIR_PREVIOUS_CAP]),
            model, timeout)
        total_cost += cost or 0
        merged = apply_patch(world_model, extract_json(text))
        if merged is not None:
            world_model = merged


def run_pass1(run_id, run_dir, data_dir, wm_path, prompt, model, max_repairs, timeout):
    """Generate + validate + repair the world model and flow. Returns
    (world_model, flow) on success, or (None, None) after quarantine."""
    total_cost = 0.0
    last_flow = None
    last_flow_raw = None       # the model's most recent (rejected) "flow", for debugging
    last_flow_reason = "model output had no 'flow' key"
    text, cost = invoke_claude(prompt, model, timeout)
    total_cost += cost or 0
    obj = extract_json(text)
    attempt = 0

    # Bootstrap: get a parseable object. A non-JSON reply has nothing to patch, so
    # re-run the full original prompt rather than asking for a patch.
    while not isinstance(obj, dict):
        if attempt >= max_repairs:
            quarantine(run_id, data_dir, [{"code": "no_json", "msg": "model returned no JSON object"}], text, total_cost)
            return None, None
        attempt += 1
        print(f"[repair {attempt}/{max_repairs}] {run_id}: output was not a JSON object — regenerating", flush=True)
        text, cost = invoke_claude(prompt, model, timeout)
        total_cost += cost or 0
        obj = extract_json(text)

    world_model = obj.get("world_model") if isinstance(obj.get("world_model"), dict) else obj
    flow, flow_reason = process_flow(obj.get("flow"))
    if flow:
        last_flow = flow
    elif obj.get("flow") is not None:
        last_flow_raw, last_flow_reason = obj.get("flow"), flow_reason
    else:
        last_flow_reason = flow_reason

    # Validate, and on failure apply a MINIMAL PATCH (regenerates only the broken
    # entities, not the whole ~9k-token model) until valid or out of repairs.
    while True:
        for fix in normalize_world_model(world_model):
            print(f"[normalize] {run_id}: {fix}", flush=True)
        stamp(world_model, model)
        write_json(os.path.join(data_dir, "world_model.candidate.json"), world_model)
        report = validate(world_model, run_dir=run_dir, data_dir=data_dir)
        print(f"[validate] {run_id}: {len(report.errors)} errors, {len(report.warnings)} warnings "
              f"(cost so far ${total_cost:.2f})", flush=True)

        if report.ok():
            write_json(wm_path, world_model)
            if last_flow:
                write_json(os.path.join(data_dir, "flow-llm.json"), last_flow)
                print(f"[ok] {run_id}: world_model.json + flow ({len(last_flow['elements'])} nodes) written "
                      f"— cost ${total_cost:.2f} ({model})", flush=True)
            else:
                # Save the rejected flow for inspection and log WHY; reconstruct()
                # will run a dedicated flow pass to recover it (never a silent blank).
                if last_flow_raw is not None:
                    write_json(os.path.join(data_dir, "flow-llm.invalid.json"), {"flow": last_flow_raw})
                print(f"[ok] {run_id}: world_model.json written, but no usable flow yet "
                      f"({last_flow_reason}) — will run a dedicated flow pass "
                      f"— cost ${total_cost:.2f} ({model})", flush=True)
            for warning in report.warnings:
                print(f"    warn {warning['code']}: {warning['msg']}", flush=True)
            return world_model, last_flow

        if attempt >= max_repairs:
            quarantine(run_id, data_dir, report.errors, world_model, total_cost)
            return None, None

        attempt += 1
        print(f"[repair {attempt}/{max_repairs}] {run_id}: {len(report.errors)} validation errors (patch)", flush=True)
        errors = "\n".join(f"- {e['code']}: {e['msg']}" for e in report.errors)
        text, cost = invoke_claude(REPAIR_INSTRUCTIONS.format(
            errors=errors, previous=json.dumps(world_model, ensure_ascii=False)[:REPAIR_PREVIOUS_CAP]),
            model, timeout)
        total_cost += cost or 0
        merged = apply_patch(world_model, extract_json(text))
        if merged is not None:
            world_model = merged
        # If the patch was unusable, world_model is unchanged → it re-validates with
        # the same errors next loop and (eventually) quarantines. No silent corruption.


def maybe_build_paper_highlights(run_dir, data_dir):
    """Resolve decision paperRef anchors to PDF highlight boxes, if the run has a
    paper. Best-effort: a missing PyMuPDF or a malformed PDF logs and skips — it must
    never fail the reconstruction (the feature degrades to no highlights)."""
    if not os.path.exists(os.path.join(run_dir, "paper_draft", "main.pdf")):
        return
    try:
        from build_paper_highlights import build_paper_highlights
        resolved = build_paper_highlights(run_dir, data_dir)
        print(f"[paper] {os.path.basename(run_dir)}: {resolved} decision(s) anchored to the PDF", flush=True)
    except ImportError:
        print("[paper] skipped — PyMuPDF not installed (pip install pymupdf)", flush=True)
    except Exception as exc:  # noqa: BLE001 — never let highlighting break a build
        print(f"[paper] skipped — {exc}", flush=True)


def _apply_graph_review_and_persist(run_id, run_dir, data_dir, wm_path, model, world_model, timeout, max_repairs):
    """Run the graph+sequence review, heal + validate, and persist if still valid.
    Returns the world_model now on disk (the reviewed one if valid, else the pre-review
    one reloaded). Never leaves an invalid model on disk."""
    review_graph_and_sequence(run_id, model, world_model, timeout, max_repairs)
    for fix in normalize_world_model(world_model):
        print(f"[normalize] {run_id}: {fix}", flush=True)
    report = validate(world_model, run_dir=run_dir, data_dir=data_dir)
    if report.ok():
        write_json(wm_path, world_model)
        print(f"[graph-review] {run_id}: world_model.json updated (F/H/E links + decision order)", flush=True)
        result = world_model
    else:
        print(f"[graph-review] {run_id}: post-review model invalid ({len(report.errors)} errors) — "
              f"reverting to pre-review world_model.json", flush=True)
        try:
            result = json.load(open(wm_path, encoding="utf-8"))
        except (OSError, ValueError):
            result = world_model

    # The Flow tab is the scientific F/H/E graph — rebuild it from the now-canonical model.
    entity_flow, _reason = process_flow(build_entity_flow(result))
    if entity_flow:
        write_json(os.path.join(data_dir, "flow-llm.json"), entity_flow)
        print(f"[graph-review] {run_id}: Flow tab = entity graph "
              f"({len(entity_flow['elements'])} nodes, {len(entity_flow['edges'])} edges)", flush=True)
    return result


def reconstruct(run_dir, repo, model, max_repairs, force, dry_run, timeout,
                review=True, review_only=False, fanout=False,
                graph_review=True, graph_review_only=False):
    run_dir = os.path.abspath(run_dir.rstrip("/"))
    run_id = os.path.basename(run_dir)
    data_dir = os.path.join(repo, "data", "runs", run_id)
    wm_path = os.path.join(data_dir, "world_model.json")
    inv_path = os.path.join(data_dir, "evidence_inventory.json")

    bundle, inventory = build_evidence_bundle(run_dir)

    if dry_run:
        print(f"[dry-run] {run_id}")
        print(f"  scanned {len(inventory['files_present'])} files, "
              f"read {len(inventory['artifacts_read'])} artifacts, bundle ~{len(bundle) // 1000}k chars")
        print(f"  model={model}  repairs<= {max_repairs}  "
              f"pass1={'skip (review-only)' if (review_only or graph_review_only) else ('fanout' if fanout else 'on')}  "
              f"graph-review={'only' if graph_review_only else ('on' if graph_review else 'off')}  "
              f"pass2={'on' if (review and not graph_review_only) else 'off'}")
        return 0

    # --- Graph-review-only: reconcile F/H/E links + decision order over an existing
    # world model, cheaply (one call), without rerunning Pass 1 or Pass 2. ---
    if graph_review_only:
        if not os.path.exists(wm_path):
            print(f"[error] {run_id}: --graph-review-only but no world_model.json exists; build Pass 1 first", flush=True)
            return 1
        try:
            world_model = json.load(open(wm_path, encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[error] {run_id}: could not read existing world_model.json: {exc}", flush=True)
            return 1
        _apply_graph_review_and_persist(run_id, run_dir, data_dir, wm_path, model, world_model, timeout, max_repairs)
        return 0

    # --- Pass 1: world model + flow (reuse a valid existing one if present) ---
    have_valid = False
    if os.path.exists(wm_path) and not force:
        try:
            if validate(json.load(open(wm_path, encoding="utf-8")), run_dir=run_dir, data_dir=data_dir).ok():
                have_valid = True
        except (OSError, ValueError):
            pass

    if review_only or have_valid:
        if not os.path.exists(wm_path):
            print(f"[error] {run_id}: --review-only but no world_model.json exists; run Pass 1 first", flush=True)
            return 1
        try:
            world_model = json.load(open(wm_path, encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[error] {run_id}: could not read existing world_model.json: {exc}", flush=True)
            return 1
        flow = read_flow_llm(data_dir)
        print(f"[skip] {run_id}: reusing existing valid world_model.json (Pass 1)", flush=True)
    else:
        write_json(inv_path, inventory)
        if fanout:
            world_model, flow = run_pass1_fanout(run_id, run_dir, data_dir, wm_path, bundle, model, max_repairs, timeout, inventory)
        else:
            flow_rules = open(FLOW_RULES_FILE, encoding="utf-8").read() if os.path.exists(FLOW_RULES_FILE) else ""
            prompt = _bundle_block(bundle) + HARNESS_INSTRUCTIONS.format(
                run_id=run_id, flow_rules=flow_rules,
                prompt=open(PROMPT_FILE, encoding="utf-8").read())
            world_model, flow = run_pass1(run_id, run_dir, data_dir, wm_path, prompt, model, max_repairs, timeout)
        if world_model is None:
            return 1  # quarantined inside run_pass1

    # --- Flow tab ---
    # With graph-review ON (default), the Flow tab is the F/H/E entity graph, built
    # deterministically from the world model after the review below — so the LLM
    # process-flow is unnecessary. Only when graph-review is OFF do we fall back to the
    # LLM process flow (and its safety-net recovery pass).
    if not graph_review:
        flow_elements = flow.get("elements") if isinstance(flow, dict) else None
        if not flow_elements:
            recovered = recover_flow(run_dir, data_dir, model, bundle, world_model, timeout, max_repairs)
            if recovered:
                flow = recovered

    # --- Graph + sequence review: reconcile the F/H/E relationship graph and order
    # each finding's decisions causally (links produced blind during fan-out). ---
    if graph_review:
        world_model = _apply_graph_review_and_persist(
            run_id, run_dir, data_dir, wm_path, model, world_model, timeout, max_repairs)

    # --- Paper highlights: resolve each decision's paperRef to a box in main.pdf ---
    maybe_build_paper_highlights(run_dir, data_dir)

    # --- Pass 2: adversarial review (per-decision engage re-judgement) ---
    if not review:
        return 0
    # Finding filter: a soft overlay (finding-review.json) marking each finding
    # show_by_default — the UI defaults to the claim-level spine and reveals the rest.
    run_finding_filter(run_dir, data_dir, model, bundle, world_model, timeout, max_repairs)
    return run_review(run_dir, data_dir, model, bundle, world_model, timeout, max_repairs)


def quarantine(run_id, data_dir, errors, candidate, total_cost):
    os.makedirs(data_dir, exist_ok=True)
    if isinstance(candidate, dict):
        write_json(os.path.join(data_dir, "world_model.invalid.json"), candidate)
    else:
        with open(os.path.join(data_dir, "world_model.invalid.txt"), "w", encoding="utf-8") as handle:
            handle.write(str(candidate))
    write_json(os.path.join(data_dir, "validation_report.json"),
               {"runId": run_id, "ok": False, "errors": errors, "at": now_iso()})
    print(f"[QUARANTINE] {run_id}: {len(errors)} unresolved errors after repairs — "
          f"world_model.json NOT written (cost ${total_cost:.2f}). See {data_dir}/world_model.invalid.json", flush=True)
    return 1


def discover_runs(root):
    runs = []
    for name in sorted(os.listdir(root)):
        candidate = os.path.join(root, name)
        if os.path.isdir(candidate) and os.path.exists(os.path.join(candidate, ".neurico", "pipeline_state.json")):
            runs.append(candidate)
    return runs


def main():
    parser = argparse.ArgumentParser(description="Reconstruct world_model.json for a NeuriCo auto-mode run.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-dir", help="a single raw run folder")
    group.add_argument("--all", dest="runs_root", help="reconstruct every run folder under this root")
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="model id/alias (default: sonnet)")
    parser.add_argument("--max-repairs", type=int, default=2,
                        help="repair attempts on invalid output; >1 survives a flaky no-JSON reply")
    parser.add_argument("--timeout", type=int, default=1200, help="per agent call, seconds")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-review", action="store_true",
                        help="skip the Pass-2 adversarial review (errors + decision re-judgement)")
    parser.add_argument("--review-only", action="store_true",
                        help="run only Pass 2 over an existing world_model.json (no Pass-1 regeneration)")
    parser.add_argument("--fanout", action="store_true",
                        help="generate Pass 1 as parallel section calls (faster wall-clock; higher token cost)")
    parser.add_argument("--no-graph-review", action="store_true",
                        help="skip the graph+sequence review (F/H/E link reconciliation + decision ordering)")
    parser.add_argument("--graph-review-only", action="store_true",
                        help="run only the graph+sequence review over an existing world_model.json "
                             "(no Pass-1 regeneration, no Pass-2): cheap way to add links + decision order")
    args = parser.parse_args()

    targets = [args.run_dir] if args.run_dir else discover_runs(args.runs_root)
    if not targets:
        print("no run folders found")
        return 1

    failures = 0
    for run_dir in targets:
        try:
            failures += 1 if reconstruct(run_dir, os.path.abspath(args.repo), args.model,
                                         args.max_repairs, args.force, args.dry_run, args.timeout,
                                         review=not args.no_review, review_only=args.review_only,
                                         fanout=args.fanout,
                                         graph_review=not args.no_graph_review,
                                         graph_review_only=args.graph_review_only) else 0
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"[error] {os.path.basename(run_dir.rstrip('/'))}: {exc}", flush=True)
    if len(targets) > 1:
        print(f"\ndone: {len(targets) - failures}/{len(targets)} runs produced a valid world_model.json")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
