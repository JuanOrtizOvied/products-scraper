"""HTML extractor — fetch, clean, feed to Claude extractor agent.

Follows links to related fund documents (PDFs, sub-pages) identified by
an LLM agent reading the page's outgoing links semantically (not regex).
"""
from __future__ import annotations

import dataclasses
import json
import re
import tempfile
from pathlib import Path
from urllib.parse import urljoin

import structlog
import tldextract
from bs4 import BeautifulSoup

from scraper.agents.classifier import _strip_fences
from scraper.agents.extractor import extract_with_claude
from scraper.agents.types import ExtractedFicha
from scraper.config import get_settings
from scraper.extract.fetch import (
    fetch_url,
    fetch_url_bytes,
    fetch_with_playwright,
    is_js_rendered,
)
from scraper.extract.pdf import extract_from_pdf
from scraper.llm import LLMClient

log = structlog.get_logger()

_STRIP_TAGS = ("script", "style", "nav", "footer", "aside", "noscript", "iframe", "header")

# Regex kept for backwards compat / fast-path unit tests; NOT used by extract_from_url anymore
_PDF_ANCHOR_KEYWORDS = re.compile(
    r"folleto|ficha(?:\s+t[eé]cnica)?|prospecto|fact\s*sheet|reglamento|"
    r"informativo|hoja\s+de\s+producto|presentaci[oó]n|cartera|gesti[oó]n|"
    r"reporte|informe|memoria|aviso|anexo",
    re.IGNORECASE,
)
_MAX_PDFS_PER_PAGE = 8
_MAX_LLM_LINK_CANDIDATES = 80
_MAX_LINKS_TO_FOLLOW = 4  # was 10
_LINK_CLASSIFIER_MODEL = "claude-sonnet-4-6"

# Use bundled Public Suffix List snapshot — no network fetch required.
# fallback_to_snapshot=True means: use the bundled PSL that shipped with
# the tldextract package and NEVER try to reach publicsuffix.org.
_TLD_EXTRACTOR = tldextract.TLDExtract(
    suffix_list_urls=(),
    fallback_to_snapshot=True,
)


def _looks_like_pdf_url(url: str) -> bool:
    """True if the URL path or query suggests a PDF file.

    Handles:
    - /docs/file.pdf               → True (path ends in .pdf)
    - /viewer?file=x.pdf           → True (.pdf in query)
    - /emisor/view-pdf?file=X      → True (path contains 'pdf')
    - /fondos/detail               → False
    """
    lower = url.lower()
    # Split path and query
    path, _, query = lower.partition("?")
    if path.endswith(".pdf"):
        return True
    if ".pdf" in query:
        return True
    # Path endpoints that indicate PDF-serving handlers
    if path.rstrip("/").endswith("view-pdf") or path.rstrip("/").endswith("/pdf"):
        return True
    return False


def _same_registrable_domain(a_url: str, b_url: str) -> bool:
    """True if two URLs belong to the same organization (same registrable domain)."""
    a = _TLD_EXTRACTOR(a_url)
    b = _TLD_EXTRACTOR(b_url)
    if not a.domain or not b.domain:
        return False
    return (a.domain, a.suffix) == (b.domain, b.suffix)


def _extract_tables(soup: BeautifulSoup) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    for tbl in soup.find_all("table"):
        rows: list[list[str]] = []
        for tr in tbl.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


def clean_html(html: str) -> tuple[str, list[list[list[str]]]]:
    """Return (raw_text, tables) from raw HTML."""
    soup = BeautifulSoup(html, "lxml")
    for tag in _STRIP_TAGS:
        for el in soup.find_all(tag):
            el.decompose()
    tables = _extract_tables(soup)
    main = soup.find("main") or soup.find("article") or soup.body or soup
    raw_text = main.get_text("\n", strip=True) if main else ""
    return raw_text, tables


def find_pdf_links(html: str, base_url: str) -> list[str]:
    """LEGACY regex-based PDF link finder. Kept for unit tests and as fallback.

    New callers should prefer `classify_links_with_llm` which uses semantic
    understanding instead of keyword regex.
    """
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        text = a.get_text(" ", strip=True)

        href_lower = href.lower().split("?", 1)[0]
        is_pdf = href_lower.endswith(".pdf")
        if not is_pdf:
            continue
        text_matches = bool(text and _PDF_ANCHOR_KEYWORDS.search(text))
        href_matches = bool(_PDF_ANCHOR_KEYWORDS.search(href_lower))
        if not (text_matches or href_matches):
            continue

        full = urljoin(base_url, href)
        if not _same_registrable_domain(base_url, full):
            continue
        if full in seen:
            continue
        seen.add(full)
        links.append(full)
        if len(links) >= _MAX_PDFS_PER_PAGE:
            break
    return links


def _gather_candidates(html: str, base_url: str) -> list[tuple[str, str]]:
    """Collect (anchor_text, full_url) pairs from the page. Same-org only."""
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        text = a.get_text(" ", strip=True) or "(no text)"
        full = urljoin(base_url, href)
        if not _same_registrable_domain(base_url, full):
            continue
        if full in seen:
            continue
        seen.add(full)
        out.append((text, full))
        if len(out) >= _MAX_LLM_LINK_CANDIDATES:
            break
    return out


