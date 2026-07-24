#!/usr/bin/env python3
"""Resolve each decision's `paperRef` anchor to a highlight box in the paper PDF.

A deterministic build-time step (no LLM): it reads the reconstructed
`world_model.json`, takes the `paperRef.anchor` of every decision that cites the
paper, locates that text in `paper_draft/main.pdf` with PyMuPDF, and writes
`data/runs/<run>/paper_highlights.json` — the page + bounding boxes the frontend
draws over its pdf.js render of the same page.

Matching is fuzzy-tolerant on purpose: the anchor is copied from the `.tex` source,
but the rendered PDF text drifts (line-wrap hyphenation, ligatures, `\\cite{}`→"[12]",
`~`→space). We try, in order: exact search → head/tail-trimmed search → a normalized
word-window match → the section heading (page-only). An anchor that still doesn't
resolve is recorded as `"status":"unresolved"` — never silently dropped, so the UI
can fall back to "mentioned in <section>" instead of showing a wrong box.

CLI:
  python build_paper_highlights.py --run-dir /path/to/run [--repo <visualizer dir>]

Importable:
  from build_paper_highlights import build_paper_highlights
  n = build_paper_highlights(run_dir, data_dir)   # returns count of resolved anchors
"""

import argparse
import datetime
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # neurico-logvisualizer/
PAPER_PDF_REL = os.path.join("paper_draft", "main.pdf")
WORD_WINDOW_CAP = 140  # chars of the (compacted) anchor used for the fuzzy fallback


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _rects_to_lists(rects):
    # PyMuPDF Rects are already in top-left PDF-point space (same origin pdf.js uses
    # after applying its viewport), so the frontend only has to scale by render zoom.
    return [[round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2)] for r in rects]


def _page_meta(page):
    return {"page": page.number + 1,  # 1-indexed to match pdf.js getPage(n)
            "pageWidth": round(page.rect.width, 2),
            "pageHeight": round(page.rect.height, 2)}


def _search_exact(doc, anchor):
    """Exact (whitespace/ligature-tolerant) search; head/tail-trimmed retries for
    when line-wrap hyphenation or a stray citation breaks the middle of the anchor."""
    tries = [(anchor, "exact")]
    words = anchor.split()
    if len(words) > 10:
        tries.append((" ".join(words[:10]), "trimmed"))
        tries.append((" ".join(words[-10:]), "trimmed"))
    for needle, status in tries:
        for page in doc:
            rects = page.search_for(needle)
            if rects:
                return {**_page_meta(page), "rects": _rects_to_lists(rects), "status": status}
    return None


def _word_window(doc, anchor):
    """Fallback: match the anchor against a per-page, whitespace-stripped concatenation
    of words, then union the bounding boxes of the covered words (grouped per line).
    Catches matches that `search_for` misses because of punctuation/command drift."""
    target = _norm(anchor).replace(" ", "")
    if len(target) < 12:
        return None
    needle = target[:WORD_WINDOW_CAP]
    for page in doc:
        words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, wordno)
        if not words:
            continue
        parts = [_norm(w[4]).replace(" ", "") for w in words]
        starts, acc = [], 0
        for p in parts:
            starts.append(acc)
            acc += len(p)
        compact = "".join(parts)
        pos = compact.find(needle)
        if pos == -1:
            continue
        end = pos + len(needle)
        covered = [i for i, p in enumerate(parts)
                   if p and starts[i] < end and starts[i] + len(p) > pos]
        if not covered:
            continue
        lines = {}  # round(y0) -> [x0,y0,x1,y1]
        for i in covered:
            x0, y0, x1, y1 = words[i][:4]
            key = round(y0)
            box = lines.get(key)
            if box is None:
                lines[key] = [x0, y0, x1, y1]
            else:
                box[0], box[1] = min(box[0], x0), min(box[1], y0)
                box[2], box[3] = max(box[2], x1), max(box[3], y1)
        rects = [[round(v, 2) for v in box] for box in lines.values()]
        return {**_page_meta(page), "rects": rects, "status": "approximate"}
    return None


