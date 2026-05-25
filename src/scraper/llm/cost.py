"""Claude pricing — input/output tokens per 1M with cache discounts.

Reference prices as of 2026:
- Claude Sonnet 4.6: $3/MTok input, $15/MTok output
- Claude Opus 4.7: $15/MTok input, $75/MTok output
- Claude Haiku 4.5: $0.80/MTok input, $4/MTok output
- Cache reads: 10% of input rate
- Cache writes: 125% of input rate (5min TTL)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int


@dataclass(frozen=True)
class ClaudeCost:
    input_usd: float
    output_usd: float
    cache_read_usd: float
    cache_write_usd: float

    @property
    def total_usd(self) -> float:
        return self.input_usd + self.output_usd + self.cache_read_usd + self.cache_write_usd


_PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-7": (15.0, 75.0),
    "claude-haiku-4-5-20251001": (0.80, 4.0),
}


def calculate_cost(model: str, usage: Usage) -> ClaudeCost:
    if model not in _PRICING_PER_MTOK:
        raise ValueError(f"Unknown model: {model}")
    input_rate, output_rate = _PRICING_PER_MTOK[model]
    cache_read_rate = input_rate * 0.10
    cache_write_rate = input_rate * 1.25

    return ClaudeCost(
        input_usd=usage.input_tokens / 1_000_000 * input_rate,
        output_usd=usage.output_tokens / 1_000_000 * output_rate,
        cache_read_usd=usage.cache_read_tokens / 1_000_000 * cache_read_rate,
        cache_write_usd=usage.cache_write_tokens / 1_000_000 * cache_write_rate,
    )