async def classify_links_with_llm(
    html: str,
    base_url: str,
    nombre: str | None,
    llm: LLMClient,
) -> list[str]:
    """Let Claude decide which on-page links are relevant fund documents.

    Sends all same-org <a> tags (text + href) to Claude. Claude returns
    a JSON array of URLs it considers documentation specific to THIS fund
    (fichas, folletos, prospectos, reglamentos, presentaciones, carteras,
    memoria, etc). Claude ignores generic navigation / regulatory / contact links.

    Returns up to _MAX_LINKS_TO_FOLLOW URLs.
    """
    candidates = _gather_candidates(html, base_url)
    if not candidates:
        return []

    links_md = "\n".join(
        f"{i+1}. [{text[:80]}] -> {url}"
        for i, (text, url) in enumerate(candidates)
    )
    target = f' llamado "{nombre}"' if nombre else ""
    user_msg = (
        f"Acá hay {len(candidates)} links de una página web de un fondo de "
        f"inversión{target}. Decime cuáles son documentos o sub-páginas "
        f"específicas sobre ESTE fondo concreto: fichas técnicas, folletos, "
        f"prospectos, reglamentos, fact sheets, presentaciones comerciales, "
        f"carteras (holdings), memorias anuales, informes, hojas de producto, "
        f"o páginas de detalle del fondo en otros sitios (CMF, CNV, SMV, "
        f"Bloomberg, Morningstar, calificadoras).\n\n"
        f"Seleccioná MÁXIMO {_MAX_LINKS_TO_FOLLOW} URLs, priorizando por valor "
        f"informacional:\n"
        f"1. Ficha técnica / fact sheet / folleto / prospecto del fondo "
        f"(documentos primarios — alta prioridad).\n"
        f"2. Reglamento o carta de gestión vigente (1 solo, el más reciente).\n"
        f"3. Página oficial en regulador/calificadora (ej. 1 URL de CNV, 1 URL "
        f"de FIX o Moody's si las hay).\n"
        f"4. Solo 1 reporte reciente si hay varios del mismo tipo.\n\n"
        f"IGNORA: políticas internas, términos y condiciones, listados "
        f"regulatorios genéricos (personas vinculadas, idóneos, OSH), "
        f"navegación, contacto, login, home, redes sociales, blogs.\n\n"
        f"IMPORTANTE sobre VARIANTES: si un link apunta a una VARIANTE del fondo "
        f"con nombre DIFERENTE al solicitado (ej. el usuario pide "
        f"'{nombre or 'X'}' y el link dice otro nombre como 'X Latam', "
        f"'X Dólares', 'X Serie B', 'X Clase 2'), DESCARTALO a menos que sea "
        f"la ÚNICA fuente disponible sobre el fondo target. Preferí siempre "
        f"el documento del fondo exacto, no de variantes.\n\n"
        f"NO selecciones múltiples reportes históricos del mismo tipo. Uno "
        f"actual es suficiente.\n\n"
        f"Links:\n{links_md}\n\n"
        f"Responde SOLO con un JSON array de hasta {_MAX_LINKS_TO_FOLLOW} URLs "
        f'(exactas, copiadas de arriba). Ej: ["https://...", "https://..."]\n'
        f"Si ninguno es relevante, devolvé []. Sin markdown fences, sin texto "
        f"antes ni después del JSON."
    )

    system_blocks = [
        {
            "type": "text",
            "text": (
                "Sos un agente que clasifica links de páginas web de fondos de "
                "inversión. Tu objetivo es seleccionar SOLO los links que son "
                "documentación específica de UN fondo concreto. Respondés "
                "siempre con un JSON array de URLs, nada más."
            ),
            "cache_control": {"type": "ephemeral"},
        }
    ]

    try:
        result = await llm.call(
            model=_LINK_CLASSIFIER_MODEL,
            system=system_blocks,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=2048,
        )
    except Exception as e:
        log.warning("link_classifier_call_failed", error=str(e))
        return []

    clean = _strip_fences(result.response_text)
    if not clean.strip().startswith("["):
        match = re.search(r"\[.*?\]", clean, re.DOTALL)
        if match:
            clean = match.group(0)

    try:
        selected = json.loads(clean)
    except json.JSONDecodeError:
        log.warning("link_classifier_parse_failed", output=clean[:200])
        return []

    if not isinstance(selected, list):
        return []

    # Sanity: only return URLs that were actually in our candidates
    candidate_urls = {u for _, u in candidates}
    valid = [u for u in selected if isinstance(u, str) and u in candidate_urls]
    log.info(
        "link_classifier_selected",
        candidates=len(candidates),
        selected=len(valid),
    )
    return valid[:_MAX_LINKS_TO_FOLLOW]