def _section_page(doc, section):
    """Last resort: locate the section heading so the UI can at least open the right
    page ('mentioned in <section>') without a precise box."""
    if not section:
        return None
    for page in doc:
        rects = page.search_for(section.strip())
        if rects:
            return {**_page_meta(page), "rects": _rects_to_lists(rects[:1]), "status": "section_only"}
    return None


def resolve_anchor(doc, anchor, section=None):
    anchor = (anchor or "").strip()
    if not anchor:
        return {"status": "unresolved"}
    return (_search_exact(doc, anchor)
            or _word_window(doc, anchor)
            or _section_page(doc, section)
            or {"status": "unresolved"})


def _paper_anchor(decision):
    """The (anchor, section) to highlight for a decision: its paperRef if present, else
    the first evidence entry that cites a `paper_draft/` section with a verbatim anchor.
    (The v3 layer rubrics put the paper quote in `evidence`, not `paperRef`; REPORT.md
    anchors are skipped — REPORT is not the compiled PDF.)"""
    ref = decision.get("paperRef")
    if isinstance(ref, dict) and (ref.get("anchor") or "").strip():
        return ref.get("anchor"), (ref.get("section") or "")
    for ev in decision.get("evidence") or []:
        path = ev.get("path") or ""
        anchor = (ev.get("anchor") or "").strip()
        if anchor and path.startswith("paper_draft/"):
            section = os.path.splitext(os.path.basename(path))[0].replace("_", " ")
            return anchor, section
    return None, None


def build_paper_highlights(run_dir, data_dir):
    """Resolve every decision.paperRef in data_dir/world_model.json against
    run_dir/paper_draft/main.pdf and write data_dir/paper_highlights.json.
    Returns the number of anchors resolved to an on-page box."""
    import fitz  # PyMuPDF — imported lazily so callers without it can skip gracefully

    pdf_path = os.path.join(run_dir, PAPER_PDF_REL)
    wm_path = os.path.join(data_dir, "world_model.json")
    if not os.path.exists(pdf_path) or not os.path.exists(wm_path):
        return 0
    with open(wm_path, encoding="utf-8") as handle:
        world_model = json.load(handle)

    items, resolved = {}, 0
    with fitz.open(pdf_path) as doc:
        for decision in world_model.get("decisions") or []:
            did = decision.get("id")
            anchor, section = _paper_anchor(decision)
            if not did or not anchor:
                continue
            box = resolve_anchor(doc, anchor, section)
            box["section"] = section or ""
            box["anchor"] = anchor
            box["note"] = (decision.get("paperRef") or {}).get("note") or ""
            items[did] = box
            if box.get("status") not in (None, "unresolved"):
                resolved += 1

    out = {"runId": os.path.basename(run_dir.rstrip("/")), "builtFrom": PAPER_PDF_REL,
           "generatedAt": now_iso(), "items": items}
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "paper_highlights.json"), "w", encoding="utf-8") as handle:
        json.dump(out, handle, ensure_ascii=False, indent=2)
    return resolved


def main():
    parser = argparse.ArgumentParser(description="Resolve decision paperRef anchors to PDF highlight boxes.")
    parser.add_argument("--run-dir", required=True, help="raw run folder (holds paper_draft/main.pdf)")
    parser.add_argument("--repo", default=REPO, help="visualizer dir (holds data/runs/<run>/)")
    args = parser.parse_args()
    run_dir = os.path.abspath(args.run_dir.rstrip("/"))
    run_id = os.path.basename(run_dir)
    data_dir = os.path.join(args.repo, "data", "runs", run_id)
    try:
        n = build_paper_highlights(run_dir, data_dir)
    except ImportError:
        print("PyMuPDF not installed — run: pip install pymupdf", file=sys.stderr)
        sys.exit(2)
    total = 0
    hl_path = os.path.join(data_dir, "paper_highlights.json")
    if os.path.exists(hl_path):
        total = len(json.load(open(hl_path, encoding="utf-8")).get("items", {}))
    print(f"{run_id}: {n}/{total} paperRef anchors resolved → {hl_path}")


if __name__ == "__main__":
    main()
