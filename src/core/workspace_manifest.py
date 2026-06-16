"""
Workspace Manifest Feature

Two-pass payload for the bootstrap rule_maker stage. Each pass is safe on
its own:

Pass 1 (mechanical, deterministic, audit-able by construction)
    build_manifest(work_dir) walks the workspace and produces a fixed-schema
    JSON sketch. Concrete values, algorithm bodies, and narrative prose are
    replaced with type tokens. Roles are assigned by path convention.

Pass 2 (agent-curated, schema-bounded, value-leak-linted)
    curate_manifest(manifest, work_dir, trimmer) calls a Trimmer agent that
    reads the raw manifest + public write-ups and emits a TrimDecision: a
    closed-enum, value-free curation of which files the rule_maker should see,
    which roles were misclassified, which artifact is the primary scored
    output, and a structural task-shape description. The decision passes
    through (parse → schema validation → cross-validation against the
    substrate → leakage lint) before apply_trim mechanically rewrites the
    manifest. If retries exhaust, fall back to the raw mechanical manifest.

CLI:
    python -m core.workspace_manifest <work_dir> [--out PATH] [--stdout]
"""

from __future__ import annotations

import ast
import csv
import json
import os
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Optional


MANIFEST_VERSION = "1"


# Buckets

def _size_bucket(byte_count: int) -> str:
    if byte_count == 0:
        return "0"
    if byte_count < 1024:
        return "<1kb"
    if byte_count < 10 * 1024:
        return "1-10kb"
    if byte_count < 100 * 1024:
        return "10-100kb"
    if byte_count < 1024 * 1024:
        return "100kb-1mb"
    if byte_count < 10 * 1024 * 1024:
        return "1-10mb"
    return ">10mb"


def _count_bucket(n: int) -> str:
    if n == 0:
        return "0"
    if n < 10:
        return "1-10"
    if n < 100:
        return "10-100"
    if n < 1000:
        return "100-1000"
    if n < 10_000:
        return "1000-10000"
    return ">10000"


# Walk + ignore

IGNORED_DIR_NAMES = frozenset({
    "__pycache__",
    ".git", ".github",
    ".venv", "venv", "env",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    ".idea", ".vscode",
    ".claude", ".gemini", ".codex",
    ".scoring_sealed",
    "node_modules",
    ".ipynb_checkpoints",
})

IGNORED_FILE_PATTERNS = (
    "*.pyc", "*.pyo",
    ".DS_Store", "Thumbs.db",
)


def _match_any_glob(name: str, patterns: Iterable[str]) -> bool:
    import fnmatch as _fnmatch
    return any(_fnmatch.fnmatch(name, p) for p in patterns)


def _walk_workspace(root: Path) -> Iterable[Path]:
    """Yield files under root in deterministic order, pruning ignored dirs."""
    for dir_path, dir_names, file_names in os.walk(root):
        dir_names[:] = sorted(d for d in dir_names if d not in IGNORED_DIR_NAMES)
        for fname in sorted(file_names):
            if _match_any_glob(fname, IGNORED_FILE_PATTERNS):
                continue
            yield Path(dir_path) / fname


# Role classifier
#
# Ordered. First match wins. Globs support ** (any depth, including empty)
# and * (single segment).

