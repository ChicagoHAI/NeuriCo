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
        


    
