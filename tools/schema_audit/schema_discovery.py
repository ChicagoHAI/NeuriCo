from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from core.trajectory_data.raw.scanner import (
    discover_repositories,
    iter_repository_files,
)

from core.trajectory_data.raw.structured_parser import (
    canonical_type,
    parse_structured_file,
)
try:
    import yaml  # type: ignore
except ImportError:
    yaml = None


SUPPORTED_SUFFIXES = {".json", ".jsonl", ".yaml", ".yml"}
SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
}
MAX_EXAMPLES_PER_ATTRIBUTE = 5
MAX_EXAMPLE_CHARS = 240


@dataclass
class FileStats:
    repo_name: str
    relative_path: str
    suffix: str
    size_bytes: int
    sha256: str
    source_family: str
    parse_status: str = "ok"
    top_level_type: str = ""
    record_count: int = 0
    malformed_record_count: int = 0
    attribute_count: int = 0
    error: str = ""


@dataclass
class AttributeStats:
    repo_name: str
    relative_path: str
    source_family: str
    attribute_path: str
    occurrences: int = 0
    null_count: int = 0
    type_counts: Counter[str] = field(default_factory=Counter)
    examples: list[str] = field(default_factory=list)

    def observe(self, value: Any) -> None:
        self.occurrences += 1
        value_type = canonical_type(value)
        self.type_counts[value_type] += 1
        if value is None:
            self.null_count += 1

        example = compact_example(value)
        if (
            example
            and example not in self.examples
            and len(self.examples) < MAX_EXAMPLES_PER_ATTRIBUTE
        ):
            self.examples.append(example)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Discover and preserve all attributes in JSON, JSONL, YAML, and YML "
            "files across QIAO-Bench pilot repositories."
        )
    )
    parser.add_argument(
        "--repos-root",
        type=Path,
        default=Path.home() / "qiao-bench" / "pilot-repos",
        help="Directory whose immediate children are repository directories.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.home() / "qiao-bench" / "schema-audit",
        help="Directory for parser outputs.",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help=(
            "Optional glob pattern relative to each repo. Repeatable. "
            "Example: --include 'logs/*.jsonl'"
        ),
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help=(
            "Optional glob pattern relative to each repo. Repeatable. "
            "Example: --exclude 'papers/**'"
        ),
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Optional maximum number of structured files to parse.",
    )
    parser.add_argument(
        "--store-scalars",
        action="store_true",
        help=(
            "Store top-level scalar JSON/YAML values as raw records. "
            "By default, only dict/list records are written."
        ),
    )
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def compact_example(value: Any) -> str:
    try:
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            rendered = str(value)
    except Exception:
        rendered = repr(value)

    rendered = rendered.replace("\n", "\\n")
    if len(rendered) > MAX_EXAMPLE_CHARS:
        rendered = rendered[: MAX_EXAMPLE_CHARS - 3] + "..."
    return rendered


def matches_patterns(relative_path: str, patterns: list[str]) -> bool:
    rel = Path(relative_path)
    return any(rel.match(pattern) for pattern in patterns)


def normalize_path(parent: str, key: str) -> str:
    return f"{parent}.{key}" if parent else key


def walk_attributes(
    value: Any,
    path: str = "$",
) -> Iterable[tuple[str, Any]]:
    """
    Yield every attribute path and value.

    Arrays are generalized with [] so that:
      $.items[0].type
      $.items[1].type
    both become:
      $.items[].type
    """
    yield path, value

    if isinstance(value, dict):
        for key, child in value.items():
            child_path = normalize_path(path, str(key))
            yield from walk_attributes(child, child_path)

    elif isinstance(value, list):
        array_path = f"{path}[]"
        for child in value:
            yield from walk_attributes(child, array_path)

