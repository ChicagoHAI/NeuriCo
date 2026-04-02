"""
Cost estimation utilities for NeuriCo runs.

This module reads provider pricing from environment variables, extracts
token-usage hints from transcript JSONL files, and computes an estimated cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import os


PROVIDERS = ("claude", "codex", "gemini")


@dataclass
class ProviderPricing:
    """Per-provider pricing, USD per 1M tokens."""

    provider: str
    input_per_1m: Optional[float]
    output_per_1m: Optional[float]


@dataclass
class UsageTotals:
    """Extracted usage totals for a run."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


def _float_env(name: str) -> Optional[float]:
    """Read float env var, returning None if missing/invalid."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if value < 0:
        return None
    return value


def load_pricing_table() -> Dict[str, ProviderPricing]:
    """
    Load pricing from environment variables.

    Required format per provider:
      - NEURICO_COST_<PROVIDER>_INPUT_PER_1M
      - NEURICO_COST_<PROVIDER>_OUTPUT_PER_1M
    """
    table: Dict[str, ProviderPricing] = {}
    for provider in PROVIDERS:
        upper = provider.upper()
        table[provider] = ProviderPricing(
            provider=provider,
            input_per_1m=_float_env(f"NEURICO_COST_{upper}_INPUT_PER_1M"),
            output_per_1m=_float_env(f"NEURICO_COST_{upper}_OUTPUT_PER_1M"),
        )
    return table


def _as_int(value: Any) -> Optional[int]:
    """Convert supported numeric/string values to non-negative int."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        iv = int(value)
        return iv if iv >= 0 else None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if stripped.isdigit():
            return int(stripped)
    return None


def _find_usage_dicts(value: Any, out: List[Dict[str, Any]]) -> None:
    """Recursively collect dict nodes that look like token-usage blocks."""
    if isinstance(value, list):
        for item in value:
            _find_usage_dicts(item, out)
        return

    if not isinstance(value, dict):
        return

    usage_keys = {
        "usage",
        "input_tokens",
        "output_tokens",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    }
    if any(k in value for k in usage_keys):
        out.append(value)

    for nested in value.values():
        _find_usage_dicts(nested, out)


def _normalize_usage_block(block: Dict[str, Any]) -> UsageTotals:
    """Normalize a usage block across provider-specific key names."""
    # Some events wrap usage under "usage".
    if isinstance(block.get("usage"), dict):
        return _normalize_usage_block(block["usage"])

    input_tokens = (
        _as_int(block.get("input_tokens"))
        or _as_int(block.get("prompt_tokens"))
        or 0
    )
    output_tokens = (
        _as_int(block.get("output_tokens"))
        or _as_int(block.get("completion_tokens"))
        or 0
    )
    total_tokens = (
        _as_int(block.get("total_tokens"))
        or (input_tokens + output_tokens)
    )

    return UsageTotals(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def extract_usage_from_transcript(transcript_path: Path) -> UsageTotals:
    """
    Extract best-effort usage totals from a transcript JSONL file.

    Strategy:
    - Parse each JSON line.
    - Recursively find usage-like dicts.
    - Use max observed usage block values (common in streaming events).
    """
    path = Path(transcript_path)
    if not path.exists():
        return UsageTotals()

    max_input = 0
    max_output = 0
    max_total = 0

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue

            usage_blocks: List[Dict[str, Any]] = []
            _find_usage_dicts(payload, usage_blocks)
            for block in usage_blocks:
                normalized = _normalize_usage_block(block)
                max_input = max(max_input, normalized.input_tokens)
                max_output = max(max_output, normalized.output_tokens)
                max_total = max(max_total, normalized.total_tokens)
    # NOTE:
    # We assume streaming transcripts include cumulative usage counters
    # and take the maximum observed values per file.
    # This may undercount if transcripts emit only incremental usage.

    if max_total == 0:
        max_total = max_input + max_output

    return UsageTotals(
        input_tokens=max_input,
        output_tokens=max_output,
        total_tokens=max_total,
    )


def aggregate_usage(transcript_files: List[Path]) -> UsageTotals:
    """Aggregate usage totals across multiple transcript files."""
    total = UsageTotals()
    for file_path in transcript_files:
        usage = extract_usage_from_transcript(file_path)
        total.input_tokens += usage.input_tokens
        total.output_tokens += usage.output_tokens
        total.total_tokens += usage.total_tokens
    if total.total_tokens == 0:
        total.total_tokens = total.input_tokens + total.output_tokens
    return total


def estimate_cost_usd(usage: UsageTotals, pricing: ProviderPricing) -> Optional[float]:
    """Estimate USD cost from usage and pricing; returns None if unavailable."""
    if pricing.input_per_1m is None or pricing.output_per_1m is None:
        return None
    input_cost = (usage.input_tokens / 1_000_000) * pricing.input_per_1m
    output_cost = (usage.output_tokens / 1_000_000) * pricing.output_per_1m
    return input_cost + output_cost
