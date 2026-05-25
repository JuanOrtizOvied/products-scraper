"""N2 — Claude web_search for URL discovery + our extractor for deep fetch.

Two-phase architecture:
1. Claude web_search returns up to 3 candidate URLs (no extraction).
2. Our `extract_from_url` fetches each URL (HTML clean + Claude extractor)
   and follows linked fact-sheet PDFs automatically (phase2b.3).

This gives the classifier much richer evidence than Claude's web_search
summary alone, because we actually download the page + linked PDFs.
"""
from __future__ import annotations

import json

import structlog

from scraper.agents.classifier import _strip_fences
from scraper.agents.types import ExtractedFicha
from scraper.extract.html import extract_from_url
from scraper.llm import LLMClient

log = structlog.get_logger()

WEBSEARCH_MODEL = "claude-sonnet-4-6"
_WEBSEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}
_MAX_URLS = 7


async def _discover_urls(nombre: str, llm: LLMClient) -> list[str]:
    """Ask Claude to find candidate URLs via web_search. Returns 0-3 URLs."""
    user_msg = (
        f"Buscá en la web TODAS las páginas relevantes sobre el producto de "
        f"inversión llamado EXACTAMENTE: '{nombre}'. Usá el tool web_search.\n\n"
        f"Hacé hasta 10 búsquedas con variaciones. Probá: el nombre completo, "
        f"el nombre sin palabras accesorias, siglas, ticker, versiones en "
        f"inglés y en español. Buscá en:\n"
        f"- Sitios de la casa administradora (bancochile.cl, credicorpcapital.com, "
        f"bci.cl, santander.cl, alianza.com.co, larrainvial.com, banchile.cl, etc.)\n"
        f"- Reguladores (cmfchile.cl, smv.gob.pe, sec.gov, sbs.gob.pe)\n"
        f"- Agregadores (bloomberg.com, morningstar.com, yahoo.finance)\n"
        f"- Fichas PDF directamente (filetype:pdf)\n\n"
        f"Devolvé hasta 7 URLs relevantes — páginas específicas del fondo, "
        f"fichas técnicas, folletos, prospectos, reglamentos. Incluí tanto "
        f"HTML de la página oficial como URLs directas de PDFs si las "
        f"encontrás.\n\n"
        f"Priorizá la página dedicada del fondo y cualquier PDF de ficha "
        f"oficial. NO devuelvas homepages genéricos ni listados generales.\n\n"
        f"NO extraigas detalles, solo URLs. Responde SOLO con un JSON array "
        f"de strings. Ejemplo exacto:\n"
        f'["https://admin.com/fondos/xyz", "https://admin.com/docs/folleto.pdf", '
        f'"https://regulador.gob/consulta/abc"]\n\n'
        f"Si no encontrás nada, devolvé [].\n"
        f"NO uses markdown fences. NO texto antes ni después del JSON."
    )
    system_blocks = [
        {
            "type": "text",
            "text": (
                "Eres un asistente de búsqueda web especializado en fichas "
                "técnicas de fondos de inversión. Tu único job es devolver URLs, "
                "no extraer datos. Respondés solo JSON arrays de strings."
            ),
        }
    ]

    try:
        result = await llm.call(
            model=WEBSEARCH_MODEL,
            system=system_blocks,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=2048,
            tools=[_WEBSEARCH_TOOL],
        )
    except Exception as e:
        log.warning("websearch_discover_call_failed", error=str(e))
        return []

    clean = _strip_fences(result.response_text)
    # Attempt to extract a JSON array from possibly noisy text
    if not clean.strip().startswith("["):
        import re

        match = re.search(r"\[.*?\]", clean, re.DOTALL)
        if match:
            clean = match.group(0)

    try:
        urls = json.loads(clean)
    except json.JSONDecodeError:
        log.warning("websearch_discover_parse_failed", output=clean[:200])
        return []

    if not isinstance(urls, list):
        log.warning("websearch_discover_not_list", type=type(urls).__name__)
        return []

    valid = [
        u
        for u in urls
        if isinstance(u, str) and u.startswith(("http://", "https://"))
    ]
    log.info("websearch_discover_success", nombre=nombre, count=len(valid))
    return valid[:_MAX_URLS]


async def run_claude_websearch(
    nombre: str, llm: LLMClient | None
) -> list[ExtractedFicha]:
    """Discover candidate URLs with Claude, then deep-extract each one.

    Each URL goes through extract_from_url which itself returns a list
    (HTML ficha + any linked PDFs). All results are flattened into a single
    list of ExtractedFicha returned to the cascade.
    """
    if llm is None:
        return []

    urls = await _discover_urls(nombre, llm)
    if not urls:
        return []

    all_fichas: list[ExtractedFicha] = []
    for url in urls:
        try:
            fichas = await extract_from_url(url=url, llm=llm, nombre=nombre)
            all_fichas.extend(fichas)
            log.info(
                "websearch_url_extracted",
                url=url,
                fichas=len(fichas),
            )
        except Exception as e:
            err_str = str(e)
            level_fn = log.info if "HTTP 404" in err_str else log.warning
            level_fn("websearch_url_extract_failed", url=url, error=err_str)

    return all_fichas
