"""N3 — Claude intensive: longer prompt, up to 10 web_search iterations."""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import structlog

from scraper.agents.classifier import _strip_fences
from scraper.agents.extractor import build_extractor_system_blocks
from scraper.agents.types import AttributeExtraction, ExtractedFicha
from scraper.llm import LLMClient

log = structlog.get_logger()

INTENSIVE_MODEL = "claude-sonnet-4-6"
_WEBSEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}


async def run_claude_intensive(nombre: str, llm: LLMClient | None) -> list[ExtractedFicha]:
    """N3 - more aggressive: instruct Claude to keep searching until found or exhausted."""
    if llm is None:
        return []

    start = time.monotonic()
    base_instructions = (
        f"No encontramos ficha tecnica para: '{nombre}' en DB local, targets "
        f"conocidos ni busqueda web estandar. Haceme una busqueda intensiva: "
        f"- Proba variaciones del nombre (siglas, traducciones, ticker). "
        f"- Busca en sitios de reguladores internacionales (SEC, FCA, BaFin). "
        f"- Busca prospectos PDF (filetype:pdf). "
        f"- Busca menciones en Bloomberg, Morningstar, Yahoo Finance. "
        f"Hasta 10 busquedas. Si no encontras nada robusto, devolve un JSON "
        f"con attributes vacio y source_confidence bajo. Responde SOLO el JSON."
    )

    scrapling_hint = ""
    try:
        from scraper.config import get_settings
        if get_settings().fetcher_backend == "scrapling":
            scrapling_hint = (
                "\n\nAdemás de web_search, tenés herramientas de Scrapling MCP disponibles: "
                "- stealthy_fetch(url): fetchea una página protegida (Cloudflare, JS-heavy) y devuelve su contenido. "
                "- screenshot(session_id): captura screenshot para análisis visual. "
                "Usá stealthy_fetch cuando web_search encuentre una URL pero el contenido parezca protegido o vacío."
            )
    except Exception:
        pass

    user_msg = base_instructions + scrapling_hint

    try:
        result = await llm.call(
            model=INTENSIVE_MODEL,
            system=build_extractor_system_blocks(),
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=8192,
            tools=[_WEBSEARCH_TOOL],
        )
    except Exception as e:
        log.warning("intensive_call_failed", error=str(e))
        return []

    clean = _strip_fences(result.response_text)
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError:
        log.warning("intensive_parse_failed", output=clean[:200])
        return []

    items = payload if isinstance(payload, list) else [payload]
    duration_ms = int((time.monotonic() - start) * 1000)

    fichas: list[ExtractedFicha] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        attrs_raw = item.get("attributes", {}) or {}
        try:
            attrs = {
                k: AttributeExtraction(
                    value=v.get("value"),
                    confidence=float(v.get("confidence", 0.0)),
                    reasoning=v.get("reasoning", ""),
                    raw_quote=v.get("raw_quote"),
                )
                for k, v in attrs_raw.items()
            }
        except (TypeError, ValueError):
            continue
        citations = list(item.get("citations") or [])
        # Reject hallucinated fichas: N3 must cite real web sources.
        # Without citations, the model is guessing from training data which
        # produces high-confidence wrong answers (observed with obscure
        # private funds where web_search finds nothing).
        valid_citations = [
            c for c in citations
            if isinstance(c, str) and c.startswith(("http://", "https://"))
        ]
        if not valid_citations:
            log.info(
                "intensive_ficha_rejected_no_citations",
                nombre=nombre,
                had_citations=len(citations),
            )
            continue
        fichas.append(
            ExtractedFicha(
                source_url=valid_citations[0] if valid_citations else None,
                source_type=item.get("source_type", "websearch"),
                source_confidence=float(item.get("source_confidence", 0.55)),
                fetched_at=datetime.now(tz=UTC),
                raw_text=item.get("raw_text", "") or "",
                tables=list(item.get("tables") or []),
                attributes=attrs,
                citations=valid_citations,
                extraction_cost_usd=(
                    result.cost.total_usd if hasattr(result.cost, "total_usd") else 0.0
                ),
                extraction_duration_ms=duration_ms,
            )
        )
    return fichas
