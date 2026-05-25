"""Loader for config/sabbi_overlay.yaml."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from scraper.overlay.types import SabbiOverlay

_OVERLAY_PATH = Path(__file__).resolve().parents[3] / "config" / "sabbi_overlay.yaml"


@lru_cache(maxsize=1)
def load_sabbi_overlay() -> SabbiOverlay:
    """Parse config/sabbi_overlay.yaml into a SabbiOverlay pydantic model."""
    if not _OVERLAY_PATH.exists():
        return SabbiOverlay()
    with open(_OVERLAY_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return SabbiOverlay(**data)


def reload_sabbi_overlay() -> None:
    """Clear the lru_cache so load_sabbi_overlay() re-reads the file."""
    load_sabbi_overlay.cache_clear()


def apply_overlay_defaults(
    attributes: dict,
    overlay: SabbiOverlay,
    choice: str | None,
) -> dict:
    """Return a new attributes dict with overlay defaults filling in None values.

    Only fills attributes that are None. Does NOT override existing values.
    choice selects which overlay section to use (e.g. 'via_sabbi_brokerage').
    """
    result = dict(attributes)
    if choice is None:
        return result
    section = getattr(overlay, choice, None)
    if section is None:
        return result

    for field_name in ("administrador", "gestor", "comision"):
        if result.get(field_name) is None:
            default_value = getattr(section, field_name, None)
            if default_value is not None:
                result[field_name] = default_value
    return result
