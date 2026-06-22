from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from core.trajectory_data.raw.scanner import (
    DiscoveredFile,
    discover_repositories,
    iter_repository_files,
)
from core.trajectory_data.raw.structured_parser import (
    canonical_type,
    parse_structured_file,
)


@dataclass
class FileStats:
    """Schema-audit summary for one structured file."""

    repo_name: str
    relative_path: str
    source_family: str
    suffix: str | None
    size_bytes: int
    sha256: str
    parse_status: str
    record_count: int = 0
    parse_error_count: int = 0
    top_level_type: str | None = None


@dataclass
class AttributeStats:
    """Observed type/count/examples for one attribute path."""

    path: str
    file_count: int = 0
    record_count: int = 0
    type_counts: Counter[str] = field(default_factory=Counter)
    examples: list[str] = field(default_factory=list)

    def add(
        self,
        *,
        value_type: str,
        example: str,
        max_examples: int = 3,
    ) -> None:
        self.record_count += 1
        self.type_counts[value_type] += 1

        if example and example not in self.examples and len(self.examples) < max_examples:
            self.examples.append(example)


def utc_now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for schema audit."""
    parser = argparse.ArgumentParser(
        description="Audit structured raw evidence schemas across NeuriCo repositories."
    )

    parser.add_argument(
        "--repos-root",
        type=Path,
        required=True,
        help="Directory whose immediate child directories are generated repositories.",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for audit CSV/JSON outputs.",
    )

    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Only include structured files whose relative path contains this substring. Repeatable.",
    )

    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Exclude structured files whose relative path contains this substring. Repeatable.",
    )

    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Optional maximum number of structured files to audit.",
    )

    parser.add_argument(
        "--store-scalars",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Include scalar raw records in raw_records.jsonl audit output.",
    )

    return parser.parse_args()


def matches_patterns(
    text: str,
    patterns: Iterable[str],
) -> bool:
    """Return whether any substring pattern appears in text."""
    return any(pattern in text for pattern in patterns)


def compact_example(value: Any, *, max_chars: int = 200) -> str:
    """Convert a value to a compact example string."""
    if isinstance(value, str):
        rendered = value
    else:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)

    rendered = " ".join(rendered.split())

    if len(rendered) > max_chars:
        return rendered[: max_chars - 3] + "..."

    return rendered


def walk_attributes(
    value: Any,
    *,
    prefix: str = "$",
) -> Iterable[tuple[str, Any]]:
    """Yield JSON-path-like attribute paths and leaf/container values."""
    yield prefix, value

    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{prefix}.{key}"
            yield from walk_attributes(child, prefix=child_path)

    elif isinstance(value, list):
        for child in value:
            child_path = f"{prefix}[]"
            yield from walk_attributes(child, prefix=child_path)


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    fieldnames: list[str],
) -> None:
    """Write rows to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def discover_structured_files(args: argparse.Namespace) -> list[DiscoveredFile]:
    """
    Discover structured files using the production scanner.
    """
    repositories = discover_repositories(args.repos_root)
    discovered_structured_files: list[DiscoveredFile] = []

    for repository in repositories:
        for discovered_file in iter_repository_files(repository):
            if not discovered_file.is_structured:
                continue

            if args.include and not matches_patterns(discovered_file.relative_path, args.include):
                continue

            if args.exclude and matches_patterns(discovered_file.relative_path, args.exclude):
                continue

            discovered_structured_files.append(discovered_file)

    if args.max_files is not None:
        discovered_structured_files = discovered_structured_files[: args.max_files] 

    return discovered_structured_files


