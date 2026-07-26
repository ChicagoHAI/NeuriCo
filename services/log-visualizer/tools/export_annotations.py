#!/usr/bin/env python3
"""Export all reviewer annotations to one CSV (or JSON).

Reads the platform's per-user annotation files —
  data/annotations/<user>/<runId>.json   (one file per user per run)
— and flattens every annotated subject into a row. This is how the researcher
pulls study results off the server (run it over SSH on indigo).

CLI:
  python export_annotations.py                      # CSV to stdout
  python export_annotations.py --out results.csv
  python export_annotations.py --format json --out results.json
  python export_annotations.py --format jsonl --out benchmark.jsonl
"""

import argparse
import csv
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # neurico-logvisualizer/
ANNO_DIR = os.path.join(REPO, "data", "annotations")

# Stable column order; mirrors the fields saveAnnotation persists.
FIELDS = ["user", "runId", "key", "subjectKind", "annotationRoute", "impactType",
          "mustAnnotate", "autoFixCandidate", "needsExpertReview", "affectedOutput",
          "fixability", "reviewerComment", "verdict", "preferredOption",
          "preferredText", "customAlternative", "label", "informUser", "interrupt",
          "note", "snapshot", "updatedAt"]


def collect(anno_dir):
    rows = []
    if not os.path.isdir(anno_dir):
        return rows
    for user in sorted(os.listdir(anno_dir)):
        user_dir = os.path.join(anno_dir, user)
        if not os.path.isdir(user_dir):
            continue
        for fname in sorted(os.listdir(user_dir)):
            if not fname.endswith(".json"):
                continue
            run_id = fname[:-5]
            try:
                with open(os.path.join(user_dir, fname), encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            for key, ann in data.items():
                if not isinstance(ann, dict):
                    continue
                row = {"user": user, "runId": run_id, "key": key}
                for field in FIELDS[3:]:
                    value = ann.get(field, "")
                    row[field] = value if isinstance(value, (str, int, float)) or value is None else json.dumps(value)
                row["jsonlRecord"] = {
                    "runId": run_id,
                    "targetKey": key,
                    "annotationRoute": ann.get("annotationRoute", ""),
                    "impactType": ann.get("impactType", []),
                    "mustAnnotate": bool(ann.get("mustAnnotate")),
                    "autoFixCandidate": bool(ann.get("autoFixCandidate")),
                    "needsExpertReview": bool(ann.get("needsExpertReview")),
                    "affectedOutput": ann.get("affectedOutput", []),
                    "llmPrelabel": ann.get("llmPrelabel", {}),
                    "reviewerVerification": ann.get("reviewerVerification", {}),
                    "reviewerComment": ann.get("reviewerComment", ""),
                    "paperAnchor": ann.get("paperAnchor", {}),
                    "provenanceUsage": ann.get("provenanceUsage", {}),
                    "expertAdjudication": ann.get("expertAdjudication", {}),
                    "hiddenBenchmarkData": ann.get("hiddenBenchmarkData", {}),
                }
                rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description="Export reviewer annotations to CSV/JSON.")
    parser.add_argument("--data-dir", default=ANNO_DIR, help="annotations dir (default: data/annotations)")
    parser.add_argument("--out", help="output file (default: stdout)")
    parser.add_argument("--format", choices=["csv", "json", "jsonl"], default="csv")
    args = parser.parse_args()

    rows = collect(args.data_dir)
    handle = open(args.out, "w", encoding="utf-8", newline="") if args.out else sys.stdout
    try:
        if args.format == "json":
            json.dump(rows, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        elif args.format == "jsonl":
            for row in rows:
                handle.write(json.dumps(row["jsonlRecord"], ensure_ascii=False) + "\n")
        else:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    finally:
        if args.out:
            handle.close()

    files = len({(r["user"], r["runId"]) for r in rows})
    where = f" → {args.out}" if args.out else ""
    print(f"{len(rows)} annotation rows across {files} user×run file(s){where}", file=sys.stderr)


if __name__ == "__main__":
    main()
