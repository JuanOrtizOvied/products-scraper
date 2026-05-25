"""Search cascade orchestrator: N0 (DB) -> N1 (targets) -> N2 (web_search) -> N3 (intensive)."""
from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.agents.types import ExtractedFicha
from scraper.config import get_settings
from scraper.llm import LLMClient
from scraper.search.cache import get_cached, put_cached
from scraper.search.level0_db import lookup_db  # noqa: F401
from scraper.search.level2_websearch import run_claude_websearch  # noqa: F401
from scraper.search.level3_intensive import run_claude_intensive  # noqa: F401
from scraper.search.types import CascadeResult

log = structlog.get_logger()

_N1_SHORT_CIRCUIT_CONF = 0.85
_N2_ENOUGH_CONF = 0.70


async def run_n1_parsers(nombre: str, llm: LLMClient | None) -> list[ExtractedFicha]:
    """Run all N1 parsers in parallel, respecting per-parser circuit breakers."""
    import asyncio

    from scraper.search.circuit_breaker import BREAKER
    from scraper.search.level1_scrapers.registry import TARGETS

    if llm is None:
        return []

    async def _run_one(parser) -> list[ExtractedFicha]:
        if BREAKER.is_open(parser.domain):
            log.info("n1_parser_skipped_breaker_open", domain=parser.domain)
            return []
        try:
            candidate_urls = await parser.search_by_name(nombre)
            fichas: list[ExtractedFicha] = []
            for url in candidate_urls:
                try:
                    f = await asyncio.wait_for(parser.parse_ficha(url, llm), timeout=30.0)
                    fichas.append(f)
                except Exception as e:
                    log.warning(
                        "n1_parser_url_failed",
                        domain=parser.domain,
                        url=url,
                        error=str(e),
                    )
            BREAKER.record_success(parser.domain)
            return fichas
        except Exception as e:
            BREAKER.record_failure(parser.domain)
            log.warning("n1_parser_failed", domain=parser.domain, error=str(e))
            return []

    results = await asyncio.gather(*(_run_one(p) for p in TARGETS))
    flat = [f for batch in results for f in batch]
    return flat


def merge_candidates(
    a: list[ExtractedFicha], b: list[ExtractedFicha]
) -> list[ExtractedFicha]:
    """Dedup by (source_url, source_type). First occurrence wins."""
    seen: set[tuple[str | None, str]] = set()
    result: list[ExtractedFicha] = []
    for f in [*a, *b]:
        key = (f.source_url, f.source_type)
        if key in seen:
            continue
        seen.add(key)
        result.append(f)
    return result


def _best_confidence(fichas: list[ExtractedFicha]) -> float:
    return max((f.source_confidence for f in fichas), default=0.0)


async def run_cascade(
    *,
    nombre: str,
    session: AsyncSession | None,
    llm: LLMClient | None,
    skip_n0: bool = False,
) -> CascadeResult:
    """Run the 4-level cascade and return first-sufficient result."""
    # N0 — skip during pipeline calibration (the validation products are in
    # the same products table we'd look up against, so hitting N0 is tautological)
    if not skip_n0:
        db_hit = await lookup_db(nombre, session)
        if db_hit is not None:
            log.info("cascade_hit_n0", nombre=nombre)
            return CascadeResult(level=0, fichas=[db_hit])
    else:
        log.info("cascade_n0_skipped", nombre=nombre, reason="calibration")

    # N1 — check cache
    cached_n1 = await get_cached(session, nombre, "level1") if session else None
    if cached_n1 is not None:
        n1 = cached_n1
    else:
        n1 = await run_n1_parsers(nombre, llm)
        if session and n1:
            await put_cached(session, nombre, "level1", n1)

    if _best_confidence(n1) >= _N1_SHORT_CIRCUIT_CONF:
        log.info("cascade_hit_n1", nombre=nombre, hits=len(n1))
        return CascadeResult(level=1, fichas=n1)

    # N2 — check cache
    cached_n2 = await get_cached(session, nombre, "websearch") if session else None
    if cached_n2 is not None:
        n2 = cached_n2
    else:
        n2 = await run_claude_websearch(nombre, llm)
        if session and n2:
            await put_cached(session, nombre, "websearch", n2)

    combined = merge_candidates(n1, n2)
    if _best_confidence(combined) >= _N2_ENOUGH_CONF:
        log.info("cascade_hit_n2", nombre=nombre, hits=len(combined))
        return CascadeResult(level=2, fichas=combined)

    # N3
    settings = get_settings()
    if getattr(settings, "skip_intensive_search", True):
        log.info("cascade_n3_skipped", nombre=nombre, reason="kill_switch")
        return CascadeResult(level=2, fichas=combined, low_quality=True)

    n3 = await run_claude_intensive(nombre, llm)
    final = merge_candidates(combined, n3)
    return CascadeResult(
        level=3,
        fichas=final,
        low_quality=_best_confidence(final) < _N2_ENOUGH_CONF,
    )
