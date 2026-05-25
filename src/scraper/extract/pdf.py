"""PDF text extractor — pypdf for text, pdfplumber for tables, Claude for structuring."""
from __future__ import annotations

import re
from pathlib import Path

import pdfplumber
import pypdf
import structlog

from scraper.agents.extractor import extract_with_claude
from scraper.agents.types import ExtractedFicha
from scraper.llm import LLMClient

log = structlog.get_logger()

_SCANNED_THRESHOLD_CHARS = 200
_KEY_PAGE_KEYWORDS = re.compile(
    r"comisi[oó]n|fee|gasto|tarifa|expense|"
    r"m[ií]nimo|inversi[oó]n m[ií]nima|suscripci[oó]n|aporte|ticket|"
    r"t[eé]rminos|condiciones|estructura de costo",
    re.IGNORECASE,
)


def looks_scanned(text: str) -> bool:
    """Heuristic: text extraction yielded so little content the PDF is probably scanned."""
    return len(text.strip()) < _SCANNED_THRESHOLD_CHARS


def _smart_truncate(page_texts: list[str], limit: int = 40000) -> str:
    """Build text within limit, prioritizing early pages + pages with key financial data."""
    full = "\n".join(page_texts)
    if len(full) <= limit:
        return full

    key_pages: list[tuple[int, str]] = []
    for i, pt in enumerate(page_texts):
        if _KEY_PAGE_KEYWORDS.search(pt):
            key_pages.append((i, pt))

    head = "\n".join(page_texts[:15])
    if len(head) > limit // 2:
        head = head[: limit // 2]

    key_section = ""
    for page_idx, pt in key_pages:
        if page_idx < 15:
            continue
        marker = f"\n\n[... página {page_idx + 1} (comisión/mínimo) ...]\n"
        if len(head) + len(key_section) + len(marker) + len(pt) < limit:
            key_section += marker + pt

    return head + key_section


def extract_pdf_text(path: Path) -> tuple[str, list[list[list[str]]]]:
    """Return (text, tables) from a text-based PDF."""
    page_texts: list[str] = []
    reader = pypdf.PdfReader(str(path))
    for page in reader.pages:
        page_text = page.extract_text() or ""
        page_texts.append(page_text)

    text = _smart_truncate(page_texts)

    tables: list[list[list[str]]] = []
    try:
        with pdfplumber.open(path) as plumber_pdf:
            for page in plumber_pdf.pages:
                for tbl in page.extract_tables() or []:
                    cleaned = [
                        [(cell or "").strip() for cell in row]
                        for row in tbl
                        if any(cell for cell in row)
                    ]
                    if cleaned:
                        tables.append(cleaned)
    except Exception as e:  # pdfplumber can fail on some PDFs; log and continue
        log.warning("pdfplumber_table_extract_failed", path=str(path), error=str(e))

    return text, tables


async def extract_from_pdf(
    *, path: Path, llm: LLMClient, nombre: str | None = None
) -> ExtractedFicha:
    """Text-mode PDF extraction. For scanned PDFs, caller should dispatch to vision."""
    text, tables = extract_pdf_text(path)
    if looks_scanned(text):
        from scraper.extract.vision import extract_from_pdf_vision

        log.info("pdf_looks_scanned_using_vision", path=str(path), text_len=len(text))
        return await extract_from_pdf_vision(path=path, llm=llm, nombre=nombre)

    return await extract_with_claude(
        llm=llm,
        source_url=None,
        source_type="pdf_text",
        raw_text=text,
        tables=tables,
        nombre=nombre,
    )
