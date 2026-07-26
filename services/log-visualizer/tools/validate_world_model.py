#!/usr/bin/env python3
"""Deterministic validator for a reconstructed world_model.json (v3).

Catches the mechanical errors an LLM cannot be trusted to avoid: hallucinated
file paths, cited transcript item ids that don't exist, missing evidence, bad
enums, unresolved crux links. Two tiers:

  errors    -> block (exit 1). Feed these back to the builder's repair loop.
  warnings  -> surface, do not block (semantic / soft checks).
  infos     -> notable but expected (e.g. a load-bearing choice left unjustified).

No third-party dependencies. If `jsonschema` happens to be installed it is used
as an extra structural pass, but it is not required.

CLI:
  python validate_world_model.py <world_model.json> --run-dir <raw run folder> [--json]

Importable:
  from validate_world_model import validate
  report = validate(world_model_dict, run_dir="...", data_dir="...")
"""

import argparse
import glob
import json
import os
import re
import sys

PHASES = {"planning", "environment", "implementation", "experimentation",
          "analysis", "documentation", "resource_finding"}
HYP_STATUS = {"supported", "uncertain", "refuted", "alive", "dead"}
EXPERIMENT_STATUS = {"done", "failed", "running"}
FINDING_KINDS = {"result", "dead_end", "note"}
INCIDENT_KINDS = {"recovered", "unresolved", "self_reported"}
OPTION_STATUS = {"chosen", "alternative"}
# "transcript" = grounded in the execution trace (a real, observed source, like
# "artifact"); "inferred" = reconstructed by the model, not something the agent
# explicitly weighed. "transcript_item" is accepted as an alias because the model
# tends to mirror the evidence type name.
OPTION_SOURCE = {"artifact", "transcript", "transcript_item", "inferred"}
ENGAGE_REASONS = {"scope_choice", "validity_risk", "cost_risk",
                  "human_preference", "irreversible_action", "routine_no"}
IMPORTANCE = {"low", "medium", "high", "critical"}
# v3: the four layers of a finding's decision chain. `layer` replaces `phase` as the
# primary axis; `phase` survives only as optional legacy metadata.
LAYERS = {"hypothesis", "method", "experiment_design", "interpretation"}
EVIDENCE_TYPES = {"artifact", "transcript_item"}
LINK_RELATIONS = {"supports", "refutes", "produced_by", "motivated_by",
                  "depends_on", "caused", "recovered_by"}
LINK_BASIS = {"explicit", "inferred"}
ENTITY_COLLECTIONS = {
    "hypotheses": "hypothesis",
    "experiments": "experiment",
    "findings": "finding",
    "decisions": "decision",
    "assessments": "assessment",
    "incidents": "incident",
}
LINK_COMPATIBILITY = {
    "supports": ({"finding"}, {"hypothesis"}),
    "refutes": ({"finding"}, {"hypothesis"}),
    "produced_by": ({"finding", "incident"}, {"experiment"}),
    "motivated_by": ({"decision", "experiment", "assessment"},
                     {"hypothesis", "finding", "decision", "incident"}),
    "depends_on": ({"decision", "experiment", "finding", "assessment"},
                   {"hypothesis", "experiment", "finding", "decision", "incident"}),
    "caused": ({"decision", "experiment"}, {"incident"}),
    "recovered_by": ({"incident"}, {"decision", "experiment"}),
}
EXPECTED_ARTIFACTS = ["planning.md", "REPORT.md", "results/config.json"]
PLACEHOLDERS = {"unknown", "todo", "tbd", "n/a", "none", "...", "placeholder", ""}


class Report:
    def __init__(self):
        self.errors, self.warnings, self.infos = [], [], []

    def err(self, code, msg):
        self.errors.append({"code": code, "msg": msg})

    def warn(self, code, msg):
        self.warnings.append({"code": code, "msg": msg})

    def info(self, code, msg):
        self.infos.append({"code": code, "msg": msg})

    def ok(self):
        return not self.errors

    def to_dict(self):
        return {"ok": self.ok(), "errors": self.errors,
                "warnings": self.warnings, "infos": self.infos}


def listify(value):
    return value if isinstance(value, list) else []


