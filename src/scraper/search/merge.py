"""Multi-source merge: sort by recency, detect conflicts, build context."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from scraper.agents.types import (
    ConflictEntry,
    ExtractedFicha,
    FieldConflict,
    MergeResult,
    SourceSummary,
)

_DICT_FIELDS = {"clase_activo", "foco_geografico", "subyacente"}
_DICT_TOLERANCE_PP = 5


def _sort_key(ficha: ExtractedFicha) -> tuple:
    has_date = ficha.document_date is not None
    date_val = ficha.document_date or datetime.min.replace(tzinfo=ficha.fetched_at.tzinfo)
    return (has_date, date_val, ficha.fetched_at)


def _source_label(ficha: ExtractedFicha) -> str:
    url_part = ficha.source_url or f"({ficha.source_type})"
    if ficha.document_date:
        return f"{url_part} ({ficha.document_date.strftime('%b %Y')})"
    return url_part


def _values_conflict(attr: str, val_a: Any, val_b: Any) -> bool:
    if val_a is None or val_b is None:
        return False
    if attr in _DICT_FIELDS and isinstance(val_a, dict) and isinstance(val_b, dict):
        all_keys = set(val_a) | set(val_b)
        for k in all_keys:
            a = val_a.get(k, 0)
            b = val_b.get(k, 0)
            try:
                if abs(float(a) - float(b)) > _DICT_TOLERANCE_PP:
                    return True
            except (TypeError, ValueError):
                if a != b:
                    return True
        return False
    if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
        return abs(float(val_a) - float(val_b)) > 1e-9
    return str(val_a).strip().lower() != str(val_b).strip().lower()


def merge_fichas(fichas: list[ExtractedFicha]) -> MergeResult:
    sorted_fichas = sorted(fichas, key=_sort_key, reverse=True)
    primary = sorted_fichas[0]
    secondaries = sorted_fichas[1:]

    all_sources = [
        SourceSummary(
            url=f.source_url or "",
            label=_source_label(f),
            document_date=f.document_date,
            source_type=f.source_type,
        )
        for f in sorted_fichas
    ]

    conflicts: list[FieldConflict] = []
    checked_attrs = set(primary.attributes.keys())
    for s in secondaries:
        checked_attrs |= set(s.attributes.keys())

    for attr_name in checked_attrs:
        primary_ae = primary.attributes.get(attr_name)
        if primary_ae is None:
            continue
        for s in secondaries:
            s_ae = s.attributes.get(attr_name)
            if s_ae is None:
                continue
            if _values_conflict(attr_name, primary_ae.value, s_ae.value):
                existing = next((c for c in conflicts if c.attribute == attr_name), None)
                alt = ConflictEntry(
                    value=s_ae.value,
                    source_url=s.source_url or "",
                    source_label=_source_label(s),
                    document_date=s.document_date,
                    raw_quote=s_ae.raw_quote,
                )
                if existing is None:
                    conflicts.append(
                        FieldConflict(
                            attribute=attr_name,
                            chosen_value=primary_ae.value,
                            chosen_source=primary.source_url or "",
                            alternatives=[alt],
                        )
                    )
                else:
                    existing.alternatives.append(alt)

    context_parts: list[str] = []
    for i, f in enumerate(sorted_fichas, 1):
        label = _source_label(f)
        context_parts.append(f"[Fuente {i}: {label} — {f.source_type}]")
        for attr, ae in f.attributes.items():
            context_parts.append(
                f"  {attr}: {ae.value!r}  (conf={ae.confidence:.2f})  quote: {ae.raw_quote!r}"
            )
        if f.raw_text:
            context_parts.append(f"  raw_text: {f.raw_text[:500]}")

    return MergeResult(
        primary=primary,
        all_sources=all_sources,
        conflicts=conflicts,
        merged_context="\n".join(context_parts),
    )
