"""Extractor agent — uses Claude Sonnet 4.6 to pull structured ficha from raw text/tables."""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from scraper.agents.parsing import strip_fences, try_parse_json
from scraper.agents.types import AttributeExtraction, ExtractedFicha

_try_parse_json = try_parse_json
from scraper.llm import LLMClient
from scraper.taxonomies import load_asset_classes, load_canonical_assets, load_regions

log = structlog.get_logger()

EXTRACTOR_MODEL = "claude-sonnet-4-6"

_THIS_DIR = Path(__file__).parent / "prompts"
_EXTRACTOR_TEMPLATE = _THIS_DIR / "extractor_system.md"


class ExtractorParseError(ValueError):
    """Raised when the extractor output can't be parsed as ExtractedFicha."""


def _render_taxonomies() -> dict[str, str]:
    classes = load_asset_classes()
    assets = load_canonical_assets()
    regions = load_regions()
    return {
        "ASSET_CLASSES": "\n".join(f"- {c.name}" for c in classes),
        "N_CANONICAL_ASSETS": str(len(assets)),
        "CANONICAL_ASSETS": "\n".join(
            f"- **{a.name}** → macro: {a.macro_class} (score {a.score})" for a in assets
        ),
        "REGIONS": "\n".join(
            f"- {r.name} (benchmark weight: {r.benchmark_weight:.3f})" for r in regions
        ),
    }


def build_extractor_system_blocks() -> list[dict[str, Any]]:
    template = _EXTRACTOR_TEMPLATE.read_text(encoding="utf-8")
    tax = _render_taxonomies()
    rendered = (
        template.replace("{{ASSET_CLASSES}}", tax["ASSET_CLASSES"])
        .replace("{{N_CANONICAL_ASSETS}}", tax["N_CANONICAL_ASSETS"])
        .replace("{{CANONICAL_ASSETS}}", tax["CANONICAL_ASSETS"])
        .replace("{{REGIONS}}", tax["REGIONS"])
    )
    return [{"type": "text", "text": rendered, "cache_control": {"type": "ephemeral"}}]


def _render_tables_md(tables: list[list[list[str]]]) -> str:
    if not tables:
        return "(sin tablas detectadas)"
    parts: list[str] = []
    for i, tbl in enumerate(tables, 1):
        if not tbl:
            continue
        head = tbl[0]
        rows = tbl[1:]
        parts.append(f"Tabla {i}:\n| " + " | ".join(head) + " |")
        parts.append("| " + " | ".join(["---"] * len(head)) + " |")
        for row in rows:
            parts.append("| " + " | ".join(row) + " |")
    return "\n".join(parts) if parts else "(tablas vacías)"


def _build_user_message(
    source_url: str | None,
    source_type: str,
    raw_text: str,
    tables: list[list[list[str]]],
    nombre: str | None = None,
) -> str:
    src = source_url or f"({source_type} upload)"
    header_lines = [f"Source URL: {src}", f"Source type: {source_type}"]
    if nombre:
        header_lines.append(f"Producto buscado: {nombre}")
        header_lines.append(
            "IMPORTANTE: si el texto menciona múltiples fondos o variantes "
            "(ej. 'Serie A' vs 'Serie B', 'Dólares' vs 'Pesos', 'Latam' vs "
            "'Global'), extraé SOLO info del fondo que matchea exactamente "
            "'" + nombre + "'. Si la página no es sobre ese fondo específicamente, "
            "marcá source_confidence ≤ 0.50 y dejá los atributos que no sean del "
            "fondo target como null con confidence 0."
        )
    return (
        "\n".join(header_lines)
        + f"\n\n=== RAW TEXT ===\n{raw_text[:40000]}\n\n"
        + f"=== TABLES ===\n{_render_tables_md(tables)}\n"
    )


async def extract_with_claude(
    *,
    llm: LLMClient,
    source_url: str | None,
    source_type: str,
    raw_text: str,
    tables: list[list[list[str]]],
    nombre: str | None = None,
) -> ExtractedFicha:
    """Run the extractor agent. Returns a validated ExtractedFicha."""
    start = time.monotonic()
    system_blocks = build_extractor_system_blocks()
    user_msg = _build_user_message(source_url, source_type, raw_text, tables, nombre)

    result = await llm.call(
        model=EXTRACTOR_MODEL,
        system=system_blocks,
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=4096,
    )

    clean = strip_fences(result.response_text)
    payload = try_parse_json(clean)
    if payload is None:
        raise ExtractorParseError(
            f"Extractor output is not valid JSON: cannot parse\n"
            f"Output: {clean[:500]}"
        )

    attrs_raw = payload.get("attributes", {}) or {}
    try:
        attributes = {
            k: AttributeExtraction(
                value=v.get("value"),
                confidence=float(v.get("confidence", 0.0)),
                reasoning=v.get("reasoning", ""),
                raw_quote=v.get("raw_quote"),
            )
            for k, v in attrs_raw.items()
        }
    except (TypeError, ValueError) as e:
        raise ExtractorParseError(f"Bad attributes shape: {e}") from e

    doc_date_raw = payload.get("document_date")
    doc_date = None
    if doc_date_raw:
        try:
            doc_date = datetime.fromisoformat(doc_date_raw)
            if doc_date.tzinfo is None:
                doc_date = doc_date.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            log.warning("extractor_bad_document_date", raw=doc_date_raw)

    duration_ms = int((time.monotonic() - start) * 1000)

    return ExtractedFicha(
        source_url=source_url,
        source_type=source_type,
        source_confidence=float(payload.get("source_confidence", 0.5)),
        fetched_at=datetime.now(tz=UTC),
        raw_text=raw_text[:40000],
        tables=tables,
        attributes=attributes,
        citations=list(payload.get("citations") or []),
        extraction_cost_usd=result.cost.total_usd if hasattr(result.cost, "total_usd") else 0.0,
        extraction_duration_ms=duration_ms,
        document_date=doc_date,
        class_options=payload.get("class_options"),
    )
