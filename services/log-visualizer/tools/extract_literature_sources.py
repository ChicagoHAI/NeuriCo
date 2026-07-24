#!/usr/bin/env python3
"""Extract run-specific literature sources without inventing missing sources.

Scans a NeuriCo run for literature notes, resources, downloaded papers/PDFs,
BibTeX entries, paper-draft citations, logs with search results, canonical
trajectory artifacts, and world-model evidence refs. Writes:

  data/runs/<repo>/literature-sources.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".gemini", ".claude", ".codex", ".git", "__pycache__", ".venv", "node_modules"}


def skipped(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def read_text(path: Path, limit: int = 600_000) -> str:
    try:
        if path.stat().st_size > limit:
            return path.read_text(encoding="utf-8", errors="ignore")[:limit]
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def compact(text: str, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[: limit - 1] + "..." if len(text) > limit else text


def infer_usage(text: str) -> list[str]:
    lower = text.lower()
    uses = []
    if re.search(r"hypothesis|idea|direction|motivat", lower):
        uses.append("hypothesis")
    if re.search(r"method|approach|protocol|design", lower):
        uses.append("method")
    if re.search(r"baseline|compare|prior work|related", lower):
        uses.append("baseline")
    if re.search(r"eval|benchmark|metric|result|experiment", lower):
        uses.append("evaluation")
    if re.search(r"write|paper|draft|introduction|related work", lower):
        uses.append("writing")
    return uses or ["writing"]


def source_id(title: str, url: str, local_file: str) -> str:
    base = title or url or local_file
    return re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")[:80] or "source"


def add_source(sources: dict[str, dict], *, title: str, root: Path, local_file: Path | None = None,
               url: str = "", kind: str = "note", authors_year: str = "",
               relevance: str = "", used_text: str = "", journey: str = "",
               decisions: list[str] | None = None) -> None:
    if not (title or url or local_file):
        return
    local = rel(local_file, root) if local_file else ""
    title = compact(title or Path(local).stem.replace("_", " ").replace("-", " ").title(), 180)
    sid = source_id(title, url, local)
    item = sources.setdefault(sid, {
        "sourceId": sid,
        "title": title,
        "authorsYear": authors_year,
        "type": kind,
        "url": url,
        "localFile": local,
        "relevanceSummary": "",
        "howNeuricoUsedIt": [],
        "relatedJourneyNode": "",
        "relatedDecisionsFindings": [],
      })
    if authors_year and not item.get("authorsYear"):
        item["authorsYear"] = authors_year
    if url and not item.get("url"):
        item["url"] = url
    if local and not item.get("localFile"):
        item["localFile"] = local
    if relevance and not item.get("relevanceSummary"):
        item["relevanceSummary"] = compact(relevance)
    for use in infer_usage(used_text or relevance or title):
        if use not in item["howNeuricoUsedIt"]:
            item["howNeuricoUsedIt"].append(use)
    if journey and not item.get("relatedJourneyNode"):
        item["relatedJourneyNode"] = journey
    for decision in decisions or []:
        if decision and decision not in item["relatedDecisionsFindings"]:
            item["relatedDecisionsFindings"].append(decision)


def parse_markdown_sources(root: Path, sources: dict[str, dict]) -> None:
    for name in ["literature_review.md", "resources.md"]:
        path = root / name
        text = read_text(path)
        if not text:
            continue
        for match in re.finditer(r"\[([^\]]{3,220})\]\((https?://[^)\s]+)\)", text):
            start = max(0, match.start() - 220)
            end = min(len(text), match.end() + 220)
            add_source(sources, title=match.group(1), url=match.group(2), root=root, local_file=path,
                       kind="web", relevance=text[start:end], used_text=text[start:end], journey="Literature / Evidence")
        for match in re.finditer(r"https?://[^\s)>\]]+", text):
            start = max(0, match.start() - 160)
            end = min(len(text), match.end() + 160)
            add_source(sources, title=match.group(0), url=match.group(0), root=root, local_file=path,
                       kind="web", relevance=text[start:end], used_text=text[start:end], journey="Literature / Evidence")
        for heading in re.finditer(r"^#{1,4}\s+(.{4,180})$", text, re.MULTILINE):
            title = heading.group(1).strip()
            if re.search(r"literature|resources|related work|notes|summary", title, re.I):
                continue
            start = heading.end()
            end = text.find("\n#", start)
            block = text[start:end if end != -1 else start + 900]
            add_source(sources, title=title, root=root, local_file=path, kind="note",
                       relevance=block, used_text=block, journey="Literature / Evidence")


def parse_bib(root: Path, sources: dict[str, dict]) -> set[str]:
    keys = set()
    for path in list(root.rglob("*.bib")):
        if skipped(path):
            continue
        text = read_text(path)
        for entry in re.finditer(r"@\w+\s*\{\s*([^,\s]+)\s*,(.*?)(?=\n@\w+\s*\{|\Z)", text, re.S):
            key, body = entry.group(1), entry.group(2)
            keys.add(key)
            title = field(body, "title") or key
            authors = field(body, "author")
            year = field(body, "year")
            url = field(body, "url") or field(body, "doi")
            if url and not url.startswith("http") and field(body, "doi"):
                url = f"https://doi.org/{url}"
            add_source(sources, title=strip_bibtex(title), url=url, root=root, local_file=path,
                       kind="citation", authors_year=", ".join(x for x in [compact(authors, 120), year] if x),
                       relevance=f"BibTeX citation {key}.", used_text=body, journey="Literature / Evidence")
    return keys


def field(body: str, name: str) -> str:
    match = re.search(rf"{name}\s*=\s*[\{{\"](.*?)[\}}\"]\s*,?\s*(?:\n|$)", body, re.I | re.S)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def strip_bibtex(text: str) -> str:
    return re.sub(r"[{}]", "", text or "").replace("\\&", "&").strip()


def parse_filesystem_sources(root: Path, sources: dict[str, dict]) -> None:
    for folder in ["papers", "downloaded_pdfs", "downloads", "sources", "literature", "web_sources", "paper_search_results"]:
        base = root / folder
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_dir() or skipped(path):
                continue
            ext = path.suffix.lower()
            if ext not in [".pdf", ".md", ".txt", ".html", ".bib", ".json", ".jsonl"]:
                continue
            kind = "pdf" if ext == ".pdf" else "search_result" if ext in [".json", ".jsonl"] else "note" if ext in [".md", ".txt"] else "web"
            text = "" if ext == ".pdf" else read_text(path, 80_000)
            add_source(sources, title=path.stem.replace("_", " ").replace("-", " "), root=root,
                       local_file=path, kind=kind, relevance=text[:500], used_text=text,
                       journey="Literature / Evidence")

    pages = root / "papers" / "pages"
    if pages.exists():
        for path in pages.rglob("*_manifest.txt"):
            if skipped(path):
                continue
            text = read_text(path, 80_000)
            add_source(sources, title=path.stem.replace("_", " ").replace("-", " "), root=root,
                       local_file=path, kind="paper_manifest", relevance=text[:500], used_text=text,
                       journey="Literature / Evidence")


def parse_tex_citations(root: Path, sources: dict[str, dict], known_bib_keys: set[str]) -> None:
    for path in (root / "paper_draft").rglob("*.tex") if (root / "paper_draft").exists() else []:
        if skipped(path):
            continue
        text = read_text(path)
        for cite in re.findall(r"\\cite\w*\{([^}]+)\}", text):
            for key in [k.strip() for k in cite.split(",") if k.strip()]:
                if key in known_bib_keys:
                    continue
                add_source(sources, title=f"Citation: {key}", root=root, local_file=path,
                           kind="citation", relevance=f"Cited in {rel(path, root)}.", used_text=text,
                           journey="Report Writing")


def parse_logs(root: Path, sources: dict[str, dict]) -> None:
    for path in (root / "logs").rglob("*") if (root / "logs").exists() else []:
        if path.is_dir() or skipped(path) or path.suffix.lower() not in [".jsonl", ".json", ".txt", ".md"]:
            continue
        text = read_text(path, 300_000)
        if not re.search(r"search|paper|arxiv|doi|scholar|semantic", text, re.I):
            continue
        for match in re.finditer(r"https?://[^\s)>\]\"']+", text):
            start = max(0, match.start() - 200)
            end = min(len(text), match.end() + 200)
            add_source(sources, title=match.group(0), url=match.group(0), root=root, local_file=path,
                       kind="web", relevance=text[start:end], used_text=text[start:end],
                       journey="Literature / Evidence")


def parse_json_refs(root: Path, sources: dict[str, dict]) -> None:
    for name in ["canonical_trajectory.json", "world_model.json"]:
        path = root / name
        data = None
        try:
            data = json.loads(read_text(path))
        except json.JSONDecodeError:
            continue
        for ref in walk_refs(data):
            ref_path = ref.get("path") or ref.get("file") or ref.get("url") or ""
            if not ref_path:
                continue
            local = root / ref_path if not re.match(r"https?://", ref_path) else None
            if re.match(r"https?://", ref_path):
                add_source(sources, title=ref.get("title") or ref_path, url=ref_path, root=root,
                           kind="web", relevance=ref.get("note") or ref.get("summary") or "",
                           used_text=json.dumps(ref), journey=ref.get("stage") or "")
            elif is_literature_path(ref_path):
                if local and skipped(local):
                    continue
                add_source(sources, title=ref.get("title") or Path(ref_path).stem, root=root,
                           local_file=local, kind="pdf" if ref_path.lower().endswith(".pdf") else "note",
                           relevance=ref.get("note") or ref.get("summary") or "",
                           used_text=json.dumps(ref), journey=ref.get("stage") or "",
                           decisions=[ref.get("id") or ref.get("decisionId") or ref.get("findingId") or ""])


def walk_refs(value):
    if isinstance(value, dict):
        if any(k in value for k in ["path", "file", "url"]):
            yield value
        for child in value.values():
            yield from walk_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_refs(child)


def is_literature_path(path: str) -> bool:
    if re.search(r"(^|/)\.(gemini|claude|codex)/skills/", path, re.I):
        return False
    return bool(re.search(r"(^|/)(papers|paper_search_results|sources|literature|downloads|web_sources|literature_review|resources)|\.(bib|pdf)$|_manifest\.txt$", path, re.I))


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract run-specific literature sources.")
    parser.add_argument("run", nargs="?", default=".", help="run directory (default: cwd)")
    parser.add_argument("--run-id", help="output run id (default: run folder name)")
    parser.add_argument("--out", help="output JSON path")
    args = parser.parse_args()

    root = Path(args.run).resolve()
    run_id = args.run_id or root.name
    out = Path(args.out).resolve() if args.out else REPO / "data" / "runs" / run_id / "literature-sources.json"
    sources: dict[str, dict] = {}

    parse_markdown_sources(root, sources)
    bib_keys = parse_bib(root, sources)
    parse_filesystem_sources(root, sources)
    parse_tex_citations(root, sources, bib_keys)
    parse_logs(root, sources)
    parse_json_refs(root, sources)

    ordered = sorted(sources.values(), key=lambda item: (item.get("type", ""), item.get("title", "")))
    for source in ordered:
        if not source.get("relevanceSummary"):
            source["relevanceSummary"] = "Found in run literature artifacts."
        source["openSourceLabel"] = "Open source"
        source["traceInJourneyLabel"] = "Trace in Journey"
        source["annotateSourceLabel"] = "Annotate source"

    payload = {
        "version": "literature_sources_v1",
        "runId": run_id,
        "sourceCount": len(ordered),
        "message": f"Only {len(ordered)} literature sources were found in this run.",
        "sources": ordered,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(ordered)} source(s) to {out}")


if __name__ == "__main__":
    main()
