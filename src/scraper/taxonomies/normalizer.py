"""Normalize taxonomy variants to canonical values.

Strategy:
1. Try exact match against canonical taxonomy (case-insensitive, accent-insensitive)
2. Try known variants dict
3. Try rapidfuzz fuzzy match above threshold 85
4. Return None if no match
"""
from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process

from scraper.taxonomies.loader import (
    load_asset_classes,
    load_canonical_assets,
    load_regions,
)

_THIS_DIR = Path(__file__).parent
_VARIANTS_FILE = _THIS_DIR / "normalizer_variants.yaml"
_FUZZY_THRESHOLD = 85.0


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _normalize_key(s: str) -> str:
    return _strip_accents(s.lower().strip())


@lru_cache(maxsize=1)
def _load_variants() -> dict:
    with open(_VARIANTS_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_canonical_lookup(canonical_names: tuple[str, ...]) -> dict[str, str]:
    """Index from normalized key → original canonical form."""
    return {_normalize_key(n): n for n in canonical_names}


def _normalize_via_table(
    raw: str,
    canonical_names: tuple[str, ...],
    variants: dict[str, str],
) -> str | None:
    """1. exact-normalized match, 2. known variants, 3. fuzzy match."""
    if not raw:
        return None

    key = _normalize_key(raw)
    canon_lookup = _build_canonical_lookup(canonical_names)

    # 1. Exact canonical
    if key in canon_lookup:
        return canon_lookup[key]

    # 2. Known variants
    if key in variants:
        return variants[key]

    # 3. Fuzzy against canonical + variants
    candidates = list(canon_lookup.keys()) + list(variants.keys())
    match = process.extractOne(key, candidates, scorer=fuzz.ratio)
    if match is None:
        return None
    matched_key, score, _ = match
    if score < _FUZZY_THRESHOLD:
        return None
    if matched_key in canon_lookup:
        return canon_lookup[matched_key]
    return variants[matched_key]


def normalize_asset_class(raw: str) -> str | None:
    variants_all = _load_variants()
    variants = {_normalize_key(k): v for k, v in variants_all["asset_class_variants"].items()}
    canonical_names = tuple(c.name for c in load_asset_classes())
    return _normalize_via_table(raw, canonical_names, variants)


def normalize_region(raw: str) -> str | None:
    variants_all = _load_variants()
    variants = {_normalize_key(k): v for k, v in variants_all["region_variants"].items()}
    canonical_names = tuple(r.name for r in load_regions())
    return _normalize_via_table(raw, canonical_names, variants)


def normalize_subyacente(raw: str) -> str | None:
    variants_all = _load_variants()
    raw_variants = variants_all.get("subyacente_variants") or {}
    variants = {_normalize_key(k): v for k, v in raw_variants.items()}
    canonical_names = tuple(a.name for a in load_canonical_assets())
    return _normalize_via_table(raw, canonical_names, variants)


def normalize_percentage_dict_asset_class(raw: dict[str, float]) -> dict[str, float]:
    """Normalize keys to canonical asset class names. Drop unknowns. Merge duplicates."""
    result: dict[str, float] = {}
    for k, v in raw.items():
        canonical = normalize_asset_class(k)
        if canonical is None:
            continue
        result[canonical] = result.get(canonical, 0.0) + v
    return result


def normalize_percentage_dict_region(raw: dict[str, float]) -> dict[str, float]:
    """Normalize keys to canonical region names. Drop unknowns. Merge duplicates."""
    result: dict[str, float] = {}
    for k, v in raw.items():
        canonical = normalize_region(k)
        if canonical is None:
            continue
        result[canonical] = result.get(canonical, 0.0) + v
    return result


def normalize_percentage_dict_subyacente(raw: dict[str, float]) -> dict[str, float]:
    """Normalize keys to canonical subyacente names. Drop unknowns. Merge duplicates."""
    result: dict[str, float] = {}
    for k, v in raw.items():
        canonical = normalize_subyacente(k)
        if canonical is None:
            continue
        result[canonical] = result.get(canonical, 0.0) + v
    return result