async def _fetch_and_extract_pdf(
    pdf_url: str, llm: LLMClient, nombre: str | None = None
) -> ExtractedFicha:
    """Download a PDF to a tempfile, run extract_from_pdf, tag the source_url."""
    data = await fetch_url_bytes(pdf_url)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        tf.write(data)
        tmp_path = Path(tf.name)
    try:
        ficha = await extract_from_pdf(path=tmp_path, llm=llm, nombre=nombre)
        return dataclasses.replace(ficha, source_url=pdf_url)
    finally:
        tmp_path.unlink(missing_ok=True)


async def _fetch_and_extract_html_subpage(
    sub_url: str, llm: LLMClient, nombre: str | None = None
) -> list[ExtractedFicha]:
    """Fetch an HTML sub-page and extract the main ficha (no further link following)."""
    html = await fetch_url(sub_url)
    if is_js_rendered(html):
        html = await fetch_with_playwright(sub_url)
    raw_text, tables = clean_html(html)
    sub = await extract_with_claude(
        llm=llm,
        source_url=sub_url,
        source_type="html",
        raw_text=raw_text,
        tables=tables,
        nombre=nombre,
    )
    return [sub]


async def _fetch_and_extract_link(
    link_url: str,
    llm: LLMClient,
    nombre: str | None = None,
) -> list[ExtractedFicha]:
    """Route a link URL to PDF or HTML extractor. Returns list of fichas.

    Used by extract_from_url's parallel sub-fetch stage.
    """
    if _looks_like_pdf_url(link_url):
        pdf_ficha = await _fetch_and_extract_pdf(link_url, llm, nombre=nombre)
        log.info("link_extracted_as_pdf", link_url=link_url)
        return [pdf_ficha]
    sub_fichas = await _fetch_and_extract_html_subpage(link_url, llm, nombre=nombre)
    log.info("link_extracted_as_html", link_url=link_url)
    return sub_fichas


async def _batch_fetch_with_session(urls: list[str]) -> dict[str, str]:
    """Fetch multiple URLs with Scrapling session reuse when available."""
    if get_settings().fetcher_backend != "scrapling":
        results = {}
        for url in urls:
            try:
                results[url] = await fetch_url(url)
            except Exception:
                results[url] = ""
        return results

    from scrapling.fetchers import AsyncStealthySession
    results = {}
    try:
        async with AsyncStealthySession(headless=True) as session:
            tasks = {url: session.fetch(url) for url in urls}
            for url, task in tasks.items():
                try:
                    page = await task
                    results[url] = str(page.html_content)
                except Exception:
                    results[url] = ""
    except Exception:
        for url in urls:
            if url not in results:
                try:
                    results[url] = await fetch_url(url)
                except Exception:
                    results[url] = ""
    return results


async def extract_from_url(
    *,
    url: str,
    llm: LLMClient,
    follow_pdfs: bool = True,
    nombre: str | None = None,
) -> list[ExtractedFicha]:
    """Fetch URL → clean → extract via Claude. Uses LLM-based link classifier
    to decide which linked documents (PDFs or sub-pages) to fetch and extract too.

    If the URL is itself a PDF (path ends in .pdf, .pdf in query, or endpoint
    is a known PDF-viewer), route directly to _fetch_and_extract_pdf and skip
    the HTML pipeline.

    Returns the HTML (or PDF) ficha first, followed by any extracted linked
    documents. Sub-pages are extracted without further follow-up (depth limit = 1).
    """
    if _looks_like_pdf_url(url):
        log.info("extract_from_url_routing_to_pdf", url=url)
        pdf_ficha = await _fetch_and_extract_pdf(url, llm, nombre=nombre)
        return [pdf_ficha]

    html = await fetch_url(url)
    # Detect PDF magic bytes (in case server returned PDF for a URL we thought was HTML)
    if html.startswith("%PDF-"):
        log.info("extract_from_url_magic_bytes_pdf", url=url)
        pdf_ficha = await _fetch_and_extract_pdf(url, llm, nombre=nombre)
        return [pdf_ficha]

    if is_js_rendered(html):
        log.info("fallback_playwright", url=url)
        html = await fetch_with_playwright(url)

    raw_text, tables = clean_html(html)
    html_ficha = await extract_with_claude(
        llm=llm,
        source_url=url,
        source_type="html",
        raw_text=raw_text,
        tables=tables,
        nombre=nombre,
    )
    fichas: list[ExtractedFicha] = [html_ficha]

    if not follow_pdfs:
        return fichas

    import asyncio as _asyncio

    relevant_urls = await classify_links_with_llm(html, url, nombre, llm)
    if relevant_urls:
        tasks = [
            _fetch_and_extract_link(link_url, llm, nombre=nombre)
            for link_url in relevant_urls
        ]
        results = await _asyncio.gather(*tasks, return_exceptions=True)
        for link_url, result in zip(relevant_urls, results, strict=True):
            if isinstance(result, Exception):
                # 404s from stale Google-indexed URLs are expected noise;
                # log at info level rather than warning.
                err_str = str(result)
                level_fn = log.info if "HTTP 404" in err_str else log.warning
                level_fn("link_follow_failed", link_url=link_url, error=err_str)
                continue
            fichas.extend(result)

    return fichas