def is_blank(value):
    return not isinstance(value, str) or value.strip().lower() in PLACEHOLDERS


def build_transcript_index(run_dir):
    """Collect every citable transcript item id, so cited evidence ids can verify.

    Three addressing schemes are accepted, because transcripts differ by agent and
    the reconstruction digest cites by line:
      - line-based `L<n>` (1-indexed physical line) — what the digest emits;
      - per-event `tool_id` (Gemini/Codex tool-call transcripts);
      - nested `item.id` (item-lifecycle transcripts).
    The line counter must match the digest's: increment on EVERY physical line.
    """
    ids, files = set(), []
    if not run_dir:
        return ids, files, False
    for path in sorted(glob.glob(os.path.join(run_dir, "logs", "*transcript*.jsonl"))):
        files.append(path)
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                for lineno, raw in enumerate(handle, start=1):
                    line = raw.strip()
                    if not line.startswith("{"):
                        continue
                    ids.add(f"L{lineno}")
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(event, dict):
                        if event.get("tool_id"):
                            ids.add(event["tool_id"])
                        item = event.get("item")
                        if isinstance(item, dict) and item.get("id"):
                            ids.add(item["id"])
        except OSError:
            pass
    return ids, files, bool(files)


def load_inventory_files(data_dir):
    """Files the Pass-1 evidence_inventory.json claims to have found, or None."""
    if not data_dir:
        return None
    path = os.path.join(data_dir, "evidence_inventory.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            inventory = json.load(handle)
    except (OSError, ValueError):
        return None
    raw = (inventory.get("filesFound") or inventory.get("files_present")
           or inventory.get("files") or [])
    out = set()
    for entry in raw:
        if isinstance(entry, str):
            out.add(entry)
        elif isinstance(entry, dict) and entry.get("path"):
            out.add(entry["path"])
    return out


def has_results(run_dir):
    return bool(run_dir) and (
        os.path.isdir(os.path.join(run_dir, "results", "analysis"))
        or os.path.exists(os.path.join(run_dir, "results", "summary.json")))


def check_evidence(rep, evidence, where, ctx):
    if not isinstance(evidence, list) or not evidence:
        rep.err("evidence_missing", f"{where}: needs at least one evidence entry")
        return
    for entry in evidence:
        if not isinstance(entry, dict):
            rep.err("evidence_shape", f"{where}: evidence entry is not an object")
            continue
        etype = entry.get("type")
        if etype not in EVIDENCE_TYPES:
            rep.err("evidence_type", f"{where}: bad evidence.type {etype!r}")
        path, item_id = entry.get("path"), entry.get("itemId")
        if etype == "artifact":
            if not path:
                rep.err("evidence_path_missing", f"{where}: artifact evidence has no path")
            elif ctx["run_dir"] and not os.path.exists(os.path.join(ctx["run_dir"], path)):
                rep.err("evidence_path_not_found", f"{where}: cited path does not exist on disk: {path}")
            elif not ctx["run_dir"]:
                rep.warn("evidence_path_unverified", f"{where}: path {path} not verified (no --run-dir)")
            if path and ctx["inventory"] is not None and path not in ctx["inventory"]:
                rep.warn("evidence_not_in_inventory", f"{where}: cited path not in evidence_inventory: {path}")
        elif etype == "transcript_item":
            if not item_id:
                rep.err("evidence_itemid_missing", f"{where}: transcript_item evidence has no itemId")
            elif ctx["has_transcript"] and item_id not in ctx["item_ids"]:
                rep.err("evidence_itemid_not_found", f"{where}: itemId not found in transcript: {item_id}")
            elif not ctx["has_transcript"]:
                rep.warn("evidence_itemid_unverified", f"{where}: itemId {item_id} not verified (no transcript)")


def check_claim_significance(rep, run_dir):
    """Soft check: report says 'beats/outperforms' but no paired test is significant.

    Reads the p-value COLUMN specifically (not every decimal in the file, which
    would also pick up CI bounds and effect sizes).
    """
    if not run_dir:
        return
    report_path = os.path.join(run_dir, "REPORT.md")
    paired_path = os.path.join(run_dir, "results", "analysis", "paired_tests.csv")
    if not (os.path.exists(report_path) and os.path.exists(paired_path)):
        return
    try:
        with open(report_path, encoding="utf-8", errors="replace") as handle:
            report_text = handle.read().lower()
    except OSError:
        return
    if not re.search(r"\b(beats?|outperform\w*|better than|superior)\b", report_text):
        return
    import csv
    pvals = []
    try:
        with open(paired_path, encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            pcol = next((c for c in (reader.fieldnames or []) if re.search(r"p[_ ]?val", c, re.I)), None)
            if not pcol:
                return
            for row in reader:
                try:
                    pvals.append(float(row[pcol]))
                except (TypeError, ValueError):
                    pass
    except OSError:
        return
    if pvals and all(p >= 0.05 for p in pvals):
        rep.warn("claim_stat_mismatch",
                 "REPORT.md uses 'beats/outperforms' language but every paired p-value >= 0.05 "
                 "— verify the headline isn't overstated")


def check_entity_links(rep, world_model):
    """Validate optional typed links and return whether the graph layer is present."""
    entities = {}
    for collection, kind in ENTITY_COLLECTIONS.items():
        for item in listify(world_model.get(collection)):
            if isinstance(item, dict) and item.get("id"):
                entities[item["id"]] = {"kind": kind, "item": item}

    has_links = any("links" in entry["item"] for entry in entities.values())
    if not has_links:
        return False

    inbound = {entity_id: [] for entity_id in entities}
    for source_id, entry in entities.items():
        links = entry["item"].get("links", [])
        if not isinstance(links, list):
            rep.err("link_shape", f"{source_id}: links must be an array")
            continue
        seen = set()
        for index, link in enumerate(links):
            where = f"{source_id}.links[{index}]"
            if not isinstance(link, dict):
                rep.err("link_shape", f"{where}: link is not an object")
                continue
            relation, target, basis = link.get("relation"), link.get("target"), link.get("basis")
            if relation not in LINK_RELATIONS:
                rep.err("link_relation", f"{where}: bad relation {relation!r}")
            if basis not in LINK_BASIS:
                rep.err("link_basis", f"{where}: bad basis {basis!r}")
            if is_blank(link.get("rationale")):
                rep.err("link_rationale", f"{where}: rationale is empty")
            if target == source_id:
                rep.err("link_self", f"{where}: entity cannot link to itself")
            target_entry = entities.get(target)
            if target_entry is None:
                rep.err("link_target", f"{where}: target id not found: {target!r}")
                continue
            compatibility = LINK_COMPATIBILITY.get(relation)
            if compatibility:
                source_kinds, target_kinds = compatibility
                if entry["kind"] not in source_kinds or target_entry["kind"] not in target_kinds:
                    rep.err("link_type", f"{where}: {entry['kind']} --{relation}--> "
                            f"{target_entry['kind']} is not an allowed direction")
            dedup_key = (relation, target)
            if dedup_key in seen:
                rep.err("link_duplicate", f"{where}: duplicate {relation} link to {target}")
            seen.add(dedup_key)
            inbound[target].append({"source": source_id, "relation": relation})

    for entity_id, entry in entities.items():
        item, kind = entry["item"], entry["kind"]
        if kind == "hypothesis" and item.get("status") in {"supported", "refuted"}:
            expected = "supports" if item.get("status") == "supported" else "refutes"
            if not any(link["relation"] == expected for link in inbound[entity_id]):
                rep.warn("hypothesis_result_unlinked",
                         f"{entity_id}: status is {item.get('status')} but no finding {expected} it")
        if kind == "experiment" and item.get("status") == "done":
            if not any(link["relation"] == "produced_by" for link in inbound[entity_id]):
                rep.warn("experiment_output_unlinked",
                         f"{entity_id}: completed experiment has no produced finding or incident")
    return True


def validate(world_model, run_dir=None, data_dir=None, min_decisions=6, max_decisions=12):
    rep = Report()
    if not isinstance(world_model, dict):
        rep.err("not_object", "world model is not a JSON object")
        return rep

    for key in ("schemaVersion", "runId", "narrative", "current_best", "crux", "hypotheses", "findings", "decisions"):
        if key not in world_model:
            rep.err("missing_field", f"missing top-level field: {key}")
    if world_model.get("schemaVersion") != 3:
        rep.warn("schema_version", f"schemaVersion is {world_model.get('schemaVersion')!r}, expected 3")
    for field in ("narrative", "current_best", "crux"):
        if field in world_model and is_blank(world_model.get(field)):
            rep.err("empty_field", f"{field} is empty or a placeholder")

    item_ids, _, has_transcript = build_transcript_index(run_dir)
    inventory = load_inventory_files(data_dir)
    ctx = {"run_dir": run_dir, "item_ids": item_ids,
           "has_transcript": has_transcript, "inventory": inventory}

    finding_ids = {f.get("id") for f in listify(world_model.get("findings")) if isinstance(f, dict)}
    decision_ids = {d.get("id") for d in listify(world_model.get("decisions")) if isinstance(d, dict)}
    incident_ids = {i.get("id") for i in listify(world_model.get("incidents")) if isinstance(i, dict)}
    all_ids = []

    for hyp in listify(world_model.get("hypotheses")):
        hid = hyp.get("id", "?")
        all_ids.append(hid)
        if not hyp.get("id"):
            rep.err("id_missing", "a hypothesis is missing its id")
        if hyp.get("status") not in HYP_STATUS:
            rep.err("enum", f"hypothesis {hid}: bad status {hyp.get('status')!r}")
        check_evidence(rep, hyp.get("evidence"), f"hypothesis {hid}", ctx)

    for finding in listify(world_model.get("findings")):
        fid = finding.get("id", "?")
        all_ids.append(fid)
        if not finding.get("id"):
            rep.err("id_missing", "a finding is missing its id")
        if finding.get("kind") not in FINDING_KINDS:
            rep.err("enum", f"finding {fid}: bad kind {finding.get('kind')!r}")
        check_evidence(rep, finding.get("evidence"), f"finding {fid}", ctx)

    # Experiments must be complete, not just present. A bare stub ({"id":"E2"}) is the
    # classic miss: the model creates the node as a link target but never fills it.
    # These are blocking errors so the repair loop regenerates the entity from the
    # bundle (pipeline_results/REPORT.md/results), same source the others come from.
    for experiment in listify(world_model.get("experiments")):
        eid = experiment.get("id", "?")
        all_ids.append(eid)
        if not experiment.get("id"):
            rep.err("id_missing", "an experiment is missing its id")
        # v3: an investigation's identity is its `name` (new) or legacy `agent` (pre-v3).
        # Require at least one so a bare {id} stub still fails, but the domain-general
        # `name`-only nodes pass.
        if is_blank(experiment.get("name")) and is_blank(experiment.get("agent")):
            rep.err("experiment_incomplete", f"experiment {eid}: missing name (investigation identity)")
        if experiment.get("status") not in EXPERIMENT_STATUS:
            rep.err("enum", f"experiment {eid}: bad/missing status {experiment.get('status')!r}")
        if experiment.get("status") == "done" and is_blank(experiment.get("result")):
            # v3: the outcome lives in the findings this investigation produced (the spine),
            # so an empty experiment.result is a quality smell, not a blocker — warn, don't
            # quarantine (the repair loop has no bundle to regenerate it from anyway).
            rep.warn("experiment_result_thin", f"experiment {eid}: status 'done' but no result summary "
                     "(its findings should carry the numbers)")

    decisions = listify(world_model.get("decisions"))
    if not decisions:
        rep.err("no_decisions", "no decisions reconstructed")
    if decisions and not (min_decisions <= len(decisions) <= max_decisions):
        rep.warn("decision_count", f"{len(decisions)} decisions (expected {min_decisions}-{max_decisions})")
    valid_finding_refs = finding_ids | {"global"}
    for decision in decisions:
        did = decision.get("id", "?")
        all_ids.append(did)
        for req in ("question", "chosen"):
            if is_blank(decision.get(req)):
                rep.err("decision_field", f"decision {did}: empty {req}")
        # v3 spine: every decision sits in a layer and belongs to a finding (or 'global').
        if decision.get("layer") not in LAYERS:
            rep.err("enum", f"decision {did}: bad/missing layer {decision.get('layer')!r}")
        finding_ref = decision.get("finding")
        if is_blank(finding_ref):
            rep.err("decision_field", f"decision {did}: empty finding (use an F-id or 'global')")
        elif finding_ref not in valid_finding_refs:
            rep.err("decision_finding_ref",
                    f"decision {did}: finding {finding_ref!r} is not a known finding id or 'global'")
        # phase is optional legacy metadata in v3 — validate the enum only when present.
        if decision.get("phase") is not None and decision.get("phase") not in PHASES:
            rep.err("enum", f"decision {did}: bad phase {decision.get('phase')!r}")
        # v3: importance is assigned by the Pass-2 PI reviewer (paper-reading), not the
        # extractor — it lives in the review overlay, not the world model. Validate only
        # if a (legacy) value is present.
        if decision.get("importance") is not None and decision.get("importance") not in IMPORTANCE:
            rep.err("enum", f"decision {did}: bad importance {decision.get('importance')!r}")

        options = decision.get("options")
        if not isinstance(options, list) or not options:
            rep.err("options_missing", f"decision {did}: needs at least one option")
        else:
            artifact_sourced, has_chosen = 0, False
            for opt in options:
                if isinstance(opt, dict):
                    if opt.get("status") not in OPTION_STATUS:
                        rep.err("enum", f"decision {did}: bad option.status {opt.get('status')!r}")
                    if opt.get("source") not in OPTION_SOURCE:
                        rep.err("enum", f"decision {did}: bad option.source {opt.get('source')!r}")
                    if opt.get("source") == "artifact":
                        artifact_sourced += 1
                    if opt.get("status") == "chosen":
                        has_chosen = True
                else:
                    rep.warn("option_unstructured", f"decision {did}: option is a string, not {{text,status,source}}")
            if options and all(isinstance(o, dict) for o in options):
                if artifact_sourced == 0:
                    rep.warn("option_no_artifact", f"decision {did}: no artifact-sourced option")
                if not has_chosen:
                    rep.warn("option_no_chosen", f"decision {did}: no option marked chosen")

        if decision.get("shouldEngageReason") not in ENGAGE_REASONS:
            rep.err("enum", f"decision {did}: bad/missing shouldEngageReason {decision.get('shouldEngageReason')!r}")
        elif decision.get("shouldEngage") and decision.get("shouldEngageReason") == "routine_no":
            rep.warn("engage_mismatch", f"decision {did}: shouldEngage is true but reason is routine_no")

        if decision.get("importance") in ("high", "critical") and not decision.get("statedRationale"):
            rep.info("unjustified_load_bearing",
                     f"decision {did}: {decision.get('importance')} importance with no stated rationale "
                     "(load-bearing choice made silently — verify this is real, not an extraction miss)")

        check_evidence(rep, decision.get("evidence"), f"decision {did}", ctx)

        # paperRef is optional, but when present it must be well-formed: a real paper
        # file and a non-blank anchor. The fuzzy anchor→PDF-box resolution is a
        # separate deterministic build step (build_paper_highlights.py), not here.
        paper_ref = decision.get("paperRef")
        if isinstance(paper_ref, dict):
            pfile = paper_ref.get("file")
            if is_blank(paper_ref.get("anchor")):
                rep.err("paperref_anchor", f"decision {did}: paperRef has no anchor")
            if not pfile or not str(pfile).startswith("paper_draft/"):
                rep.err("paperref_file", f"decision {did}: paperRef.file must be under paper_draft/ (got {pfile!r})")
            elif ctx["run_dir"] and not os.path.exists(os.path.join(ctx["run_dir"], pfile)):
                rep.err("paperref_file_not_found", f"decision {did}: paperRef.file not found: {pfile}")
        elif paper_ref is not None:
            rep.err("paperref_shape", f"decision {did}: paperRef must be an object or null")

    for incident in listify(world_model.get("incidents")):
        iid = incident.get("id", "?")
        all_ids.append(iid)
        if incident.get("kind") not in INCIDENT_KINDS:
            rep.err("enum", f"incident {iid}: bad kind {incident.get('kind')!r}")
        if incident.get("evidence") is not None:
            check_evidence(rep, incident.get("evidence"), f"incident {iid}", ctx)

    # Uniform node envelope: every entity carries `type` (matching its collection) and
    # the optional provenance arrays `affects` (files it changed) / `basedOn` (files/ids
    # it derives from). normalize_world_model backfills these, so this is a consistency
    # guard, not a content demand — empty arrays are fine; most nodes can't fill them.
    for collection, kind in ENTITY_COLLECTIONS.items():
        for node in listify(world_model.get(collection)):
            if not isinstance(node, dict):
                continue
            nid = node.get("id", "?")
            if node.get("type") not in (None, kind):
                rep.err("envelope_type", f"{kind} {nid}: type {node.get('type')!r} != {kind!r}")
            for arr in ("affects", "basedOn"):
                if arr in node and not isinstance(node[arr], list):
                    rep.err("envelope_shape", f"{kind} {nid}: {arr} must be an array")

    check_entity_links(rep, world_model)

    crux_evidence = world_model.get("cruxEvidence")
    if not crux_evidence:
        rep.warn("crux_unlinked", "crux has no cruxEvidence links — should reference a finding/decision/incident")
    else:
        pools = {"finding": finding_ids, "decision": decision_ids, "incident": incident_ids}
        for ref in listify(crux_evidence):
            pool = pools.get(ref.get("type"))
            if pool is None:
                rep.err("crux_ref_type", f"cruxEvidence has bad type {ref.get('type')!r}")
            elif ref.get("id") not in pool:
                rep.err("crux_ref", f"cruxEvidence id not found: {ref.get('type')} {ref.get('id')}")

    duplicates = {i for i in all_ids if i and all_ids.count(i) > 1}
    if duplicates:
        rep.err("duplicate_ids", f"duplicate ids: {sorted(duplicates)}")

    if has_results(run_dir) and not re.search(r"\d", str(world_model.get("current_best", ""))):
        rep.warn("current_best_no_numbers", "results exist but current_best contains no numbers")
    check_claim_significance(rep, run_dir)
    if run_dir:
        for artifact in EXPECTED_ARTIFACTS:
            if not os.path.exists(os.path.join(run_dir, artifact)):
                rep.warn("expected_artifact_missing", f"expected artifact missing: {artifact}")
    if data_dir and inventory is None:
        rep.warn("inventory_missing", "evidence_inventory.json not found (Pass 1 artifact)")

    return rep


def _print_human(world_model_path, rep):
    print(f"world model: {world_model_path}")
    print(f"result: {'PASS' if rep.ok() else 'FAIL'}  "
          f"({len(rep.errors)} errors, {len(rep.warnings)} warnings, {len(rep.infos)} infos)\n")
    for label, items in (("ERROR", rep.errors), ("WARN", rep.warnings), ("INFO", rep.infos)):
        for item in items:
            print(f"  [{label}] {item['code']}: {item['msg']}")
    if not (rep.errors or rep.warnings or rep.infos):
        print("  clean.")


def main():
    parser = argparse.ArgumentParser(description="Validate a reconstructed world_model.json (v3).")
    parser.add_argument("world_model", help="path to world_model.json")
    parser.add_argument("--run-dir", help="raw run folder, enables path/itemId/claim checks")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    parser.add_argument("--min-decisions", type=int, default=6)
    parser.add_argument("--max-decisions", type=int, default=12)
    args = parser.parse_args()

    data_dir = os.path.dirname(os.path.abspath(args.world_model))
    try:
        with open(args.world_model, encoding="utf-8") as handle:
            world_model = json.load(handle)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "errors": [{"code": "parse", "msg": str(exc)}]}) if args.json
              else f"FAIL: could not read/parse {args.world_model}: {exc}")
        sys.exit(2)

    rep = validate(world_model, run_dir=args.run_dir, data_dir=data_dir,
                   min_decisions=args.min_decisions, max_decisions=args.max_decisions)
    if args.json:
        print(json.dumps(rep.to_dict(), indent=2))
    else:
        _print_human(args.world_model, rep)
    sys.exit(0 if rep.ok() else 1)


if __name__ == "__main__":
    main()
