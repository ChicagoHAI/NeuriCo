"""Provider/model pricing helpers for NeuriCo usage tracking.

Values are USD per one million tokens. They are estimates based on public
provider pricing and can be overridden per provider family with environment
variables such as ``NEURICO_PRICE_GEMINI_INPUT_PER_M``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class TokenPrice:
    """USD price per one million tokens for one model/provider family."""

    input_per_million: float
    output_per_million: float
    cached_input_per_million: Optional[float] = None
    cache_write_per_million: Optional[float] = None
    source: str = "model"


MODEL_PRICES: Tuple[Tuple[str, Tuple[str, ...], TokenPrice], ...] = (
    (
        "gemini",
        ("gemini-2.5-pro",),
        TokenPrice(1.25, 10.00, 0.125, 1.25, "model"),
    ),
    (
        "gemini",
        ("gemini-2.5-flash-lite",),
        TokenPrice(0.10, 0.40, 0.01, 0.10, "model"),
    ),
    (
        "gemini",
        ("gemini-2.5-flash",),
        TokenPrice(0.30, 2.50, 0.03, 0.30, "model"),
    ),
    (
        "gemini",
        ("gemini-2.0-flash",),
        TokenPrice(0.10, 0.40, 0.025, 0.10, "model"),
    ),
)


def get_price(
    provider: str,
    model: Optional[str] = None,
    input_tokens: Optional[int] = None,
) -> Optional[TokenPrice]:
    """Return pricing for a known model, including environment overrides."""
    normalized = provider.lower()
    default = _match_model_price(normalized, model, input_tokens)
    if default is None:
        return None

    prefix = f"NEURICO_PRICE_{normalized.upper()}"
    input_price = _float_env(f"{prefix}_INPUT_PER_M", default.input_per_million)
    output_price = _float_env(f"{prefix}_OUTPUT_PER_M", default.output_per_million)
    cached_input_price = _optional_float_env(
        f"{prefix}_CACHED_INPUT_PER_M",
        default.cached_input_per_million,
    )
    cache_write_price = _optional_float_env(
        f"{prefix}_CACHE_WRITE_PER_M",
        default.cache_write_per_million,
    )
    return TokenPrice(
        input_per_million=input_price,
        output_per_million=output_price,
        cached_input_per_million=cached_input_price,
        cache_write_per_million=cache_write_price,
        source=default.source,
    )


def estimate_cost_usd(
    provider: str,
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    cached_input_tokens: Optional[int] = None,
    cache_creation_input_tokens: Optional[int] = None,
    model: Optional[str] = None,
) -> Optional[float]:
    """Estimate cost in USD from input/output/cache token counts."""
    if (
        input_tokens is None
        and output_tokens is None
        and cached_input_tokens is None
        and cache_creation_input_tokens is None
    ):
        return None

    price = get_price(provider, model=model, input_tokens=input_tokens)
    if price is None:
        return None

    input_count = input_tokens or 0
    output_count = output_tokens or 0
    cached_count = cached_input_tokens or 0
    cache_creation_count = cache_creation_input_tokens or 0
    regular_input_count = max(input_count - cached_count - cache_creation_count, 0)

    cached_price = price.cached_input_per_million
    if cached_price is None:
        cached_price = price.input_per_million

    cache_write_price = price.cache_write_per_million
    if cache_write_price is None:
        cache_write_price = price.input_per_million

    cost = (
        regular_input_count / 1_000_000 * price.input_per_million
        + cached_count / 1_000_000 * cached_price
        + cache_creation_count / 1_000_000 * cache_write_price
        + output_count / 1_000_000 * price.output_per_million
    )
    return round(cost, 6)


def _match_model_price(
    provider: str,
    model: Optional[str],
    input_tokens: Optional[int],
) -> Optional[TokenPrice]:
    if not model:
        return None
    normalized_model = _normalize_model_name(model)
    for price_provider, patterns, price in MODEL_PRICES:
        if price_provider != provider:
            continue
        if any(pattern in normalized_model for pattern in patterns):
            if provider == "gemini" and "gemini-2.5-pro" in patterns and (input_tokens or 0) > 200_000:
                return TokenPrice(2.50, 15.00, 0.25, 2.50, "model")
            return price
    return None


def _normalize_model_name(model: str) -> str:
    return model.lower().replace("_", "-")


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _optional_float_env(name: str, default: Optional[float]) -> Optional[float]:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default
