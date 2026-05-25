"""PDF vision extractor — rasterize pages + Claude vision extraction."""
from __future__ import annotations

import base64
import time
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import structlog

from scraper.agents.classifier import _strip_fences
from scraper.agents.extractor import (
    ExtractorParseError,
    _try_parse_json,
    build_extractor_system_blocks,
)
from scraper.agents.types import AttributeExtraction, ExtractedFicha
from scraper.llm import LLMClient

log = structlog.get_logger()

VISION_MODEL = "claude-sonnet-4-6"
_MAX_PAGES = 10  # safety cap for cost


def _pdf_pages_to_png_bytes(path: Path) -> list[bytes]:
    """Render each PDF page to PNG bytes. First _MAX_PAGES only."""
    from pdf2image import convert_from_path

    images = convert_from_path(str(path), dpi=150, first_page=1, last_page=_MAX_PAGES)
    out: list[bytes] = []
    for img in images:
        buf = BytesIO()
        img.save(buf, format="PNG")
        out.append(buf.getvalue())
    return out


async def extract_from_pdf_vision(
    *, path: Path, llm: LLMClient, nombre: str | None = None
) -> ExtractedFicha:
    """Claude vision on rendered PDF pages."""
    start = time.monotonic()
    png_bytes_list = _pdf_pages_to_png_bytes(path)
    if not png_bytes_list:
        raise ExtractorParseError(f"Could not render any pages from {path}")

    # Build content blocks: images + text prompt
    content_blocks: list[dict] = []
    for png in png_bytes_list:
        content_blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.b64encode(png).decode("ascii"),
                },
            }
        )
    prompt_text = (
        "Extrae la ficha del PDF escaneado mostrado arriba. "
        "Seguí el formato JSON del system prompt. Responde SOLO el JSON."
    )
    if nombre:
        prompt_text = (
            f"Producto buscado: {nombre}\n\n"
            f"IMPORTANTE: si el PDF menciona múltiples fondos o variantes, "
            f"extraé SOLO info del fondo que matchea exactamente '{nombre}'. "
            f"Si el PDF no es sobre ese fondo específicamente, marcá "
            f"source_confidence ≤ 0.50.\n\n" + prompt_text
        )
    content_blocks.append({"type": "text", "text": prompt_text})

    system_blocks = build_extractor_system_blocks()
    result = await llm.call(
        model=VISION_MODEL,
        system=system_blocks,
        messages=[{"role": "user", "content": content_blocks}],
        max_tokens=4096,
    )

    clean = _strip_fences(result.response_text)
    payload = _try_parse_json(clean)
    if payload is None:
        raise ExtractorParseError(
            f"Vision extractor output is not valid JSON: cannot parse\n"
            f"Output: {clean[:500]}"
        )

    attrs_raw = payload.get("attributes", {}) or {}
    attributes = {
        k: AttributeExtraction(
            value=v.get("value"),
            confidence=float(v.get("confidence", 0.0)),
            reasoning=v.get("reasoning", ""),
            raw_quote=v.get("raw_quote"),
        )
        for k, v in attrs_raw.items()
    }

    duration_ms = int((time.monotonic() - start) * 1000)

    return ExtractedFicha(
        source_url=None,
        source_type="pdf_vision",
        source_confidence=float(payload.get("source_confidence", 0.7)),
        fetched_at=datetime.now(tz=UTC),
        raw_text="",  # vision didn't produce text
        tables=[],
        attributes=attributes,
        citations=[f"page_{i+1}" for i in range(len(png_bytes_list))],
        extraction_cost_usd=result.cost.total_usd if hasattr(result.cost, "total_usd") else 0.0,
        extraction_duration_ms=duration_ms,
    )
