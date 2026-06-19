from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None


SUPPORTED_SUFFIXES = {".json", ".jsonl", ".yaml", ".yml"}

@dataclass(frozen=True)
class ParsedRecord:
    """
    One raw record extracted from a structured source file.
    """
    record_index: int
    source_line: int | None
    record_format: str
    record_type: str
    payload: Any | None = None
    raw_text: str | None = None

@dataclass(frozen=True)
class ParsedError:
    """
    One parsing issue associated with a source file or line.
    """
    source_line: int | None
    error_type: str
    error_message: str
    raw_excerpt: str | None = None


@dataclass
class ParseResult:
    """
    Complete result of attempting to parse one structured file.
    """
    top_level_type: str | None = None
    records: list[ParsedRecord] = field(default_factory=list)
    errors: list[ParsedError] = field(default_factory=list)
    @property
    def status(self) -> str:
        if self.errors and self.records:
            return "partial"
        if self.errors:
            return "error"
        return "ok"
    
def canonical_type(value: Any) -> str:
    """
    Map Python values to stable JSON-like type names.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
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

def parse_json(path: Path) -> ParseResult:
    """
    Parse a conventional JSON file.
    A top-level array becomes one raw record per array item. Other
    top-level values become one raw record.
    """
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    result = ParseResult(top_level_type=canonical_type(payload))
    values = payload if isinstance(payload, list) else [payload]
    for record_index, value in enumerate(values):
        result.records.append(ParsedRecord(
            record_index=record_index,
            source_line=None,
            record_format="json",
            record_type=canonical_type(value),
            payload=value,
        ))
    return result

def parse_jsonl(path: Path, *, preserve_malformed_lines: bool = True) -> ParseResult:
    """
    Parse a JSON Lines file.
    Physical source_line numbers are preserved. Blank lines are skipped.
    Malformed non-empty lines are:
    - recorded as parse errors;
    - optionally preserved as raw plain-text records.
    """
    result = ParseResult(top_level_type="jsonl")
    record_index = 0
    with path.open(
        "r",
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                result.errors.append(
                    ParsedError(
                        source_line=line_number,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                        raw_excerpt=stripped[:1000],
                    )
                )
                if preserve_malformed_lines:
                    result.records.append(
                        ParsedRecord(
                            record_index=record_index,
                            source_line=line_number,
                            record_format="plain_text",
                            record_type="string",
                            payload=None,
                            raw_text=stripped,
                        )
                    )
                    record_index += 1
                continue
            result.records.append(
                ParsedRecord(
                    record_index=record_index,
                    source_line=line_number,
                    record_format="jsonl",
                    record_type=canonical_type(payload),
                    payload=payload,
                )
            )
            record_index += 1
        return result
    
def parse_yaml(path: Path) -> ParseResult:
    """
    Parse one or more YAML docs.
    """
    if yaml is None:
        return ParseResult(
            errors=[
                ParsedError(
                    source_line=None,
                    error_type="MissingDependency",
                    error_message=(
                        "PyYAML is required to parse YAML files."
                        "Install it with `python -m pip install pyyaml`."
                    ),
                )
            ]
        )
    try:
        with path.open("r", encoding="utf-8") as handle:
            documents = [
                document
                for document in yaml.safe_load_all(handle)
                if document is not None
            ]
    except Exception as exc:
        problem_line = getattr(getattr(exc, "problem_mark", None), "line", None)
        source_line = problem_line + 1 if problem_line is not None else None 
        return ParseResult(
            errors=[
                ParsedError(
                    source_line=source_line,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            ]
        )
    top_level_type = (
        canonical_type(documents[0])
        if len(documents) == 1
        else "yaml_documents"
    )

    result = ParseResult(top_level_type=top_level_type)
    for record_index, document in enumerate(documents):
        result.records.append(
            ParsedRecord(
                record_index=record_index,
                source_line=None,
                record_format="yaml",
                record_type=canonical_type(document),
                payload=document,
            )
        )
    return result




def parse_structured_file(path: Path) -> ParseResult:
    """
    Parse one supported structured file.
    Some historical files use a `.json` extension while containing JSONL.
    Therefore a failed conventional JSON parse is followed by a JSONL attempt.
    """
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            return parse_json(path)
        except json.JSONDecodeError as json_error:
            jsonl_result = parse_jsonl(
                path,
                preserve_malformed_lines=False,
            )
            if jsonl_result.records and not jsonl_result.errors:
                jsonl_result.top_level_type = "jsonl_in_json_file"
                return jsonl_result
            return ParseResult(
                errors=[
                    ParsedError(
                        source_line=getattr(json_error, "lineno", None),
                        error_type=type(json_error).__name__,
                        error_message=str(json_error),
                    )
                ]
            )
        except (OSError, UnicodeError) as exc:
            return ParseResult(
                errors=[
                    ParsedError(
                        source_line=None,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                ]
            )
    if suffix == ".jsonl":
        try:
            return parse_jsonl(path)
        except (OSError, UnicodeError) as exc:
            return ParseResult(
                errors=[
                    ParsedError(
                        source_line=None,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                ]
            )
    if suffix in {".yaml", ".yml"}:
        return parse_yaml(path)
    raise ValueError(f"Unsupported structured file suffix: {suffix}")
        


    

    

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


def iter_json_records(path: Path) -> tuple[str, list[Any], list[dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    top_type = canonical_type(payload)

    if isinstance(payload, list):
        records = [
            {
                "source_line": None,
                "record_format": "json",
                "payload": item,
            }
            for item in payload
        ]
    else:
        records = [
            {
                "source_line": None,
                "record_format": "json",
                "payload": payload,
            }
        ]

    return top_type, records, []


def iter_jsonl_records(path: Path, *, preserve_plain_text: bool = True) -> tuple[str, list[Any], list[dict[str, Any]]]:
    records: list[Any] = []
    errors: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            try:
                payload = json.loads(stripped)
                records.append(
                    {
                        "source_line": line_number,
                        "record_format": "json",
                        "payload": payload,
                    }
                )
            except json.JSONDecodeError as exc:
                if preserve_plain_text:
                    records.append(
                        {
                            "source_line": line_number,
                            "record_format": "plain_text",
                            "payload": {
                                "text": stripped,
                            },
                        }
                    )
                else:
                    errors.append(
                        {
                            "line_number": line_number,
                            "error": str(exc),
                            "raw_line": stripped[:1000],
                        }
                    )
    return "mixed_jsonl", records, errors


def iter_yaml_records(path: Path) -> tuple[str, list[Any], list[dict[str, Any]]]:
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required for YAML files. Install it with: "
            "python3 -m pip install pyyaml"
        )

    with path.open("r", encoding="utf-8") as handle:
        documents = [
            document 
            for document in yaml.safe_load_all(handle) 
            if document is not None
        ]
    top_type = (
        canonical_type(documents[0])
        if len(documents) == 1
        else "yaml_documents"
    )
    records = [
        {
            "source_line": None,
            "record_format": "yaml",
            "payload": document,
        }
        for document in documents
    ]
    return top_type, records, []


def parse_file(path: Path) -> tuple[str, list[Any], list[dict[str, Any]]]:
    suffix = path.suffix.lower()

    if suffix == ".json":
        try:
            return iter_json_records(path)
        except json.JSONDecodeError as json_error:
            top_type, records, errors = iter_jsonl_records(
                path,
                preserve_plain_text=False,
            )
            if records:
                return "jsonl_in_json_file", records, errors
            raise json_error
    if suffix == ".jsonl":
        return iter_jsonl_records(path)
    if suffix in {".yaml", ".yml"}:
        return iter_yaml_records(path)

    raise ValueError(f"Unsupported suffix: {suffix}")


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

    discovered = discover_files(
        repos_root,
        include_patterns=args.include,
        exclude_patterns=args.exclude,
    )

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
                top_type, records, errors = parse_file(path)
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
            