_RAW_ROLE_RULES: list[tuple[str, str]] = [
    # Sealed groundtruth — must never be exposed even via schema.
    ("data/.test/**", "sealed_groundtruth"),
    ("data/.test", "sealed_groundtruth"),
    ("data/test/**", "sealed_groundtruth"),
    ("data/holdout/**", "sealed_groundtruth"),

    # Pre-experiment context — safe to expose in full. Resource_finder has used
    # several layout names across template versions; recognise all of them.
    ("resources/**", "preexperiment_context"),
    ("papers/**", "preexperiment_context"),
    ("paper_search_results/**", "preexperiment_context"),
    ("literature_review.md", "preexperiment_context"),
    ("literature_review*.md", "preexperiment_context"),
    ("resources.md", "preexperiment_context"),
    ("ideas/**", "preexperiment_context"),
    (".resource_finder_complete", "pipeline_state"),

    # Runtime artifacts — produced by the experiment_runner.
    ("results/**", "runtime_artifact"),
    ("experiments/**", "runtime_artifact"),
    ("REPORT.md", "runtime_artifact"),
    ("planning.md", "runtime_artifact"),
    ("artifacts/**", "runtime_artifact"),

    # Ephemeral.
    ("logs/**", "ephemeral_log"),

    # Notebooks.
    ("notebooks/**", "notebook"),

    # Source code. Older layouts used `code/` instead of `src/`.
    ("src/**", "source_code"),
    ("code/**", "source_code"),
    ("Mathlib/**", "source_code"),
    ("*.lean", "source_code"),
    ("lakefile.lean", "source_code"),
    ("lakefile.toml", "source_code"),
    ("lean-toolchain", "source_code"),

    # Input data.
    ("data/**", "input_data"),
    ("inputs/**", "input_data"),

    # Paper outputs.
    ("paper/**", "paper_output"),
    ("paper_draft/**", "paper_output"),
    ("templates/paper_writing/**", "scaffolding"),

    # Scaffolding.
    ("README*.md", "scaffolding"),
    ("README", "scaffolding"),
    ("pyproject.toml", "scaffolding"),
    ("setup.py", "scaffolding"),
    ("setup.cfg", "scaffolding"),
    ("requirements*.txt", "scaffolding"),
    ("package.json", "scaffolding"),
    ("Cargo.toml", "scaffolding"),
    ("Makefile", "scaffolding"),
    ("Dockerfile", "scaffolding"),
    (".gitignore", "scaffolding"),
    ("LICENSE", "scaffolding"),

    # NeuriCo internals — not part of experiment surface.
    (".neurico/**", "pipeline_state"),
    ("scoring/**", "scoring_protocol"),  # bootstrap precondition: absent
]


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a POSIX glob with ** support into a regex matching whole paths."""
    parts: list[str] = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                parts.append(".*")
                i += 2
                if i < len(pattern) and pattern[i] == "/":
                    i += 1
            else:
                parts.append("[^/]*")
                i += 1
        elif c == "?":
            parts.append("[^/]")
            i += 1
        elif c in r".+()[]{}|^$\\":
            parts.append(re.escape(c))
            i += 1
        else:
            parts.append(c)
            i += 1
    return re.compile("^" + "".join(parts) + "$")


_ROLE_RULES_COMPILED = [(_glob_to_regex(p), role) for p, role in _RAW_ROLE_RULES]


# Roles for which we record path + size + format but withhold any schema or
# content extraction. The rule_maker sees these files exist but learns nothing
# about their internal shape, because their contents are either the answer key,
# an after-the-fact narrative of results, or workflow plumbing that isn't part
# of the experiment surface.
WITHHELD_EXTRACTION_ROLES = frozenset({
    "sealed_groundtruth",
    "ephemeral_log",
    "paper_output",
    "pipeline_state",
    "scoring_protocol",
})


def _classify_role(rel_path: str) -> str:
    for pattern, role in _ROLE_RULES_COMPILED:
        if pattern.match(rel_path):
            return role
    return "unknown"


# Python signature extraction (AST, bodies and docstrings stripped)

def _ann(node: Optional[ast.AST]) -> str:
    if node is None:
        return "<unannotated>"
    try:
        return ast.unparse(node)
    except Exception:
        return "<unrepresentable>"


def _function_signature(node: ast.AST) -> dict:
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    params: list[dict] = []
    args = node.args
    for a in args.posonlyargs:
        params.append({"name": a.arg, "annotation": _ann(a.annotation), "kind": "positional_only"})
    for a in args.args:
        params.append({"name": a.arg, "annotation": _ann(a.annotation), "kind": "positional"})
    if args.vararg:
        params.append({"name": args.vararg.arg, "annotation": _ann(args.vararg.annotation),
                       "kind": "var_positional"})
    for a in args.kwonlyargs:
        params.append({"name": a.arg, "annotation": _ann(a.annotation), "kind": "keyword_only"})
    if args.kwarg:
        params.append({"name": args.kwarg.arg, "annotation": _ann(args.kwarg.annotation),
                       "kind": "var_keyword"})
    return {
        "kind": "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
        "name": node.name,
        "params": params,
        "returns": _ann(node.returns),
        "decorators": [_ann(d) for d in node.decorator_list],
    }


def _class_signature(node: ast.ClassDef) -> dict:
    methods: list[dict] = []
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(_function_signature(item))
    return {
        "kind": "class",
        "name": node.name,
        "bases": [_ann(b) for b in node.bases],
        "methods": methods,
        "decorators": [_ann(d) for d in node.decorator_list],
    }


def _extract_python_signatures(path: Path) -> tuple[list[dict], Optional[str]]:
    try:
        source = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        return [], f"read_failed: {type(e).__name__}"
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        return [], f"syntax_error: {e.msg}"

    sigs: list[dict] = []
    annotated_count = 0
    total_param_slots = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sig = _function_signature(node)
            sigs.append(sig)
            total_param_slots += len(sig["params"]) + 1  # +1 for return
            annotated_count += sum(1 for p in sig["params"] if p["annotation"] != "<unannotated>")
            if sig["returns"] != "<unannotated>":
                annotated_count += 1
        elif isinstance(node, ast.ClassDef):
            cs = _class_signature(node)
            sigs.append(cs)
            for m in cs["methods"]:
                total_param_slots += len(m["params"]) + 1
                annotated_count += sum(1 for p in m["params"] if p["annotation"] != "<unannotated>")
                if m["returns"] != "<unannotated>":
                    annotated_count += 1
    # Coverage isn't returned per-sig but the rule_maker can compute it from the
    # manifest if needed; surfaced in extraction summary.
    return sigs, None


# JSON / JSONL schema redaction

def _redact_json_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "<bool>"
    if isinstance(value, int):
        return "<int>"
    if isinstance(value, float):
        return "<float>"
    if isinstance(value, str):
        return "<string>"
    if value is None:
        return "<null>"
    if isinstance(value, dict):
        return {k: _redact_json_value(v) for k, v in value.items()}
    if isinstance(value, list):
        if not value:
            return ["<empty_list>"]
        shapes = [_redact_json_value(item) for item in value[:5]]
        deduped: list[Any] = []
        for s in shapes:
            if s not in deduped:
                deduped.append(s)
        return deduped if len(deduped) == 1 else [{"<union>": deduped}]
    return "<unknown>"


def _extract_json_schema(path: Path) -> tuple[Any, Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        return None, f"read_failed: {type(e).__name__}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"parse_failed: {e.msg}"
    return _redact_json_value(data), None


def _extract_jsonl_schema(path: Path, max_lines: int = 100) -> tuple[dict, Optional[str]]:
    sampled: list[Any] = []
    total = 0
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                total += 1
                if len(sampled) >= max_lines:
                    continue
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    sampled.append(json.loads(stripped))
                except json.JSONDecodeError:
                    continue
    except (UnicodeDecodeError, OSError) as e:
        return {}, f"read_failed: {type(e).__name__}"

    if not sampled:
        return {}, "no_valid_lines"

    if all(isinstance(r, dict) for r in sampled):
        all_keys: set[str] = set()
        for r in sampled:
            all_keys.update(r.keys())
        record_schema: dict[str, Any] = {}
        for key in sorted(all_keys):
            seen_shapes: list[Any] = []
            present_in = 0
            for r in sampled:
                if key in r:
                    present_in += 1
                    redacted = _redact_json_value(r[key])
                    if redacted not in seen_shapes:
                        seen_shapes.append(redacted)
            shape = seen_shapes[0] if len(seen_shapes) == 1 else {"<union>": seen_shapes}
            if present_in < len(sampled):
                record_schema[key] = {"<optional>": shape}
            else:
                record_schema[key] = shape
        return {
            "record_schema": record_schema,
            "record_count_bucket": _count_bucket(total),
            "sampled_records": len(sampled),
        }, None

    return {
        "record_schema": _redact_json_value(sampled[0]),
        "record_count_bucket": _count_bucket(total),
        "sampled_records": len(sampled),
    }, None


# Tabular schema

def _infer_csv_dtype(samples: list[str]) -> str:
    non_empty = [s for s in samples if s != ""]
    if not non_empty:
        return "<unknown>"

    def is_int(s: str) -> bool:
        try:
            int(s)
            return True
        except ValueError:
            return False

    def is_float(s: str) -> bool:
        try:
            float(s)
            return True
        except ValueError:
            return False

    if all(is_int(s) for s in non_empty):
        return "<int>"
    if all(is_float(s) for s in non_empty):
        return "<float>"
    if all(s.lower() in {"true", "false"} for s in non_empty):
        return "<bool>"
    return "<string>"


def _extract_csv_schema(path: Path) -> tuple[dict, Optional[str]]:
    try:
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
            except StopIteration:
                return {"columns": [], "row_count_bucket": "0"}, None
            sample_rows: list[list[str]] = []
            for i, row in enumerate(reader):
                if i >= 50:
                    break
                sample_rows.append(row)
        with path.open(encoding="utf-8", newline="") as f:
            total = max(0, sum(1 for _ in csv.reader(f)) - 1)
    except (UnicodeDecodeError, OSError) as e:
        return {}, f"read_failed: {type(e).__name__}"
    except csv.Error as e:
        return {}, f"parse_failed: {e}"

    columns = []
    for col_idx, col_name in enumerate(headers):
        samples = [row[col_idx] for row in sample_rows if col_idx < len(row)]
        columns.append({"name": col_name, "dtype": _infer_csv_dtype(samples)})
    return {"columns": columns, "row_count_bucket": _count_bucket(total)}, None


# Markdown outline

_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_NUMERIC_RE = re.compile(r"[\d.]+%?")


def _safe_header_text(text: str) -> str:
    # Strip any numeric token from header text. Section numbers and inline
    # numerics in titles like "Results: 0.62 accuracy" must not leak.
    return _NUMERIC_RE.sub("<N>", text).strip()


def _extract_markdown_outline(path: Path) -> tuple[list[dict], Optional[str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError) as e:
        return [], f"read_failed: {type(e).__name__}"

    in_fence = False
    headers: list[dict] = []
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADER_RE.match(line)
        if m:
            headers.append({
                "level": len(m.group(1)),
                "text": _safe_header_text(m.group(2)),
            })
    return headers, None


# Notebook outline

def _extract_notebook_outline(path: Path) -> tuple[list[dict], Optional[str]]:
    try:
        nb = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, OSError) as e:
        return [], f"read_failed: {type(e).__name__}"
    except json.JSONDecodeError as e:
        return [], f"parse_failed: {e.msg}"

    outline: list[dict] = []
    for i, cell in enumerate(nb.get("cells", [])):
        cell_type = cell.get("cell_type", "unknown")
        entry: dict[str, Any] = {"index": i, "type": cell_type}
        if cell_type == "markdown":
            source = cell.get("source", "")
            if isinstance(source, list):
                source = "".join(source)
            md_headers: list[dict] = []
            for line in source.splitlines():
                m = _HEADER_RE.match(line)
                if m:
                    md_headers.append({
                        "level": len(m.group(1)),
                        "text": _safe_header_text(m.group(2)),
                    })
            if md_headers:
                entry["markdown_headers"] = md_headers
        outline.append(entry)
    return outline, None


# Likely runner outputs

_LIKELY_OUTPUT_NAMES = frozenset({
    "results.json", "metrics.json", "predictions.json",
    "outputs.json", "summary.json", "scores.json",
    "results.csv", "metrics.csv", "predictions.csv",
    "report.md", "REPORT.md",
})


def _find_likely_runner_outputs(file_entries: list[dict]) -> list[dict]:
    candidates: list[dict] = []
    for entry in file_entries:
        path = entry["path"]
        name = Path(path).name
        role = entry["role"]

        score = 0
        reasons: list[str] = []

        if role == "runtime_artifact":
            score += 2
            reasons.append("role=runtime_artifact")

        if name in _LIKELY_OUTPUT_NAMES:
            score += 2
            reasons.append("canonical_output_name")

        if path.startswith("results/") and "/" not in path[len("results/"):]:
            score += 1
            reasons.append("top_level_of_results")

        if path == "REPORT.md":
            score += 1
            reasons.append("workspace_root_REPORT.md")

        if score >= 2:
            candidates.append({"path": path, "score": score, "evidence": reasons})

    return sorted(candidates, key=lambda c: (-c["score"], c["path"]))


# Sweep rollups

def _detect_sweep_rollups(file_entries: list[dict]) -> list[dict]:
    """
    Detect groups of >=3 sibling directories with identical file basenames.
    Common pattern: experiments/sweep/run_001/, run_002/, ... each holding the
    same artifacts. Surface a single rollup entry instead of N redundant ones.
    """
    grandparents: dict[str, dict[str, set[str]]] = {}
    for entry in file_entries:
        parts = Path(entry["path"]).parts
        if len(parts) < 3:
            continue
        gp = "/".join(parts[:-2])
        sib = parts[-2]
        basename = parts[-1]
        grandparents.setdefault(gp, {}).setdefault(sib, set()).add(basename)

    rollups: list[dict] = []
    for gp, sibs in sorted(grandparents.items()):
        if len(sibs) < 3:
            continue
        groups: dict[frozenset[str], list[str]] = {}
        for sib, basenames in sibs.items():
            groups.setdefault(frozenset(basenames), []).append(sib)
        for basenames, sib_list in groups.items():
            if len(sib_list) >= 3:
                rollups.append({
                    "parent_dir": gp,
                    "replicates": len(sib_list),
                    "shared_basenames": sorted(basenames),
                    "sample_sibling": sorted(sib_list)[0],
                })
    return sorted(rollups, key=lambda r: r["parent_dir"])


# Format mapping

_FORMAT_FOR_EXT = {
    ".py": "python",
    ".json": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".csv": "csv",
    ".tsv": "csv",
    ".md": "markdown",
    ".markdown": "markdown",
    ".ipynb": "notebook",
    ".lean": "lean",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".txt": "text",
    ".toml": "toml",
    ".cfg": "config",
    ".ini": "config",
    ".html": "html",
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".svg": "image",
    ".npy": "numpy_binary",
    ".npz": "numpy_binary",
    ".parquet": "parquet",
    ".pkl": "pickle",
    ".pickle": "pickle",
    ".pth": "torch_binary",
    ".bin": "binary",
    ".so": "binary",
    ".tar": "archive",
    ".gz": "archive",
    ".zip": "archive",
}


def _format_for_extension(ext: str) -> str:
    return _FORMAT_FOR_EXT.get(ext, ext.lstrip(".") or "no_extension")


# Public API

def build_manifest(work_dir: Path) -> dict:
    """
    Build a deterministic, value-redacted manifest of a workspace.

    The manifest is the only structural information the bootstrap rule_maker
    sees. Source code bodies, artifact values, and report prose are excluded
    by construction.
    """
    work_dir = Path(work_dir).resolve()
    if not work_dir.is_dir():
        raise NotADirectoryError(f"work_dir is not a directory: {work_dir}")

    files_meta: list[dict] = []
    python_signatures: list[dict] = []
    json_schemas: list[dict] = []
    jsonl_schemas: list[dict] = []
    tabular_schemas: list[dict] = []
    markdown_outlines: list[dict] = []
    notebook_outlines: list[dict] = []
    extraction_warnings: list[dict] = []

    for file_path in _walk_workspace(work_dir):
        try:
            rel = file_path.relative_to(work_dir).as_posix()
        except ValueError:
            continue

        try:
            stat = file_path.stat()
        except OSError as e:
            extraction_warnings.append({"path": rel, "reason": f"stat_failed: {e}"})
            continue

        size = stat.st_size
        role = _classify_role(rel)
        ext = file_path.suffix.lower()
        fmt = _format_for_extension(ext)

        entry: dict[str, Any] = {
            "path": rel,
            "role": role,
            "format": fmt,
            "size_bucket": _size_bucket(size),
        }

        # Per-format extraction. Some roles record only path/size/format with
        # no schema extraction even when the file is JSON/CSV/MD: the rule_maker
        # never sees their shape, because that shape leaks either the answer
        # key, post-hoc result narrative, or workflow plumbing.
        if role in WITHHELD_EXTRACTION_ROLES:
            entry["extraction"] = "withheld"
        elif ext == ".py":
            sigs, err = _extract_python_signatures(file_path)
            if err:
                extraction_warnings.append({"path": rel, "reason": err})
                entry["extraction"] = "skipped"
            else:
                for s in sigs:
                    python_signatures.append({"path": rel, **s})
                entry["extraction"] = "full"
        elif ext == ".json":
            schema, err = _extract_json_schema(file_path)
            if err:
                extraction_warnings.append({"path": rel, "reason": err})
                entry["extraction"] = "skipped"
            else:
                json_schemas.append({"path": rel, "schema": schema})
                entry["extraction"] = "full"
        elif ext in (".jsonl", ".ndjson"):
            schema, err = _extract_jsonl_schema(file_path)
            if err:
                extraction_warnings.append({"path": rel, "reason": err})
                entry["extraction"] = "skipped"
            else:
                jsonl_schemas.append({"path": rel, **schema})
                entry["extraction"] = "full"
        elif ext in (".csv", ".tsv"):
            schema, err = _extract_csv_schema(file_path)
            if err:
                extraction_warnings.append({"path": rel, "reason": err})
                entry["extraction"] = "skipped"
            else:
                tabular_schemas.append({"path": rel, **schema})
                entry["extraction"] = "full"
        elif ext in (".md", ".markdown"):
            headers, err = _extract_markdown_outline(file_path)
            if err:
                extraction_warnings.append({"path": rel, "reason": err})
                entry["extraction"] = "skipped"
            else:
                markdown_outlines.append({"path": rel, "headers": headers})
                entry["extraction"] = "full"
        elif ext == ".ipynb":
            outline, err = _extract_notebook_outline(file_path)
            if err:
                extraction_warnings.append({"path": rel, "reason": err})
                entry["extraction"] = "skipped"
            else:
                notebook_outlines.append({"path": rel, "cells": outline})
                entry["extraction"] = "full"
        else:
            entry["extraction"] = "none"

        files_meta.append(entry)

    sweep_rollups = _detect_sweep_rollups(files_meta)
    likely_outputs = _find_likely_runner_outputs(files_meta)

    roles_summary: dict[str, int] = {}
    for entry in files_meta:
        roles_summary[entry["role"]] = roles_summary.get(entry["role"], 0) + 1

    return {
        "version": MANIFEST_VERSION,
        "workspace_basename": work_dir.name,
        "roles_summary": dict(sorted(roles_summary.items())),
        "files": files_meta,
        "likely_runner_outputs": likely_outputs,
        "sweep_rollups": sweep_rollups,
        "python_signatures": python_signatures,
        "json_schemas": json_schemas,
        "jsonl_schemas": jsonl_schemas,
        "tabular_schemas": tabular_schemas,
        "markdown_outlines": markdown_outlines,
        "notebook_outlines": notebook_outlines,
        "extraction_warnings": extraction_warnings,
    }


# Pass 2: Trim decision schema (closed enums; agent output target)

class Role(str, Enum):
    sealed_groundtruth = "sealed_groundtruth"
    preexperiment_context = "preexperiment_context"
    runtime_artifact = "runtime_artifact"
    ephemeral_log = "ephemeral_log"
    notebook = "notebook"
    source_code = "source_code"
    input_data = "input_data"
    paper_output = "paper_output"
    scaffolding = "scaffolding"
    pipeline_state = "pipeline_state"
    scoring_protocol = "scoring_protocol"
    unknown = "unknown"


class TaskType(str, Enum):
    classification = "classification"
    regression = "regression"
    generation = "generation"
    ranking = "ranking"
    retrieval = "retrieval"
    optimization = "optimization"
    proof_synthesis = "proof_synthesis"
    program_synthesis = "program_synthesis"
    simulation = "simulation"
    other = "other"


class EvaluationParadigm(str, Enum):
    held_out_test_classification = "held_out_test_classification"
    held_out_test_regression = "held_out_test_regression"
    reference_match = "reference_match"
    unit_tests = "unit_tests"
    proof_check = "proof_check"
    numeric_threshold = "numeric_threshold"
    benchmark_score = "benchmark_score"
    pairwise_comparison = "pairwise_comparison"
    other = "other"


class LabelSpace(str, Enum):
    binary = "binary"
    k_way_discrete = "k_way_discrete"
    continuous = "continuous"
    sequence = "sequence"
    structured = "structured"
    open_ended = "open_ended"
    not_applicable = "not_applicable"


_INTENT_SUMMARY_MAX_CHARS = 200
_OUTPUT_DESCRIPTION_MAX_CHARS = 200
_DATASET_FAMILY_MAX_CHARS = 80


@dataclass(frozen=True)
class TaskShape:
    task_type: TaskType
    evaluation_paradigm: EvaluationParadigm
    label_space: LabelSpace
    dataset_family: Optional[str]

    def as_dict(self) -> dict:
        return {
            "task_type": self.task_type.value,
            "evaluation_paradigm": self.evaluation_paradigm.value,
            "label_space": self.label_space.value,
            "dataset_family": self.dataset_family,
        }


@dataclass(frozen=True)
class TrimDecision:
    """
    Output-focused curation decision.

    The rule_maker receives only:
      - task shape and intent summary (semantic frame)
      - output_description (what the runner produces, value-free)
      - the schema of each primary runner output
      - the specific public API signatures that produce those outputs
    Everything else in the workspace -- literature, planning, internal helpers,
    paper drafts, logs -- is excluded from the rule_maker's view.
    """
    primary_runner_outputs: list[str]
    producer_signatures: dict[str, list[str]]  # path -> [signature_names]
    task_shape: TaskShape
    intent_summary: str
    output_description: str

    def as_dict(self) -> dict:
        return {
            "primary_runner_outputs": list(self.primary_runner_outputs),
            "producer_signatures": {p: list(n) for p, n in self.producer_signatures.items()},
            "task_shape": self.task_shape.as_dict(),
            "intent_summary": self.intent_summary,
            "output_description": self.output_description,
        }


class ManifestValidationError(ValueError):
    """Raised when a trim decision fails schema/cross/lint validation."""


# Pass 2: Parsing — dict → TrimDecision with explicit, message-rich checks

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestValidationError(message)


def _require_enum(value: Any, enum_cls: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    _require(
        isinstance(value, str),
        f"{field_name} must be a string, got {type(value).__name__}",
    )
    try:
        return enum_cls(value)
    except ValueError:
        allowed = ", ".join(e.value for e in enum_cls)
        raise ManifestValidationError(
            f"{field_name}={value!r} is not one of: {allowed}"
        )


def parse_trim_decision(payload: Any) -> TrimDecision:
    """
    Strict dict → TrimDecision parser. Raises ManifestValidationError with a
    descriptive message on any deviation so the agent's retry pass can use the
    message to self-correct.
    """
    _require(isinstance(payload, dict), "trim decision must be a JSON object")

    primary = payload.get("primary_runner_outputs")
    _require(isinstance(primary, list), "primary_runner_outputs must be a list")
    _require(
        all(isinstance(p, str) for p in primary),
        "every primary_runner_outputs entry must be a string",
    )

    raw_producer = payload.get("producer_signatures")
    _require(
        isinstance(raw_producer, dict),
        "producer_signatures must be an object mapping path -> list of names",
    )
    producer_signatures: dict[str, list[str]] = {}
    for path, names in raw_producer.items():
        _require(isinstance(path, str), "producer_signatures keys must be strings")
        _require(
            isinstance(names, list) and all(isinstance(n, str) for n in names),
            f"producer_signatures[{path!r}] must be a list of strings",
        )
        _require(
            len(names) > 0,
            f"producer_signatures[{path!r}] must list at least one signature name",
        )
        producer_signatures[path] = list(names)

    shape_payload = payload.get("task_shape")
    _require(isinstance(shape_payload, dict), "task_shape must be an object")
    dataset_family = shape_payload.get("dataset_family")
    if dataset_family is not None:
        _require(
            isinstance(dataset_family, str),
            "task_shape.dataset_family must be a string or null",
        )
        _require(
            len(dataset_family) <= _DATASET_FAMILY_MAX_CHARS,
            f"task_shape.dataset_family exceeds {_DATASET_FAMILY_MAX_CHARS} chars",
        )
    shape = TaskShape(
        task_type=_require_enum(shape_payload.get("task_type"), TaskType, "task_shape.task_type"),
        evaluation_paradigm=_require_enum(
            shape_payload.get("evaluation_paradigm"),
            EvaluationParadigm,
            "task_shape.evaluation_paradigm",
        ),
        label_space=_require_enum(
            shape_payload.get("label_space"), LabelSpace, "task_shape.label_space"
        ),
        dataset_family=dataset_family,
    )

    intent = payload.get("intent_summary")
    _require(isinstance(intent, str), "intent_summary must be a string")
    _require(
        len(intent) <= _INTENT_SUMMARY_MAX_CHARS,
        f"intent_summary exceeds {_INTENT_SUMMARY_MAX_CHARS} chars",
    )

    output_description = payload.get("output_description")
    _require(isinstance(output_description, str), "output_description must be a string")
    _require(
        len(output_description) <= _OUTPUT_DESCRIPTION_MAX_CHARS,
        f"output_description exceeds {_OUTPUT_DESCRIPTION_MAX_CHARS} chars",
    )

    return TrimDecision(
        primary_runner_outputs=list(primary),
        producer_signatures=producer_signatures,
        task_shape=shape,
        intent_summary=intent,
        output_description=output_description,
    )


# Pass 2: Cross-validation against the mechanical substrate

def cross_validate(trim: TrimDecision, manifest: dict) -> list[str]:
    """
    Structural checks the schema validator can't do alone: every claimed path
    must exist in the manifest; producer_signatures must reference actual
    signatures the mechanical extractor found.
    """
    errors: list[str] = []
    manifest_paths = {f["path"] for f in manifest.get("files", [])}

    if not trim.primary_runner_outputs:
        errors.append("primary_runner_outputs must contain at least one path")

    bad_primary = [p for p in trim.primary_runner_outputs if p not in manifest_paths]
    if bad_primary:
        errors.append(f"primary_runner_outputs not in manifest: {bad_primary[:5]}")

    # Signature name lookup keyed by (path, name).
    sig_names_by_path: dict[str, set[str]] = {}
    for sig in manifest.get("python_signatures", []):
        sig_names_by_path.setdefault(sig["path"], set()).add(sig["name"])

    if not trim.producer_signatures:
        errors.append("producer_signatures must reference at least one path")

    for path, names in trim.producer_signatures.items():
        if path not in manifest_paths:
            errors.append(f"producer_signatures path not in manifest: {path}")
            continue
        available = sig_names_by_path.get(path, set())
        bad_names = [n for n in names if n not in available]
        if bad_names:
            errors.append(
                f"producer_signatures[{path!r}] references names not found by AST "
                f"extraction: {bad_names[:5]}"
            )

    return errors


# Pass 2: Leakage lint — numeric + performance vocabulary
#
# The agent reads value-bearing write-ups. Its output must not transmit
# numeric anchors or qualitative performance claims through any free-text
# field. These checks run on every text field the agent controls.

_DIGIT_RE = re.compile(r"\d")

_PERFORMANCE_BANLIST = (
    # Qualitative positive
    "good", "great", "excellent", "high", "strong", "competitive", "robust",
    "improved", "improves", "better", "best", "outperforms", "outperformed",
    "achieves", "achieved", "reaches", "reached", "surpasses",
    # Qualitative negative
    "poor", "low", "weak", "fails", "failed", "below", "worse", "worst",
    # Approximation hedges that gesture at values
    "around", "approximately", "roughly", "about",
    # Magnitude / degree
    "significantly", "substantially", "marginally", "notably",
)

_PERFORMANCE_BANLIST_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _PERFORMANCE_BANLIST) + r")\b",
    re.IGNORECASE,
)


def _text_leakage_check(
    text: str,
    field_name: str,
    *,
    allow_digits: bool = False,
) -> list[str]:
    issues: list[str] = []
    if not allow_digits and _DIGIT_RE.search(text):
        issues.append(f"{field_name} contains a numeric token (digits are banned)")
    banned_hits = _PERFORMANCE_BANLIST_RE.findall(text)
    if banned_hits:
        unique_hits = sorted({h.lower() for h in banned_hits})
        issues.append(
            f"{field_name} contains banned performance vocabulary: {unique_hits}"
        )
    return issues


def lint_for_leakage(trim: TrimDecision) -> list[str]:
    """
    Scan agent-controlled free text for value-leak indicators.

    Digit ban applies to intent_summary and output_description, where any
    digit would encode a performance value. dataset_family is exempt from
    the digit ban: canonical benchmark identifiers legitimately contain
    digits (GSM8K, MMLU-Pro, HumanEval+, etc.) and these are not value
    leaks. Performance vocabulary is still banned in every text field.
    """
    issues: list[str] = []
    issues.extend(_text_leakage_check(trim.intent_summary, "intent_summary"))
    issues.extend(_text_leakage_check(trim.output_description, "output_description"))
    if trim.task_shape.dataset_family:
        issues.extend(
            _text_leakage_check(
                trim.task_shape.dataset_family,
                "task_shape.dataset_family",
                allow_digits=True,
            )
        )
    return issues


# Pass 2: apply_trim — pure, deterministic post-processor
#
# Output shape is intentionally NARROW. The rule_maker sees only the
# semantic frame (task_shape, intent_summary, output_description), the
# schema of each primary runner output, and the specific public-API
# signatures that produce those outputs. Workspace-wide files[], roles
# summary, broad markdown outlines, internal helpers -- all dropped.

def apply_trim(manifest: dict, trim: TrimDecision) -> dict:
    """
    Apply a fully-validated TrimDecision to a raw manifest. Pure function.

    Assumes its input has already passed parse_trim_decision, cross_validate,
    and lint_for_leakage. Crashes loudly on mismatched input by design.
    """
    files_index = {f["path"]: f for f in manifest.get("files", [])}

    # Group raw extractions by path so we can attach per-format detail.
    json_by_path = {s["path"]: s for s in manifest.get("json_schemas", [])}
    jsonl_by_path = {s["path"]: s for s in manifest.get("jsonl_schemas", [])}
    tabular_by_path = {s["path"]: s for s in manifest.get("tabular_schemas", [])}
    md_by_path = {s["path"]: s for s in manifest.get("markdown_outlines", [])}
    notebook_by_path = {s["path"]: s for s in manifest.get("notebook_outlines", [])}

    # 1) output_artifacts — one entry per primary runner output, in agent rank
    #    order, with the format-specific detail attached.
    output_artifacts: list[dict[str, Any]] = []
    for rank, path in enumerate(trim.primary_runner_outputs, start=1):
        file_entry = files_index.get(path, {})
        artifact: dict[str, Any] = {
            "path": path,
            "rank": rank,
            "format": file_entry.get("format", "unknown"),
            "size_bucket": file_entry.get("size_bucket"),
        }
        if path in json_by_path:
            artifact["schema"] = json_by_path[path]["schema"]
        if path in jsonl_by_path:
            jsonl = jsonl_by_path[path]
            artifact["record_schema"] = jsonl.get("record_schema")
            artifact["record_count_bucket"] = jsonl.get("record_count_bucket")
            artifact["sampled_records"] = jsonl.get("sampled_records")
        if path in tabular_by_path:
            tab = tabular_by_path[path]
            artifact["columns"] = tab.get("columns")
            artifact["row_count_bucket"] = tab.get("row_count_bucket")
        if path in md_by_path:
            artifact["outline"] = md_by_path[path]["headers"]
        if path in notebook_by_path:
            artifact["cells"] = notebook_by_path[path]["cells"]
        output_artifacts.append(artifact)

    # 2) producer_api — only signatures the agent explicitly nominated,
    #    grouped by file. Internal helpers the agent didn't pick are gone.
    sigs_by_path: dict[str, list[dict]] = {}
    for sig in manifest.get("python_signatures", []):
        sigs_by_path.setdefault(sig["path"], []).append(sig)

    producer_api: list[dict[str, Any]] = []
    for path, names in trim.producer_signatures.items():
        file_entry = files_index.get(path, {})
        wanted = set(names)
        kept_sigs = [
            {k: v for k, v in s.items() if k != "path"}
            for s in sigs_by_path.get(path, [])
            if s["name"] in wanted
        ]
        if not kept_sigs:
            continue
        producer_api.append({
            "path": path,
            "format": file_entry.get("format", "python"),
            "size_bucket": file_entry.get("size_bucket"),
            "signatures": kept_sigs,
        })

    return {
        "version": manifest.get("version", MANIFEST_VERSION),
        "workspace_basename": manifest.get("workspace_basename"),
        "curation": "trimmer_agent",
        "task_shape": trim.task_shape.as_dict(),
        "intent_summary": trim.intent_summary,
        "output_description": trim.output_description,
        "output_artifacts": output_artifacts,
        "producer_api": producer_api,
    }


# Pass 2: curate_manifest — the retry-with-feedback wrapper
#
# The trimmer agent is provider-side wiring; this module stays pure-library
# by accepting it as a callable. agents/manifest_trimmer.py supplies the
# concrete implementation.

TrimmerCallable = Callable[[dict, Path, Optional[str]], Any]


def curate_manifest(
    manifest: dict,
    work_dir: Path,
    trimmer: TrimmerCallable,
    max_retries: int = 3,
    verbose: bool = True,
) -> dict:
    """
    Run the trimmer agent under a validate-and-retry loop. On exhaustion,
    return the raw manifest with a curation marker so downstream code can
    detect the fallback explicitly.
    """
    last_error: Optional[str] = None

    for attempt in range(1, max_retries + 1):
        if verbose:
            prefix = f"  [trim attempt {attempt}/{max_retries}]"
            print(f"{prefix} invoking trimmer agent")

        try:
            raw_output = trimmer(manifest, work_dir, last_error)
        except Exception as e:
            last_error = f"trimmer raised: {type(e).__name__}: {e}"
            if verbose:
                print(f"  ↳ {last_error}")
            continue

        try:
            trim = parse_trim_decision(raw_output)
        except ManifestValidationError as e:
            last_error = f"schema: {e}"
            if verbose:
                print(f"  ↳ {last_error}")
            continue

        cross_errors = cross_validate(trim, manifest)
        if cross_errors:
            last_error = "cross: " + "; ".join(cross_errors)
            if verbose:
                print(f"  ↳ {last_error}")
            continue

        leak_errors = lint_for_leakage(trim)
        if leak_errors:
            last_error = "leak: " + "; ".join(leak_errors)
            if verbose:
                print(f"  ↳ {last_error}")
            continue

        if verbose:
            print(
                f"  ↳ accepted. primary outputs: {trim.primary_runner_outputs} "
                f"| producer_api: {list(trim.producer_signatures.keys())}"
            )
        result = apply_trim(manifest, trim)
        result["curation_attempts"] = attempt
        return result

    if verbose:
        print(
            f"⚠️  trimmer agent failed after {max_retries} attempts; "
            f"last error: {last_error}"
        )
        print("   Falling back to raw mechanical manifest.")
    return _fallback_curation(manifest, last_error)


def _fallback_curation(manifest: dict, last_error: Optional[str]) -> dict:
    """
    Emit a narrow-shape document with explicit fallback markers.

    The mechanical pass had no agent guidance, so it can't pick primary
    outputs or producer signatures. Surface the raw heuristics' best guess
    at likely_runner_outputs as candidate paths, leave producer_api empty,
    and mark task_shape/intent_summary/output_description as null. Downstream
    code can detect the fallback via curation == "mechanical_fallback".
    """
    candidate_outputs = [
        c["path"] for c in manifest.get("likely_runner_outputs", [])
    ]
    return {
        "version": manifest.get("version", MANIFEST_VERSION),
        "workspace_basename": manifest.get("workspace_basename"),
        "curation": "mechanical_fallback",
        "curation_fallback_reason": last_error,
        "curation_attempts": None,
        "task_shape": None,
        "intent_summary": None,
        "output_description": None,
        "output_artifacts": [],
        "producer_api": [],
        "candidate_output_paths": candidate_outputs,
    }


# CLI

def _cli(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Build a value-redacted structural manifest of a research workspace.",
    )
    parser.add_argument("work_dir", type=Path, help="Workspace directory to scan")
    parser.add_argument(
        "--out", type=Path, default=None,
        help="Write manifest to this path "
             "(default: <work_dir>/.neurico/bootstrap_manifest.json)",
    )
    parser.add_argument(
        "--stdout", action="store_true",
        help="Print manifest to stdout instead of writing a file.",
    )
    args = parser.parse_args(argv)

    manifest = build_manifest(args.work_dir)
    text = json.dumps(manifest, indent=2, sort_keys=False)

    if args.stdout:
        print(text)
        return 0

    out_path = args.out or (args.work_dir / ".neurico" / "bootstrap_manifest.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text + "\n", encoding="utf-8")
    print(f"Wrote manifest to {out_path}")
    print(f"  files: {len(manifest['files'])}")
    print(f"  likely runner outputs: {len(manifest['likely_runner_outputs'])}")
    print(f"  sweep rollups: {len(manifest['sweep_rollups'])}")
    print(f"  python signatures: {len(manifest['python_signatures'])}")
    print(f"  json schemas: {len(manifest['json_schemas'])}")
    print(f"  jsonl schemas: {len(manifest['jsonl_schemas'])}")
    print(f"  tabular schemas: {len(manifest['tabular_schemas'])}")
    print(f"  markdown outlines: {len(manifest['markdown_outlines'])}")
    print(f"  notebook outlines: {len(manifest['notebook_outlines'])}")
    print(f"  extraction warnings: {len(manifest['extraction_warnings'])}")
    print(f"  roles: {manifest['roles_summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