def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    args = parse_args()
    repos_root = args.repos_root.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not repos_root.exists():
        raise FileNotFoundError(f"Repositories root does not exist: {repos_root}")

    repositories = discover_repositories(
        repos_root,
    )

    discovered_structured_files = []
    for repository in repositories:
        for discovered_file in iter_repository_files(repository):
            if discovered_file.is_structured:
                discovered_structured_files.append(discovered_file)

    if args.max_files is not None:
        discovered = discovered[: args.max_files]

    raw_records_path = output_dir / "raw_records.jsonl"
    parse_errors_path = output_dir / "parse_errors.jsonl"

    file_rows: list[dict[str, Any]] = []
    attribute_stats: dict[tuple[str, str, str], AttributeStats] = {}
    global_attribute_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "occurrences": 0,
            "repos": set(),
            "files": set(),
            "source_families": set(),
            "type_counts": Counter(),
            "examples": [],
        }
    )

    total_records = 0
    total_malformed = 0

    with raw_records_path.open("w", encoding="utf-8") as raw_out, \
         parse_errors_path.open("w", encoding="utf-8") as error_out:

        for file_index, (repo_name, path, relative_path) in enumerate(discovered, start=1):
            family = source_family(relative_path)
            stats = FileStats(
                repo_name=repo_name,
                relative_path=relative_path,
                suffix=path.suffix.lower(),
                size_bytes=path.stat().st_size,
                sha256=sha256_file(path),
                source_family=family,
            )

            try:
                result = parse_structured_file(
                    discovered_file.absolute_path
                )

                top_type = result.top_level_type
                records = result.records
                errors = result.errors
                for record in result.records:
                    payload = record.payload
                    source_line = record.source_line
                    record_format = record.record_format

                stats.top_level_type = top_type
                stats.record_count = len(records)
                stats.malformed_record_count = len(errors)

                for error in errors:
                    error_out.write(
                        json.dumps(
                            {
                                "repo_name": repo_name,
                                "relative_path": relative_path,
                                "source_family": family,
                                **error,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )

                total_malformed += len(errors)

                unique_paths_in_file: set[str] = set()

                for record_index, record_container in enumerate(records):
                    payload = record_container["payload"]
                    source_line = record_container.get("source_line")
                    record_format = record_container.get("record_format")
                    is_structured = isinstance(payload, (dict, list))
                    if is_structured or args.store_scalars:
                        raw_out.write(
                            json.dumps(
                                {
                                    "repo_name": repo_name,
                                    "relative_path": relative_path,
                                    "source_family": family,
                                    "record_index": record_index,
                                    "source_line": source_line,
                                    "record_format": record_format,
                                    "record_type": canonical_type(payload),
                                    "raw_payload": payload,
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )

                    total_records += 1

                    for attr_path, value in walk_attributes(payload):
                        unique_paths_in_file.add(attr_path)
                        key = (repo_name, relative_path, attr_path)

                        if key not in attribute_stats:
                            attribute_stats[key] = AttributeStats(
                                repo_name=repo_name,
                                relative_path=relative_path,
                                source_family=family,
                                attribute_path=attr_path,
                            )
                        attribute_stats[key].observe(value)

                        global_stat = global_attribute_stats[attr_path]
                        global_stat["occurrences"] += 1
                        global_stat["repos"].add(repo_name)
                        global_stat["files"].add(f"{repo_name}/{relative_path}")
                        global_stat["source_families"].add(family)
                        global_stat["type_counts"][canonical_type(value)] += 1

                        example = compact_example(value)
                        if (
                            example
                            and example not in global_stat["examples"]
                            and len(global_stat["examples"]) < MAX_EXAMPLES_PER_ATTRIBUTE
                        ):
                            global_stat["examples"].append(example)

                stats.attribute_count = len(unique_paths_in_file)

            except Exception as exc:
                stats.parse_status = "error"
                stats.error = f"{type(exc).__name__}: {exc}"
                error_out.write(
                    json.dumps(
                        {
                            "repo_name": repo_name,
                            "relative_path": relative_path,
                            "source_family": family,
                            "error": stats.error,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

            file_rows.append(
                {
                    "repo_name": stats.repo_name,
                    "relative_path": stats.relative_path,
                    "suffix": stats.suffix,
                    "size_bytes": stats.size_bytes,
                    "sha256": stats.sha256,
                    "source_family": stats.source_family,
                    "parse_status": stats.parse_status,
                    "top_level_type": stats.top_level_type,
                    "record_count": stats.record_count,
                    "malformed_record_count": stats.malformed_record_count,
                    "attribute_count": stats.attribute_count,
                    "error": stats.error,
                }
            )

            print(
                f"[{file_index}/{len(discovered)}] "
                f"{repo_name}/{relative_path}: {stats.parse_status}"
            )

    attribute_rows: list[dict[str, Any]] = []
    for stat in sorted(
        attribute_stats.values(),
        key=lambda x: (x.repo_name, x.relative_path, x.attribute_path),
    ):
        attribute_rows.append(
            {
                "repo_name": stat.repo_name,
                "relative_path": stat.relative_path,
                "source_family": stat.source_family,
                "attribute_path": stat.attribute_path,
                "occurrences": stat.occurrences,
                "null_count": stat.null_count,
                "null_rate": (
                    round(stat.null_count / stat.occurrences, 6)
                    if stat.occurrences
                    else 0.0
                ),
                "type_counts_json": json.dumps(
                    dict(sorted(stat.type_counts.items())),
                    ensure_ascii=False,
                ),
                "examples_json": json.dumps(stat.examples, ensure_ascii=False),
            }
        )

    total_repos = len({repo_name for repo_name, _, _ in discovered})
    global_rows: list[dict[str, Any]] = []

    for attr_path, stat in sorted(global_attribute_stats.items()):
        repos_present = len(stat["repos"])
        global_rows.append(
            {
                "attribute_path": attr_path,
                "occurrences": stat["occurrences"],
                "repos_present": repos_present,
                "repo_coverage_rate": (
                    round(repos_present / total_repos, 6)
                    if total_repos
                    else 0.0
                ),
                "files_present": len(stat["files"]),
                "source_families_json": json.dumps(
                    sorted(stat["source_families"]),
                    ensure_ascii=False,
                ),
                "type_counts_json": json.dumps(
                    dict(sorted(stat["type_counts"].items())),
                    ensure_ascii=False,
                ),
                "examples_json": json.dumps(
                    stat["examples"],
                    ensure_ascii=False,
                ),
            }
        )

    write_csv(
        output_dir / "file_manifest.csv",
        file_rows,
        [
            "repo_name",
            "relative_path",
            "suffix",
            "size_bytes",
            "sha256",
            "source_family",
            "parse_status",
            "top_level_type",
            "record_count",
            "malformed_record_count",
            "attribute_count",
            "error",
        ],
    )

    write_csv(
        output_dir / "attribute_inventory.csv",
        attribute_rows,
        [
            "repo_name",
            "relative_path",
            "source_family",
            "attribute_path",
            "occurrences",
            "null_count",
            "null_rate",
            "type_counts_json",
            "examples_json",
        ],
    )

    write_csv(
        output_dir / "global_attribute_inventory.csv",
        global_rows,
        [
            "attribute_path",
            "occurrences",
            "repos_present",
            "repo_coverage_rate",
            "files_present",
            "source_families_json",
            "type_counts_json",
            "examples_json",
        ],
    )

    summary = {
        "generated_at": utc_now(),
        "repos_root": str(repos_root),
        "output_dir": str(output_dir),
        "repositories_scanned": total_repos,
        "structured_files_discovered": len(discovered),
        "files_parsed_ok": sum(row["parse_status"] == "ok" for row in file_rows),
        "files_with_errors": sum(row["parse_status"] != "ok" for row in file_rows),
        "records_preserved": total_records,
        "malformed_records": total_malformed,
        "unique_attribute_paths": len(global_attribute_stats),
        "outputs": {
            "file_manifest": str(output_dir / "file_manifest.csv"),
            "attribute_inventory": str(output_dir / "attribute_inventory.csv"),
            "global_attribute_inventory": str(
                output_dir / "global_attribute_inventory.csv"
            ),
            "raw_records": str(raw_records_path),
            "parse_errors": str(parse_errors_path),
        },
    }

    with (output_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print("\nSchema discovery complete")
    print("=" * 32)
    print(f"Repositories scanned:       {summary['repositories_scanned']}")
    print(f"Structured files found:     {summary['structured_files_discovered']}")
    print(f"Files parsed successfully:  {summary['files_parsed_ok']}")
    print(f"Files with errors:          {summary['files_with_errors']}")
    print(f"Records preserved:          {summary['records_preserved']}")
    print(f"Malformed records:          {summary['malformed_records']}")
    print(f"Unique attribute paths:     {summary['unique_attribute_paths']}")
    print(f"Output directory:           {output_dir}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
            