def audit_structured_files(
    discovered_structured_files: list[DiscoveredFile],
    *,
    store_scalars: bool,
    output_dir: Path,
) -> dict[str, Any]:
    """Audit structured file shapes and write outputs."""
    output_dir.mkdir(parents=True, exist_ok=True)

    file_rows: list[dict[str, Any]] = []
    attribute_stats: dict[str, AttributeStats] = {}
    attribute_files: dict[str, set[str]] = defaultdict(set)

    raw_records_path = output_dir / "raw_records.jsonl"
    parse_errors_path = output_dir / "parse_errors.jsonl"

    total_records = 0
    malformed_records = 0
    files_parsed_ok = 0
    files_with_errors = 0

    with raw_records_path.open("w", encoding="utf-8") as raw_out, parse_errors_path.open(
        "w",
        encoding="utf-8",
    ) as errors_out:
        for file_index, discovered_file in enumerate(discovered_structured_files, start=1):  
            result = parse_structured_file(discovered_file.absolute_path)  

            file_stats = FileStats(
                repo_name=discovered_file.repo_name,  
                relative_path=discovered_file.relative_path,
                source_family=discovered_file.source_family,  
                suffix=discovered_file.suffix,
                size_bytes=discovered_file.size_bytes,
                sha256=discovered_file.sha256,  
                parse_status=result.status,
                record_count=len(result.records),
                parse_error_count=len(result.errors),
                top_level_type=result.top_level_type,
            )

            if result.errors:
                files_with_errors += 1
            else:
                files_parsed_ok += 1

            for parsed_error in result.errors:
                malformed_records += 1
                errors_out.write(
                    json.dumps(
                        {
                            "repo_name": discovered_file.repo_name,
                            "relative_path": discovered_file.relative_path,
                            "source_line": parsed_error.source_line,
                            "error_type": parsed_error.error_type,
                            "error_message": parsed_error.error_message,
                            "raw_excerpt": parsed_error.raw_excerpt,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

            for record in result.records:
                total_records += 1

                value_for_inventory = (
                    record.payload
                    if record.payload is not None
                    else record.raw_text
                )

                should_store_record = isinstance(value_for_inventory, (dict, list)) or store_scalars

                if should_store_record:
                    raw_out.write(
                        json.dumps(
                            {
                                "repo_name": discovered_file.repo_name,
                                "relative_path": discovered_file.relative_path,
                                "record_index": record.record_index,
                                "source_line": record.source_line,
                                "record_format": record.record_format,
                                "record_type": record.record_type,
                                "payload": record.payload,
                                "raw_text": record.raw_text,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )

                if not isinstance(value_for_inventory, (dict, list)):
                    continue

                for attr_path, attr_value in walk_attributes(value_for_inventory):
                    if attr_path not in attribute_stats:
                        attribute_stats[attr_path] = AttributeStats(path=attr_path)

                    value_type = canonical_type(attr_value)
                    example = compact_example(attr_value)

                    attribute_stats[attr_path].add(
                        value_type=value_type,
                        example=example,
                    )

                    attribute_files[attr_path].add(
                        f"{discovered_file.repo_name}/{discovered_file.relative_path}"
                    )

            file_rows.append(
                {
                    "repo_name": file_stats.repo_name,
                    "relative_path": file_stats.relative_path,
                    "source_family": file_stats.source_family,
                    "suffix": file_stats.suffix,
                    "size_bytes": file_stats.size_bytes,
                    "sha256": file_stats.sha256,
                    "parse_status": file_stats.parse_status,
                    "record_count": file_stats.record_count,
                    "parse_error_count": file_stats.parse_error_count,
                    "top_level_type": file_stats.top_level_type,
                }
            )

            if file_index % 100 == 0:
                print(f"Audited {file_index}/{len(discovered_structured_files)} structured files")

    attribute_rows: list[dict[str, Any]] = []

    for attr_path, stats in sorted(attribute_stats.items()):
        stats.file_count = len(attribute_files[attr_path])

        attribute_rows.append(
            {
                "path": stats.path,
                "file_count": stats.file_count,
                "record_count": stats.record_count,
                "type_counts_json": json.dumps(dict(stats.type_counts), sort_keys=True),
                "examples_json": json.dumps(stats.examples, ensure_ascii=False),
            }
        )

    write_csv(
        output_dir / "files.csv",
        file_rows,
        fieldnames=[
            "repo_name",
            "relative_path",
            "source_family",
            "suffix",
            "size_bytes",
            "sha256",
            "parse_status",
            "record_count",
            "parse_error_count",
            "top_level_type",
        ],
    )

    write_csv(
        output_dir / "attributes.csv",
        attribute_rows,
        fieldnames=[
            "path",
            "file_count",
            "record_count",
            "type_counts_json",
            "examples_json",
        ],
    )

    summary = {
        "generated_at": utc_now_iso(),
        "structured_files_discovered": len(discovered_structured_files),
        "files_parsed_ok": files_parsed_ok,
        "files_with_errors": files_with_errors,
        "records_preserved": total_records,
        "malformed_records": malformed_records,
        "unique_attribute_paths": len(attribute_stats),
        "outputs": {
            "files_csv": str(output_dir / "files.csv"),
            "attributes_csv": str(output_dir / "attributes.csv"),
            "raw_records_jsonl": str(raw_records_path),
            "parse_errors_jsonl": str(parse_errors_path),
        },
    }

    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return summary


def main() -> None:
    args = parse_args()

    discovered_structured_files = discover_structured_files(args) 

    summary = audit_structured_files(
        discovered_structured_files,
        store_scalars=args.store_scalars,
        output_dir=args.output_dir.expanduser().resolve(),
    )

    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()