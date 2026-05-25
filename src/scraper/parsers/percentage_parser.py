"""Parser for strings like 'Perú 65%, USA 35%' → {'Perú': 65.0, 'USA': 35.0}."""
from __future__ import annotations

import re

_PATTERN = re.compile(
    r"""
    ^\s*
    (?P<label>[^,\n(][^,\n(]*?)         # etiqueta: texto hasta coma/paren/newline
    [\s(]*                              # espacios y/o paréntesis
    (?P<value>\d+(?:\.\d+)?)            # número con decimal opcional
    \s*%\)?                             # %  y paréntesis de cierre opcional
    \s*$
    """,
    re.VERBOSE,
)


class PercentageSumError(ValueError):
    """Raised when parsed percentages don't sum close to 100%."""


def parse_percentages(
    raw: str | None,
    *,
    strict_sum: bool = False,
    tolerance: float = 5.0,
) -> dict[str, float]:
    """Parse 'Label N%, Label N%' (comma- or newline-separated) into a dict.

    Handles variations:
    - 'Perú 65%, USA 35%'
    - 'EEUU (100%)'
    - 'A 62.44%\\nB 21.78%\\nC 15.06%'

    Args:
        raw: Input string. None or empty returns {}.
        strict_sum: If True, raises PercentageSumError when sum is outside 100 ± tolerance.
        tolerance: Allowed deviation from 100% (in percentage points).
    """
    if not raw or not isinstance(raw, str) or raw.strip().lower() in ("nan", "none"):
        return {}

    segments = re.split(r"[,\n]", raw)
    result: dict[str, float] = {}
    for segment in segments:
        segment_stripped = segment.strip()
        if not segment_stripped:
            continue
        m = _PATTERN.match(segment_stripped)
        if not m:
            continue
        label = m.group("label").strip().rstrip(":").strip()
        value = float(m.group("value"))
        if label:
            result[label] = value

    if strict_sum and result:
        total = sum(result.values())
        if abs(total - 100.0) > tolerance:
            raise PercentageSumError(
                f"Percentages sum to {total}, expected 100 ± {tolerance}. Input: {raw!r}"
            )

    return result
