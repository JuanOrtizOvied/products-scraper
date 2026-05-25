# Phase 2b — Extract + Search Cascade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir el pipeline end-to-end que acepta un nombre de producto y devuelve clasificación canónica completa, con cascada de búsqueda (DB → 7 sitios conocidos → Claude web_search → Claude intensive con kill switch) y extractor thick (HTML + PDF texto + PDF vision).

**Architecture:** Tres entry points (name/url/pdf) convergen en `ExtractedFicha`. Para name: cascada de 4 niveles con short-circuit por umbrales de confidence. Para url/pdf: extract directo. En todos los casos, el output se pasa al Phase 2a classifier como evidence block y continúa por reviewer + orchestrator.

**Tech Stack:** httpx + Playwright (fallback JS), BeautifulSoup + lxml, pypdf + pdfplumber, Claude Sonnet 4.6 con `web_search_20250305` tool, rapidfuzz, tenacity, pytest, structlog.

**Spec de referencia:** `docs/superpowers/specs/2026-04-18-phase2b-extract-search-design.md`
**Phase 2a status:** `docs/superpowers/plans/phase2a-STATUS.md` (tag `phase2a-complete` en `77fafe5`)

**Entregable al final de Phase 2b:**
- `poetry run python -m scraper.scripts.find_and_classify "Credicorp Crecimiento"` → clasificación completa
- `poetry run python -m scraper.scripts.extract_one --pdf ficha.pdf` → `ExtractedFicha`
- `poetry run python -m scraper.scripts.extract_one --url https://...` → `ExtractedFicha`
- 7 parsers N1 con fixtures de HTML real versionadas
- Accuracy end-to-end ≥85% por atributo contra validation_set
- Tag `phase2b-complete`

---

## File structure que se crea en Phase 2b

```
scraper/
├── src/scraper/
│   ├── extract/                            # NEW
│   │   ├── __init__.py
│   │   ├── fetch.py                        # httpx + Playwright
│   │   ├── html.py                         # BeautifulSoup + Claude
│   │   ├── pdf.py                          # pypdf + pdfplumber + Claude
│   │   └── vision.py                       # Claude vision fallback
│   ├── search/                             # NEW
│   │   ├── __init__.py
│   │   ├── types.py                        # CascadeResult
│   │   ├── cascade.py                      # orchestrator
│   │   ├── level0_db.py                    # rapidfuzz DB lookup
│   │   ├── level1_scrapers/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                     # SiteParser protocol
│   │   │   ├── registry.py
│   │   │   ├── credicorpcapital_com.py
│   │   │   ├── smv_gob_pe.py
│   │   │   ├── sbs_gob_pe.py
│   │   │   ├── bcpcapital_com.py
│   │   │   ├── corecapital_pe.py
│   │   │   ├── sabbi_pe.py
│   │   │   └── bvl_com_pe.py
│   │   ├── level2_websearch.py
│   │   ├── level3_intensive.py
│   │   ├── cache.py                        # search_cache integration
│   │   └── circuit_breaker.py
│   ├── agents/
│   │   ├── extractor.py                    # NEW
│   │   ├── prompts/
│   │   │   └── extractor_system.md         # NEW
│   │   └── types.py                        # + ExtractedFicha, AttributeExtraction
│   └── scripts/
│       ├── extract_one.py                  # NEW
│       └── find_and_classify.py            # NEW
└── tests/
    ├── fixtures/
    │   ├── html/
    │   │   ├── credicorpcapital_sample.html
    │   │   ├── smv_sample.html
    │   │   ├── sbs_sample.html
    │   │   ├── bcp_sample.html
    │   │   ├── corecapital_sample.html
    │   │   ├── sabbi_sample.html
    │   │   └── bvl_sample.html
    │   └── pdfs/
    │       ├── ficha_text.pdf
    │       └── ficha_scanned.pdf
    ├── unit/
    │   ├── test_extracted_ficha.py
    │   ├── test_fetch.py
    │   ├── test_extract_html.py
    │   ├── test_extract_pdf.py
    │   ├── test_cascade.py
    │   ├── test_level0_db.py
    │   ├── test_level1_base.py
    │   ├── test_circuit_breaker.py
    │   └── test_cache.py
    └── integration/
        ├── test_extractor_mocked.py
        ├── test_level2_websearch_mocked.py
        ├── test_extract_one_smoke.py
        ├── test_find_and_classify_smoke.py
        └── (parser-specific tests)
```

---

## Task 1: `ExtractedFicha` + `AttributeExtraction` dataclasses

Agregar las dataclasses compartidas. Sin dependencias nuevas — solo tipos puros.

**Files:**
- Modify: `src/scraper/agents/types.py`
- Create: `tests/unit/test_extracted_ficha.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_extracted_ficha.py`:

```python
from datetime import datetime, timezone


def test_attribute_extraction_construction():
    from scraper.agents.types import AttributeExtraction

    a = AttributeExtraction(
        value="soles",
        confidence=0.95,
        reasoning="ficha dice 'S/.' explícitamente",
        raw_quote="denominación: S/.",
    )
    assert a.value == "soles"
    assert a.confidence == 0.95
    assert a.raw_quote == "denominación: S/."


def test_attribute_extraction_frozen():
    from scraper.agents.types import AttributeExtraction

    a = AttributeExtraction(value=None, confidence=0.0, reasoning="n/a", raw_quote=None)
    import dataclasses
    assert dataclasses.is_dataclass(a)
    try:
        a.confidence = 1.0
        raise AssertionError("should be frozen")
    except dataclasses.FrozenInstanceError:
        pass


def test_extracted_ficha_construction_with_defaults():
    from scraper.agents.types import AttributeExtraction, ExtractedFicha

    f = ExtractedFicha(
        source_url="https://example.com/fondo",
        source_type="html",
        source_confidence=0.90,
        fetched_at=datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc),
        raw_text="texto limpio",
        tables=[[["col1", "col2"], ["v1", "v2"]]],
        attributes={
            "moneda": AttributeExtraction(
                value="soles", confidence=0.95, reasoning="r", raw_quote="q"
            ),
        },
        citations=["https://example.com/fondo"],
        extraction_cost_usd=0.012,
        extraction_duration_ms=3400,
    )
    assert f.source_url == "https://example.com/fondo"
    assert f.source_type == "html"
    assert "moneda" in f.attributes


def test_extracted_ficha_to_json_roundtrip():
    from scraper.agents.types import AttributeExtraction, ExtractedFicha

    f = ExtractedFicha(
        source_url=None,
        source_type="pdf_text",
        source_confidence=0.80,
        fetched_at=datetime(2026, 4, 18, tzinfo=timezone.utc),
        raw_text="t",
        tables=[],
        attributes={
            "nombre": AttributeExtraction(value="X", confidence=1.0, reasoning="", raw_quote="X")
        },
        citations=[],
        extraction_cost_usd=0.0,
        extraction_duration_ms=0,
    )
    payload = f.to_json()
    assert isinstance(payload, dict)
    assert payload["source_type"] == "pdf_text"
    back = ExtractedFicha.from_json(payload)
    assert back.source_type == "pdf_text"
    assert back.attributes["nombre"].value == "X"
```

- [ ] **Step 2: Run test — fails**

```bash
poetry run pytest tests/unit/test_extracted_ficha.py -v
```

Expected: `ImportError: cannot import name 'AttributeExtraction'`.

- [ ] **Step 3: Add types to `src/scraper/agents/types.py`**

Agregar al final del archivo existente (no tocar `AttributeClassification`, `ClassificationResult`, `AttributeReview`, `ReviewResult`):

```python
@dataclass(frozen=True)
class AttributeExtraction:
    """One attribute as extracted from a raw source.

    Different from AttributeClassification: includes raw_quote for traceability
    to the source text/table cell. No rule_applied (extractor doesn't apply
    classification rules — that's the classifier's job).
    """
    value: Any | None
    confidence: float
    reasoning: str
    raw_quote: str | None


@dataclass(frozen=True)
class ExtractedFicha:
    """Output of the Extractor agent. Input to the Classifier agent.

    One ExtractedFicha = one source (one URL, one PDF, one DB row). Multiple
    fichas may be combined as evidence blocks when feeding the classifier.
    """
    source_url: str | None           # None when source is a PDF file
    source_type: str                 # "html" | "pdf_text" | "pdf_vision" | "db" | "websearch"
    source_confidence: float         # 0.0–1.0; set by the cascade level
    fetched_at: datetime

    raw_text: str
    tables: list[list[list[str]]]

    attributes: dict[str, AttributeExtraction]
    citations: list[str]
    extraction_cost_usd: float
    extraction_duration_ms: int

    def to_json(self) -> dict[str, Any]:
        return {
            "source_url": self.source_url,
            "source_type": self.source_type,
            "source_confidence": self.source_confidence,
            "fetched_at": self.fetched_at.isoformat(),
            "raw_text": self.raw_text,
            "tables": self.tables,
            "attributes": {
                k: {
                    "value": v.value,
                    "confidence": v.confidence,
                    "reasoning": v.reasoning,
                    "raw_quote": v.raw_quote,
                }
                for k, v in self.attributes.items()
            },
            "citations": list(self.citations),
            "extraction_cost_usd": self.extraction_cost_usd,
            "extraction_duration_ms": self.extraction_duration_ms,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "ExtractedFicha":
        return cls(
            source_url=payload.get("source_url"),
            source_type=payload["source_type"],
            source_confidence=float(payload.get("source_confidence", 0.0)),
            fetched_at=datetime.fromisoformat(payload["fetched_at"]),
            raw_text=payload.get("raw_text", ""),
            tables=list(payload.get("tables", [])),
            attributes={
                k: AttributeExtraction(
                    value=v.get("value"),
                    confidence=float(v.get("confidence", 0.0)),
                    reasoning=v.get("reasoning", ""),
                    raw_quote=v.get("raw_quote"),
                )
                for k, v in payload.get("attributes", {}).items()
            },
            citations=list(payload.get("citations", [])),
            extraction_cost_usd=float(payload.get("extraction_cost_usd", 0.0)),
            extraction_duration_ms=int(payload.get("extraction_duration_ms", 0)),
        )
```

Asegurate de tener los imports al tope del archivo (ya existen `dataclass`, `Any`; agregar `datetime` si no está).

- [ ] **Step 4: Run test — passes**

```bash
poetry run pytest tests/unit/test_extracted_ficha.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Full suite still green**

```bash
poetry run pytest -q 2>&1 | tail -3
```

Expected: ~79 passed (75 Phase 2a + 4 new).

- [ ] **Step 6: Lint + commit**

```bash
poetry run ruff check src/scraper/agents/types.py tests/unit/test_extracted_ficha.py
git add src/scraper/agents/types.py tests/unit/test_extracted_ficha.py
git commit -m "feat: add ExtractedFicha and AttributeExtraction dataclasses (Phase 2b)"
```

---

## Task 2: `scraper.extract.fetch` — httpx + Playwright wrapper

HTTP fetcher con timeout, retry (tenacity), detection de JS-rendered pages, y fallback a Playwright.

**Files:**
- Create: `src/scraper/extract/__init__.py`
- Create: `src/scraper/extract/fetch.py`
- Create: `tests/unit/test_fetch.py`
- Modify: `pyproject.toml` (agregar `httpx`, `playwright`, `lxml`)

- [ ] **Step 1: Install dependencies**

```bash
poetry add httpx playwright lxml beautifulsoup4
poetry run playwright install chromium
```

(Playwright Chromium download: ~300MB. Documentar en README en Task 19.)

- [ ] **Step 2: Write failing tests**

`tests/unit/test_fetch.py`:

```python
import pytest


def test_is_js_rendered_short_body():
    from scraper.extract.fetch import is_js_rendered

    html = "<html><body></body></html>"
    assert is_js_rendered(html) is True


def test_is_js_rendered_enable_javascript_noscript():
    from scraper.extract.fetch import is_js_rendered

    html = """<html><body>
        <noscript>Please enable JavaScript to view this site</noscript>
        <div id="app"></div>
    </body></html>"""
    assert is_js_rendered(html) is True


def test_is_js_rendered_normal_content():
    from scraper.extract.fetch import is_js_rendered

    html = "<html><body>" + ("<p>real content here</p>" * 50) + "</body></html>"
    assert is_js_rendered(html) is False


async def test_fetch_url_httpx_returns_html(httpx_mock):
    from scraper.extract.fetch import fetch_url

    httpx_mock.add_response(
        url="https://example.com/ficha",
        text="<html><body>content</body></html>",
        status_code=200,
    )
    html = await fetch_url("https://example.com/ficha")
    assert "content" in html


async def test_fetch_url_timeout_raises(httpx_mock):
    from scraper.extract.fetch import FetchError, fetch_url
    import httpx as hx

    httpx_mock.add_exception(hx.TimeoutException("timed out"))
    with pytest.raises(FetchError):
        await fetch_url("https://slow.example.com/x", timeout=1.0)
```

Y agregar dependencia de test:

```bash
poetry add --group dev pytest-httpx
```

- [ ] **Step 3: Run — fail (ImportError)**

```bash
poetry run pytest tests/unit/test_fetch.py -v
```

- [ ] **Step 4: Implement `src/scraper/extract/__init__.py`**

```python
from scraper.extract.fetch import FetchError, fetch_url, fetch_with_playwright, is_js_rendered

__all__ = ["FetchError", "fetch_url", "fetch_with_playwright", "is_js_rendered"]
```

- [ ] **Step 5: Implement `src/scraper/extract/fetch.py`**

```python
"""HTTP fetcher with httpx primary + Playwright fallback for JS-rendered pages."""
from __future__ import annotations

import re

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = structlog.get_logger()

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 SabbiBot/0.1"
)
_DEFAULT_TIMEOUT = 30.0
_NOSCRIPT_JS_PATTERN = re.compile(
    r"<noscript>[^<]*(enable\s+javascript|javascript\s+must\s+be\s+enabled)",
    re.IGNORECASE,
)


class FetchError(RuntimeError):
    """Raised when a URL cannot be fetched (timeout, network, non-2xx)."""


def is_js_rendered(html: str) -> bool:
    """Heuristic: page needs JS to be usable."""
    if _NOSCRIPT_JS_PATTERN.search(html):
        return True
    # Strip tags loosely and measure visible body
    visible = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    visible = re.sub(r"<style[^>]*>.*?</style>", "", visible, flags=re.DOTALL | re.IGNORECASE)
    visible = re.sub(r"<[^>]+>", "", visible)
    return len(visible.strip()) < 500


@retry(
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    reraise=True,
)
async def _fetch_with_httpx(url: str, timeout: float) -> str:
    headers = {"User-Agent": _USER_AGENT}
    async with httpx.AsyncClient(
        timeout=timeout, headers=headers, follow_redirects=True
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text


async def fetch_url(url: str, timeout: float = _DEFAULT_TIMEOUT) -> str:
    """Fetch URL with httpx + retry. Raises FetchError on failure."""
    try:
        html = await _fetch_with_httpx(url, timeout)
        log.info("fetch_url_success", url=url, length=len(html))
        return html
    except httpx.TimeoutException as e:
        raise FetchError(f"Timeout fetching {url}: {e}") from e
    except httpx.HTTPStatusError as e:
        raise FetchError(f"HTTP {e.response.status_code} for {url}") from e
    except httpx.TransportError as e:
        raise FetchError(f"Transport error for {url}: {e}") from e


async def fetch_with_playwright(url: str, timeout: float = _DEFAULT_TIMEOUT) -> str:
    """Render page with Chromium for JS-heavy sites."""
    # Lazy import so Playwright isn't required for pure-httpx paths
    from playwright.async_api import async_playwright

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(user_agent=_USER_AGENT)
                page = await context.new_page()
                await page.goto(url, timeout=timeout * 1000)
                await page.wait_for_load_state("networkidle", timeout=timeout * 1000)
                html = await page.content()
                log.info("fetch_playwright_success", url=url, length=len(html))
                return html
            finally:
                await browser.close()
    except Exception as e:
        raise FetchError(f"Playwright fetch failed for {url}: {e}") from e
```

- [ ] **Step 6: Run — tests pass**

```bash
poetry run pytest tests/unit/test_fetch.py -v
```

Expected: 5 passed.

- [ ] **Step 7: Full suite green**

```bash
poetry run pytest -q 2>&1 | tail -3
```

- [ ] **Step 8: Lint + commit**

```bash
poetry run ruff check src/scraper/extract/ tests/unit/test_fetch.py
git add src/scraper/extract/__init__.py src/scraper/extract/fetch.py tests/unit/test_fetch.py pyproject.toml poetry.lock
git commit -m "feat: add scraper.extract.fetch (httpx + Playwright fallback)"
```

---

## Task 3: Extractor agent — prompt + `extract_with_claude()` + mocked tests

El agente extractor. Análogo al classifier/reviewer pero con prompt dedicado y schema `ExtractedFicha`.

**Files:**
- Create: `src/scraper/agents/prompts/extractor_system.md`
- Create: `src/scraper/agents/extractor.py`
- Create: `tests/integration/test_extractor_mocked.py`

- [ ] **Step 1: Create `src/scraper/agents/prompts/extractor_system.md`**

```markdown
Eres el Extractor de Productos de Inversión de Sabbi. Recibes el texto crudo + tablas de una ficha técnica (HTML limpio, PDF extraído, o contenido de web search). Tu trabajo es poblar una `ExtractedFicha` con los 9 atributos canónicos, citando el `raw_quote` literal de donde sacaste cada valor.

**IMPORTANTE: Tu job NO es clasificar.** El Clasificador después refina usando reglas. Vos solo extraés lo que ves en el texto, mapeando a valores canónicos cuando es obvio y dejando `null` (confidence 0) cuando no.

## TAXONOMÍAS CANÓNICAS (lista cerrada — usar estos valores cuando puedas)

### Clases de Activo Macro (6)
{{ASSET_CLASSES}}

### Subyacentes Canónicos ({{N_CANONICAL_ASSETS}})
{{CANONICAL_ASSETS}}

### Regiones Geográficas (5)
{{REGIONS}}

## OUTPUT — formato obligatorio

Responde EXACTAMENTE con un objeto JSON con esta estructura:

```json
{
  "source_type": "html",
  "source_confidence": 0.85,
  "raw_text": "texto limpio original (primeras 2000 chars)",
  "tables": [],
  "attributes": {
    "nombre": {"value": "Credicorp Crecimiento", "confidence": 1.0, "reasoning": "...", "raw_quote": "..."},
    "foco_geografico": {"value": {"Perú": 100}, "confidence": 0.9, "reasoning": "...", "raw_quote": "..."},
    "clase_activo": {"value": {"Mercados Públicos - Variable": 100}, "confidence": 0.85, "reasoning": "...", "raw_quote": "..."},
    "subyacente": {"value": {"Acciones Peru": 100}, "confidence": 0.85, "reasoning": "...", "raw_quote": "..."},
    "comision": {"value": 0.0325, "confidence": 0.95, "reasoning": "...", "raw_quote": "comisión 3.25%"},
    "moneda": {"value": "soles", "confidence": 1.0, "reasoning": "...", "raw_quote": "S/."},
    "administrador": {"value": "Credicorp Capital", "confidence": 0.9, "reasoning": "...", "raw_quote": "..."},
    "gestor": {"value": "Credicorp Capital", "confidence": 0.9, "reasoning": "...", "raw_quote": "..."},
    "liquidez": {"value": "Inmediata", "confidence": 0.8, "reasoning": "...", "raw_quote": "..."},
    "minimo_inversion": {"value": "100 soles", "confidence": 0.9, "reasoning": "...", "raw_quote": "..."}
  },
  "citations": ["https://..."]
}
```

## Reglas de extracción

- **Valor canónico cuando es obvio; raw cuando no.** Si la ficha dice "Mercados Públicos - Variable" textual, usá ese valor canónico. Si dice algo ambiguo como "renta variable peruana", dejá `value: "renta variable peruana"` y `confidence: 0.6` — el classifier después lo normaliza.
- **Porcentajes como números (no strings).** `{"Perú": 100}`, no `{"Perú": "100%"}`.
- **Comisión como decimal.** 3.25% → `0.0325`. "sin comisión" → `0.0`. No mencionada → `null`.
- **Raw quote obligatorio.** Copia literal de hasta 200 chars del texto fuente que justifica el valor. Si viene de una tabla, cita la celda: `"tabla 2, fila 'Moneda', celda 'PEN'"`.
- **Confidence honesta.** Si tuviste que inferir, baja confidence a ≤0.75. Si el valor viene citado literal, ≥0.90.
- **NO inventes.** Si el atributo no está en el texto, `value: null, confidence: 0.0, reasoning: "no encontrado"`.
- **NO apliques reglas de clasificación.** Vos solo extraés; las reglas las aplica el classifier después. Ej: NO hagas conversiones como "Bloomberg Aggregate → 100% Bonos Corp IG". Si la ficha dice "Bloomberg US Aggregate", reportá eso literal.

## INPUT QUE VAS A RECIBIR

El mensaje `user` contendrá:

```
Source URL: https://... (o "PDF upload" o "websearch")
Source type: html|pdf_text|pdf_vision|websearch

=== RAW TEXT ===
<texto limpio sin HTML tags>

=== TABLES ===
Tabla 1:
| col1 | col2 |
| v1a  | v1b  |
...

=== METADATA ===
Key-value pairs de HTTP headers, PDF metadata, etc.
```

Respondé SOLO el JSON. Sin markdown fences.
```

- [ ] **Step 2: Write failing tests**

`tests/integration/test_extractor_mocked.py`:

```python
import json
from datetime import datetime, timezone


async def test_extract_with_claude_parses_valid_json(mock_llm_client):
    from scraper.agents.extractor import extract_with_claude

    output_json = json.dumps({
        "source_type": "html",
        "source_confidence": 0.85,
        "raw_text": "texto",
        "tables": [],
        "attributes": {
            "nombre": {"value": "X", "confidence": 1.0, "reasoning": "r", "raw_quote": "X"},
            "moneda": {"value": "soles", "confidence": 1.0, "reasoning": "PEN", "raw_quote": "S/."},
        },
        "citations": ["https://a.example"],
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(output_json)

    ficha = await extract_with_claude(
        llm=mock_llm_client,
        source_url="https://a.example",
        source_type="html",
        raw_text="texto crudo",
        tables=[],
    )
    assert ficha.source_url == "https://a.example"
    assert ficha.attributes["moneda"].value == "soles"
    assert ficha.attributes["nombre"].raw_quote == "X"


async def test_extract_with_claude_strips_fences(mock_llm_client):
    from scraper.agents.extractor import extract_with_claude

    fenced = (
        "```json\n"
        + json.dumps({
            "source_type": "pdf_text",
            "source_confidence": 0.8,
            "raw_text": "t",
            "tables": [],
            "attributes": {"nombre": {"value": "Y", "confidence": 1.0, "reasoning": "", "raw_quote": "Y"}},
            "citations": [],
        })
        + "\n```"
    )
    mock_llm_client.call.return_value = mock_llm_client.make_result(fenced)

    ficha = await extract_with_claude(
        llm=mock_llm_client,
        source_url=None,
        source_type="pdf_text",
        raw_text="pdf text",
        tables=[],
    )
    assert ficha.source_type == "pdf_text"
    assert ficha.attributes["nombre"].value == "Y"


async def test_extract_with_claude_raises_on_bad_json(mock_llm_client):
    from scraper.agents.extractor import ExtractorParseError, extract_with_claude

    mock_llm_client.call.return_value = mock_llm_client.make_result("not json")
    import pytest as _pt
    with _pt.raises(ExtractorParseError):
        await extract_with_claude(
            llm=mock_llm_client,
            source_url=None,
            source_type="html",
            raw_text="",
            tables=[],
        )
```

- [ ] **Step 3: Run — fails**

```bash
poetry run pytest tests/integration/test_extractor_mocked.py -v
```

- [ ] **Step 4: Implement `src/scraper/agents/extractor.py`**

```python
"""Extractor agent — uses Claude Sonnet 4.6 to pull structured ficha from raw text/tables."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from scraper.agents.classifier import _strip_fences
from scraper.agents.types import AttributeExtraction, ExtractedFicha
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
    source_url: str | None, source_type: str, raw_text: str, tables: list[list[list[str]]]
) -> str:
    src = source_url or f"({source_type} upload)"
    return (
        f"Source URL: {src}\n"
        f"Source type: {source_type}\n\n"
        f"=== RAW TEXT ===\n{raw_text[:20000]}\n\n"
        f"=== TABLES ===\n{_render_tables_md(tables)}\n"
    )


async def extract_with_claude(
    *,
    llm: LLMClient,
    source_url: str | None,
    source_type: str,
    raw_text: str,
    tables: list[list[list[str]]],
) -> ExtractedFicha:
    """Run the extractor agent. Returns a validated ExtractedFicha."""
    start = time.monotonic()
    system_blocks = build_extractor_system_blocks()
    user_msg = _build_user_message(source_url, source_type, raw_text, tables)

    result = await llm.call(
        model=EXTRACTOR_MODEL,
        system=system_blocks,
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=4096,
    )

    clean = _strip_fences(result.response_text)
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError as e:
        raise ExtractorParseError(
            f"Extractor output is not valid JSON: {e}\nOutput: {clean[:500]}"
        ) from e

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

    duration_ms = int((time.monotonic() - start) * 1000)

    return ExtractedFicha(
        source_url=source_url,
        source_type=source_type,
        source_confidence=float(payload.get("source_confidence", 0.5)),
        fetched_at=datetime.now(tz=timezone.utc),
        raw_text=raw_text[:20000],
        tables=tables,
        attributes=attributes,
        citations=list(payload.get("citations") or []),
        extraction_cost_usd=result.cost.total_usd if hasattr(result.cost, "total_usd") else 0.0,
        extraction_duration_ms=duration_ms,
    )
```

- [ ] **Step 5: Run tests — pass**

```bash
poetry run pytest tests/integration/test_extractor_mocked.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Full suite**

```bash
poetry run pytest -q 2>&1 | tail -3
```

- [ ] **Step 7: Lint + commit**

```bash
poetry run ruff check src/scraper/agents/extractor.py src/scraper/agents/prompts/extractor_system.md tests/integration/test_extractor_mocked.py
git add src/scraper/agents/extractor.py src/scraper/agents/prompts/extractor_system.md tests/integration/test_extractor_mocked.py
git commit -m "feat: add extractor agent (Sonnet 4.6) with thick canonical extraction"
```

---

## Task 4: HTML extractor (BeautifulSoup + Claude)

Orquesta fetch → clean HTML → Claude extraction. Incluye captura de tablas.

**Files:**
- Create: `src/scraper/extract/html.py`
- Create: `tests/fixtures/html/credicorpcapital_sample.html`
- Create: `tests/unit/test_extract_html.py`

- [ ] **Step 1: Create HTML fixture**

Ejecutar:

```bash
mkdir -p tests/fixtures/html
```

Crear `tests/fixtures/html/credicorpcapital_sample.html` con contenido representativo:

```html
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Credicorp Capital — Fondo Crecimiento</title>
<script>var tracking = true;</script>
<style>.hidden { display: none; }</style>
</head>
<body>
<nav>Top nav that should be stripped</nav>
<main>
  <h1>Fondo Crecimiento</h1>
  <p>Administrador: Credicorp Capital SAF S.A.</p>
  <p>Gestor: Credicorp Capital SAF S.A.</p>
  <p>Moneda: Soles</p>
  <p>Liquidez: inmediata</p>
  <table>
    <tr><th>Atributo</th><th>Valor</th></tr>
    <tr><td>Clase de activo</td><td>Mercados Públicos - Variable</td></tr>
    <tr><td>Foco geográfico</td><td>Perú 100%</td></tr>
    <tr><td>Comisión</td><td>3.25%</td></tr>
    <tr><td>Mínimo de inversión</td><td>100 soles</td></tr>
  </table>
</main>
<footer>Footer stripped</footer>
</body>
</html>
```

- [ ] **Step 2: Write failing tests**

`tests/unit/test_extract_html.py`:

```python
from pathlib import Path
from unittest.mock import AsyncMock


def test_clean_html_removes_scripts_styles_nav():
    from scraper.extract.html import clean_html

    html = """<html><body>
        <script>junk</script>
        <style>.x{}</style>
        <nav>nav</nav>
        <main><p>keep me</p></main>
        <footer>footer</footer>
    </body></html>"""
    raw_text, tables = clean_html(html)
    assert "keep me" in raw_text
    assert "junk" not in raw_text
    assert ".x{}" not in raw_text
    assert "nav" not in raw_text or raw_text.count("nav") <= 1  # navigable text not word


def test_clean_html_extracts_table():
    from scraper.extract.html import clean_html

    html = """<html><body><main>
        <table>
          <tr><th>A</th><th>B</th></tr>
          <tr><td>1</td><td>2</td></tr>
        </table>
    </main></body></html>"""
    _, tables = clean_html(html)
    assert len(tables) == 1
    assert tables[0] == [["A", "B"], ["1", "2"]]


def test_clean_html_fixture_credicorp():
    from scraper.extract.html import clean_html

    fixture = Path(__file__).parents[1] / "fixtures" / "html" / "credicorpcapital_sample.html"
    html = fixture.read_text(encoding="utf-8")
    raw_text, tables = clean_html(html)

    assert "Fondo Crecimiento" in raw_text
    assert "Credicorp Capital SAF" in raw_text
    assert len(tables) == 1
    assert any("Comisión" in cell for row in tables[0] for cell in row)


async def test_extract_from_url_orchestrates_fetch_and_claude(monkeypatch, mock_llm_client):
    import json

    from scraper.extract import html as html_mod

    async def fake_fetch(url: str, timeout: float = 30.0) -> str:
        return "<html><body><main><p>hello world</p></main></body></html>"

    monkeypatch.setattr(html_mod, "fetch_url", fake_fetch)

    async def fake_extract(**kwargs):
        from scraper.agents.types import AttributeExtraction, ExtractedFicha
        from datetime import datetime, timezone
        return ExtractedFicha(
            source_url=kwargs["source_url"],
            source_type="html",
            source_confidence=0.9,
            fetched_at=datetime.now(tz=timezone.utc),
            raw_text=kwargs["raw_text"],
            tables=kwargs["tables"],
            attributes={
                "nombre": AttributeExtraction(value="X", confidence=1.0, reasoning="r", raw_quote="q")
            },
            citations=[kwargs["source_url"]],
            extraction_cost_usd=0.01,
            extraction_duration_ms=500,
        )

    monkeypatch.setattr(html_mod, "extract_with_claude", fake_extract)

    ficha = await html_mod.extract_from_url(
        url="https://example.com/x", llm=mock_llm_client
    )
    assert ficha.source_url == "https://example.com/x"
    assert "hello world" in ficha.raw_text
```

- [ ] **Step 3: Run — fails**

```bash
poetry run pytest tests/unit/test_extract_html.py -v
```

- [ ] **Step 4: Implement `src/scraper/extract/html.py`**

```python
"""HTML extractor — fetch, clean, feed to Claude extractor agent."""
from __future__ import annotations

from typing import Any

import structlog
from bs4 import BeautifulSoup

from scraper.agents.extractor import extract_with_claude
from scraper.agents.types import ExtractedFicha
from scraper.extract.fetch import fetch_url, fetch_with_playwright, is_js_rendered
from scraper.llm import LLMClient

log = structlog.get_logger()

_STRIP_TAGS = ("script", "style", "nav", "footer", "aside", "noscript", "iframe", "header")


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


async def extract_from_url(*, url: str, llm: LLMClient) -> ExtractedFicha:
    """Fetch URL → clean → extract via Claude. Falls back to Playwright for JS pages."""
    html = await fetch_url(url)
    if is_js_rendered(html):
        log.info("fallback_playwright", url=url)
        html = await fetch_with_playwright(url)

    raw_text, tables = clean_html(html)
    return await extract_with_claude(
        llm=llm,
        source_url=url,
        source_type="html",
        raw_text=raw_text,
        tables=tables,
    )
```

- [ ] **Step 5: Tests pass**

```bash
poetry run pytest tests/unit/test_extract_html.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Lint + commit**

```bash
poetry run ruff check src/scraper/extract/html.py tests/unit/test_extract_html.py
git add src/scraper/extract/html.py tests/unit/test_extract_html.py tests/fixtures/html/credicorpcapital_sample.html
git commit -m "feat: HTML extractor — clean + table capture + Claude orchestration"
```

---

## Task 5: PDF text extractor (pypdf + pdfplumber)

Extract text y tablas de PDFs basados en texto. Fallback a vision en Task 6.

**Files:**
- Create: `src/scraper/extract/pdf.py`
- Create: `tests/fixtures/pdfs/ficha_text.pdf` (fixture mínima)
- Create: `tests/unit/test_extract_pdf.py`
- Modify: `pyproject.toml` (agregar `pypdf`, `pdfplumber`)

- [ ] **Step 1: Install deps**

```bash
poetry add pypdf pdfplumber
```

- [ ] **Step 2: Create text PDF fixture using reportlab**

Tests generan el PDF on-the-fly para no comitear bytes binarios grandes.

```bash
poetry add --group dev reportlab
```

- [ ] **Step 3: Write failing tests**

`tests/unit/test_extract_pdf.py`:

```python
from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def _write_text_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica", 14)
    c.drawString(72, 720, "Ficha Técnica - Fondo Ejemplo")
    c.setFont("Helvetica", 10)
    c.drawString(72, 680, "Administrador: Ejemplo Capital SAF")
    c.drawString(72, 660, "Moneda: Soles (PEN)")
    c.drawString(72, 640, "Comisión: 2.50% anual")
    c.drawString(72, 620, "Clase: Mercados Públicos - Fijo")
    c.showPage()
    c.save()


def _write_empty_pdf(path: Path) -> None:
    # Single blank page — simulates scanned image-only PDF
    c = canvas.Canvas(str(path), pagesize=letter)
    c.showPage()
    c.save()


def test_extract_pdf_text_happy_path(tmp_path):
    from scraper.extract.pdf import extract_pdf_text

    pdf = tmp_path / "ficha.pdf"
    _write_text_pdf(pdf)

    text, tables = extract_pdf_text(pdf)
    assert "Ejemplo Capital SAF" in text
    assert "Moneda" in text or "Comisión" in text


def test_extract_pdf_text_detects_empty(tmp_path):
    from scraper.extract.pdf import extract_pdf_text, looks_scanned

    pdf = tmp_path / "empty.pdf"
    _write_empty_pdf(pdf)

    text, _ = extract_pdf_text(pdf)
    assert looks_scanned(text) is True


async def test_extract_from_pdf_uses_text_mode(tmp_path, monkeypatch, mock_llm_client):
    from scraper.extract import pdf as pdf_mod

    pdf_path = tmp_path / "ficha.pdf"
    _write_text_pdf(pdf_path)

    seen_args: dict = {}

    async def fake_extract(**kwargs):
        seen_args.update(kwargs)
        from scraper.agents.types import AttributeExtraction, ExtractedFicha
        from datetime import datetime, timezone
        return ExtractedFicha(
            source_url=None,
            source_type=kwargs["source_type"],
            source_confidence=0.9,
            fetched_at=datetime.now(tz=timezone.utc),
            raw_text=kwargs["raw_text"],
            tables=kwargs["tables"],
            attributes={
                "nombre": AttributeExtraction(value="F", confidence=1.0, reasoning="", raw_quote="")
            },
            citations=[],
            extraction_cost_usd=0.0,
            extraction_duration_ms=0,
        )

    monkeypatch.setattr(pdf_mod, "extract_with_claude", fake_extract)

    ficha = await pdf_mod.extract_from_pdf(path=pdf_path, llm=mock_llm_client)
    assert ficha.source_type == "pdf_text"
    assert seen_args["source_type"] == "pdf_text"
```

- [ ] **Step 4: Run — fails**

```bash
poetry run pytest tests/unit/test_extract_pdf.py -v
```

- [ ] **Step 5: Implement `src/scraper/extract/pdf.py`**

```python
"""PDF text extractor — pypdf for text, pdfplumber for tables, Claude for structuring."""
from __future__ import annotations

from pathlib import Path

import pdfplumber
import pypdf
import structlog

from scraper.agents.extractor import extract_with_claude
from scraper.agents.types import ExtractedFicha
from scraper.llm import LLMClient

log = structlog.get_logger()

_SCANNED_THRESHOLD_CHARS = 200


def looks_scanned(text: str) -> bool:
    """Heuristic: text extraction yielded so little content the PDF is probably scanned."""
    return len(text.strip()) < _SCANNED_THRESHOLD_CHARS


def extract_pdf_text(path: Path) -> tuple[str, list[list[list[str]]]]:
    """Return (text, tables) from a text-based PDF."""
    text_parts: list[str] = []
    reader = pypdf.PdfReader(str(path))
    for page in reader.pages:
        page_text = page.extract_text() or ""
        text_parts.append(page_text)
    text = "\n".join(text_parts)

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


async def extract_from_pdf(*, path: Path, llm: LLMClient) -> ExtractedFicha:
    """Text-mode PDF extraction. For scanned PDFs, caller should dispatch to vision."""
    text, tables = extract_pdf_text(path)
    if looks_scanned(text):
        # Caller decides how to handle — raise so extract_one's CLI can route to vision
        from scraper.extract.vision import extract_from_pdf_vision

        log.info("pdf_looks_scanned_using_vision", path=str(path), text_len=len(text))
        return await extract_from_pdf_vision(path=path, llm=llm)

    return await extract_with_claude(
        llm=llm,
        source_url=None,
        source_type="pdf_text",
        raw_text=text,
        tables=tables,
    )
```

- [ ] **Step 6: Run tests (note: `extract_from_pdf_vision` doesn't exist yet — add stub)**

Agrega stub temporal en `src/scraper/extract/vision.py` para que el import no rompa:

```python
"""PDF vision extractor stub — full implementation in Task 6."""
from __future__ import annotations

from pathlib import Path

from scraper.agents.types import ExtractedFicha
from scraper.llm import LLMClient


async def extract_from_pdf_vision(*, path: Path, llm: LLMClient) -> ExtractedFicha:
    raise NotImplementedError("Vision fallback implemented in Task 6")
```

```bash
poetry run pytest tests/unit/test_extract_pdf.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Lint + commit**

```bash
poetry run ruff check src/scraper/extract/pdf.py src/scraper/extract/vision.py tests/unit/test_extract_pdf.py
git add src/scraper/extract/pdf.py src/scraper/extract/vision.py tests/unit/test_extract_pdf.py pyproject.toml poetry.lock
git commit -m "feat: PDF text extractor (pypdf + pdfplumber) with vision fallback stub"
```

---

## Task 6: PDF vision extractor (Claude vision fallback)

Renderiza páginas como imágenes y las manda a Claude para extracción vision.

**Files:**
- Modify: `src/scraper/extract/vision.py`
- Modify: `src/scraper/extract/__init__.py` (export)
- Create: `tests/unit/test_extract_vision.py`
- Modify: `pyproject.toml` (agregar `pdf2image` o usar pypdf's rendering — see below)

- [ ] **Step 1: Install pdf2image**

```bash
poetry add pdf2image
```

**Nota:** `pdf2image` requiere `poppler` instalado en el sistema. En Windows viene con binarios via `pip install pdf2image` + descargar poppler de https://github.com/oschwartz10612/poppler-windows. Documentar en README (Task 19).

- [ ] **Step 2: Write failing test**

`tests/unit/test_extract_vision.py`:

```python
from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def _write_empty_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    c.showPage()
    c.save()


async def test_extract_from_pdf_vision_sends_images_to_claude(tmp_path, monkeypatch, mock_llm_client):
    import base64
    import json

    from scraper.extract import vision as vision_mod
    from scraper.llm.client import CallResult
    from scraper.llm.cost import ClaudeCost
    from unittest.mock import MagicMock

    pdf_path = tmp_path / "scan.pdf"
    _write_empty_pdf(pdf_path)

    # Monkeypatch pdf rendering to produce deterministic fake PNG bytes
    fake_png = b"\x89PNG\r\n\x1a\nfake"
    monkeypatch.setattr(vision_mod, "_pdf_pages_to_png_bytes", lambda p: [fake_png])

    # Mock llm response: valid extractor JSON
    output_json = json.dumps({
        "source_type": "pdf_vision",
        "source_confidence": 0.75,
        "raw_text": "",
        "tables": [],
        "attributes": {
            "nombre": {"value": "Scanned Fondo", "confidence": 0.8, "reasoning": "vision", "raw_quote": ""}
        },
        "citations": [],
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(output_json)

    ficha = await vision_mod.extract_from_pdf_vision(path=pdf_path, llm=mock_llm_client)

    assert ficha.source_type == "pdf_vision"
    assert ficha.attributes["nombre"].value == "Scanned Fondo"
    # Confirm the user message contained an image block
    call = mock_llm_client.call.call_args
    msgs = call.kwargs["messages"]
    content = msgs[0]["content"]
    assert isinstance(content, list)
    assert any(block["type"] == "image" for block in content)
```

- [ ] **Step 3: Run — fails**

```bash
poetry run pytest tests/unit/test_extract_vision.py -v
```

- [ ] **Step 4: Implement `src/scraper/extract/vision.py`**

Reemplazar el stub con implementación completa:

```python
"""PDF vision extractor — rasterize pages + Claude vision extraction."""
from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import structlog

from scraper.agents.classifier import _strip_fences
from scraper.agents.extractor import (
    ExtractorParseError,
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


async def extract_from_pdf_vision(*, path: Path, llm: LLMClient) -> ExtractedFicha:
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
    content_blocks.append(
        {
            "type": "text",
            "text": (
                "Extrae la ficha del PDF escaneado mostrado arriba. "
                "Seguí el formato JSON del system prompt. Responde SOLO el JSON."
            ),
        }
    )

    system_blocks = build_extractor_system_blocks()
    result = await llm.call(
        model=VISION_MODEL,
        system=system_blocks,
        messages=[{"role": "user", "content": content_blocks}],
        max_tokens=4096,
    )

    clean = _strip_fences(result.response_text)
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError as e:
        raise ExtractorParseError(
            f"Vision extractor output is not valid JSON: {e}\nOutput: {clean[:500]}"
        ) from e

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
        fetched_at=datetime.now(tz=timezone.utc),
        raw_text="",  # vision didn't produce text
        tables=[],
        attributes=attributes,
        citations=[f"page_{i+1}" for i in range(len(png_bytes_list))],
        extraction_cost_usd=result.cost.total_usd if hasattr(result.cost, "total_usd") else 0.0,
        extraction_duration_ms=duration_ms,
    )
```

- [ ] **Step 5: Update `src/scraper/extract/__init__.py`**

```python
from scraper.extract.fetch import FetchError, fetch_url, fetch_with_playwright, is_js_rendered
from scraper.extract.html import clean_html, extract_from_url
from scraper.extract.pdf import extract_from_pdf, extract_pdf_text, looks_scanned
from scraper.extract.vision import extract_from_pdf_vision

__all__ = [
    "FetchError",
    "clean_html",
    "extract_from_pdf",
    "extract_from_pdf_vision",
    "extract_from_url",
    "extract_pdf_text",
    "fetch_url",
    "fetch_with_playwright",
    "is_js_rendered",
    "looks_scanned",
]
```

- [ ] **Step 6: Test passes**

```bash
poetry run pytest tests/unit/test_extract_vision.py -v
```

Expected: 1 passed.

- [ ] **Step 7: Full suite**

```bash
poetry run pytest -q 2>&1 | tail -3
```

- [ ] **Step 8: Lint + commit**

```bash
poetry run ruff check src/scraper/extract/vision.py src/scraper/extract/__init__.py tests/unit/test_extract_vision.py
git add src/scraper/extract/vision.py src/scraper/extract/__init__.py tests/unit/test_extract_vision.py pyproject.toml poetry.lock
git commit -m "feat: PDF vision extractor via Claude image blocks"
```

---

## Task 7: `CascadeResult` + orchestrator skeleton

Armar la estructura básica de la cascada. Levels N0/N1/N2/N3 se implementan en tasks siguientes.

**Files:**
- Create: `src/scraper/search/__init__.py`
- Create: `src/scraper/search/types.py`
- Create: `src/scraper/search/cascade.py`
- Create: `tests/unit/test_cascade.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_cascade.py`:

```python
from datetime import datetime, timezone


def _make_ficha(url: str, conf: float):
    from scraper.agents.types import AttributeExtraction, ExtractedFicha
    return ExtractedFicha(
        source_url=url,
        source_type="html",
        source_confidence=conf,
        fetched_at=datetime.now(tz=timezone.utc),
        raw_text="",
        tables=[],
        attributes={"nombre": AttributeExtraction(value="x", confidence=conf, reasoning="", raw_quote="")},
        citations=[url],
        extraction_cost_usd=0.0,
        extraction_duration_ms=0,
    )


def test_cascade_result_construction():
    from scraper.search.types import CascadeResult

    f = _make_ficha("https://a", 0.9)
    r = CascadeResult(level=1, fichas=[f], low_quality=False)
    assert r.level == 1
    assert r.fichas[0].source_url == "https://a"
    assert r.best_confidence == 0.9


def test_cascade_result_empty_best_confidence_zero():
    from scraper.search.types import CascadeResult

    r = CascadeResult(level=2, fichas=[], low_quality=True)
    assert r.best_confidence == 0.0


def test_merge_candidates_dedup_by_source_url():
    from scraper.search.cascade import merge_candidates

    a = [_make_ficha("https://a", 0.9)]
    b = [_make_ficha("https://a", 0.7), _make_ficha("https://b", 0.8)]
    merged = merge_candidates(a, b)
    urls = sorted(f.source_url for f in merged)
    assert urls == ["https://a", "https://b"]


async def test_run_cascade_short_circuits_on_n0_hit(monkeypatch):
    from scraper.search import cascade as cascade_mod
    from scraper.search.types import CascadeResult

    async def fake_n0(nombre, session):
        return _make_ficha("db://existing", 1.0)

    async def fail(*args, **kwargs):
        raise AssertionError("should not reach N1")

    monkeypatch.setattr(cascade_mod, "lookup_db", fake_n0)
    monkeypatch.setattr(cascade_mod, "run_n1_parsers", fail)

    result = await cascade_mod.run_cascade(nombre="X", session=None, llm=None)
    assert result.level == 0
    assert len(result.fichas) == 1


async def test_run_cascade_skips_n2_when_n1_high_confidence(monkeypatch):
    from scraper.search import cascade as cascade_mod

    async def no_db(nombre, session):
        return None

    async def hi_n1(nombre, llm):
        return [_make_ficha("https://x", 0.9)]

    async def fail_n2(*args, **kwargs):
        raise AssertionError("should not reach N2")

    monkeypatch.setattr(cascade_mod, "lookup_db", no_db)
    monkeypatch.setattr(cascade_mod, "run_n1_parsers", hi_n1)
    monkeypatch.setattr(cascade_mod, "run_claude_websearch", fail_n2)

    result = await cascade_mod.run_cascade(nombre="X", session=None, llm=None)
    assert result.level == 1
    assert result.best_confidence == 0.9
```

- [ ] **Step 2: Run — fails**

```bash
poetry run pytest tests/unit/test_cascade.py -v
```

- [ ] **Step 3: Implement `src/scraper/search/types.py`**

```python
"""Shared types for the search cascade."""
from __future__ import annotations

from dataclasses import dataclass, field

from scraper.agents.types import ExtractedFicha


@dataclass(frozen=True)
class CascadeResult:
    """Result of running the search cascade for a product name."""
    level: int  # 0=DB, 1=known targets, 2=web_search, 3=intensive
    fichas: list[ExtractedFicha] = field(default_factory=list)
    low_quality: bool = False  # True if we fell through without a confident hit

    @property
    def best_confidence(self) -> float:
        return max((f.source_confidence for f in self.fichas), default=0.0)
```

- [ ] **Step 4: Implement `src/scraper/search/cascade.py`**

```python
"""Search cascade orchestrator: N0 (DB) → N1 (targets) → N2 (web_search) → N3 (intensive)."""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.agents.types import ExtractedFicha
from scraper.config import get_settings
from scraper.llm import LLMClient
from scraper.search.types import CascadeResult

log = structlog.get_logger()

_N1_SHORT_CIRCUIT_CONF = 0.85
_N2_ENOUGH_CONF = 0.70


async def lookup_db(nombre: str, session: AsyncSession | None) -> ExtractedFicha | None:
    """N0 — implemented in Task 8. Stub here."""
    return None


async def run_n1_parsers(nombre: str, llm: LLMClient | None) -> list[ExtractedFicha]:
    """N1 — implemented in Tasks 9-15. Stub here."""
    return []


async def run_claude_websearch(nombre: str, llm: LLMClient | None) -> list[ExtractedFicha]:
    """N2 — implemented in Task 17. Stub here."""
    return []


async def run_claude_intensive(nombre: str, llm: LLMClient | None) -> list[ExtractedFicha]:
    """N3 — implemented in Task 18. Stub here."""
    return []


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
) -> CascadeResult:
    """Run the 4-level cascade and return first-sufficient result."""
    # N0
    db_hit = await lookup_db(nombre, session)
    if db_hit is not None:
        log.info("cascade_hit_n0", nombre=nombre)
        return CascadeResult(level=0, fichas=[db_hit])

    # N1
    n1 = await run_n1_parsers(nombre, llm)
    if _best_confidence(n1) >= _N1_SHORT_CIRCUIT_CONF:
        log.info("cascade_hit_n1", nombre=nombre, hits=len(n1))
        return CascadeResult(level=1, fichas=n1)

    # N2
    n2 = await run_claude_websearch(nombre, llm)
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
    return CascadeResult(level=3, fichas=final, low_quality=_best_confidence(final) < _N2_ENOUGH_CONF)
```

- [ ] **Step 5: Create `src/scraper/search/__init__.py`**

```python
from scraper.search.cascade import merge_candidates, run_cascade
from scraper.search.types import CascadeResult

__all__ = ["CascadeResult", "merge_candidates", "run_cascade"]
```

- [ ] **Step 6: Tests pass**

```bash
poetry run pytest tests/unit/test_cascade.py -v
```

Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
poetry run ruff check src/scraper/search/ tests/unit/test_cascade.py
git add src/scraper/search/ tests/unit/test_cascade.py
git commit -m "feat: cascade skeleton (CascadeResult + run_cascade orchestrator with stubs)"
```

---

## Task 8: N0 — DB fuzzy lookup

Busca un producto existente en la tabla `products` por nombre con fuzzy ratio ≥85.

**Files:**
- Modify: `src/scraper/search/cascade.py` (remove stub, import real impl)
- Create: `src/scraper/search/level0_db.py`
- Create: `tests/unit/test_level0_db.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_level0_db.py`:

```python
from datetime import datetime, timezone


async def test_level0_exact_match(seeded_and_split_session):
    from scraper.search.level0_db import lookup_db

    ficha = await lookup_db("Credicorp Crecimiento", seeded_and_split_session)
    # If the seed has this product, it should hit; if not, None is acceptable —
    # verify the structure only when non-None.
    if ficha is not None:
        assert ficha.source_type == "db"
        assert ficha.source_confidence == 1.0
        assert ficha.attributes["nombre"].value is not None


async def test_level0_fuzzy_match_above_threshold(seeded_and_split_session):
    from scraper.search.level0_db import lookup_db

    # Add a deliberate small typo — fuzzy should still find it
    ficha = await lookup_db("Credicorp Crecimento", seeded_and_split_session)  # missing 'i'
    if ficha is not None:
        assert ficha.source_type == "db"


async def test_level0_no_match_returns_none(seeded_and_split_session):
    from scraper.search.level0_db import lookup_db

    ficha = await lookup_db("Producto Que No Existe Xyz123", seeded_and_split_session)
    assert ficha is None
```

- [ ] **Step 2: Run — fails**

```bash
poetry run pytest tests/unit/test_level0_db.py -v
```

- [ ] **Step 3: Implement `src/scraper/search/level0_db.py`**

```python
"""N0 — lookup by product name in local DB using fuzzy matching."""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.agents.types import AttributeExtraction, ExtractedFicha
from scraper.db.models import Product

log = structlog.get_logger()

_FUZZY_THRESHOLD = 85.0


def _product_to_ficha(p: Product) -> ExtractedFicha:
    def ae(value, conf: float = 1.0, note: str = "from DB") -> AttributeExtraction:
        return AttributeExtraction(value=value, confidence=conf, reasoning=note, raw_quote=None)

    return ExtractedFicha(
        source_url=p.source_url,
        source_type="db",
        source_confidence=1.0,
        fetched_at=datetime.now(tz=timezone.utc),
        raw_text=f"Producto: {p.nombre}",
        tables=[],
        attributes={
            "nombre": ae(p.nombre),
            "foco_geografico": ae(p.foco_geografico or {}),
            "clase_activo": ae(p.clase_activo or {}),
            "subyacente": ae(p.subyacentes or {}),
            "comision": ae(p.comision if p.comision is not None else p.comision_raw),
            "moneda": ae(p.moneda),
            "administrador": ae(p.administrador),
            "gestor": ae(p.gestor),
            "liquidez": ae(p.liquidez),
            "minimo_inversion": ae(p.minimo_inversion),
        },
        citations=[f"db://products/{p.id}"],
        extraction_cost_usd=0.0,
        extraction_duration_ms=0,
    )


async def lookup_db(nombre: str, session: AsyncSession | None) -> ExtractedFicha | None:
    """Fuzzy lookup of product name in DB. Returns the top match ≥ threshold, else None."""
    if session is None:
        return None

    r = await session.execute(select(Product))
    products = list(r.scalars().all())
    if not products:
        return None

    name_to_product = {p.nombre: p for p in products}
    match = process.extractOne(nombre, list(name_to_product.keys()), scorer=fuzz.ratio)
    if match is None:
        return None
    matched_name, score, _ = match
    if score < _FUZZY_THRESHOLD:
        log.info("level0_no_match", nombre=nombre, best=matched_name, score=score)
        return None

    p = name_to_product[matched_name]
    log.info("level0_match", nombre=nombre, matched=matched_name, score=score)
    return _product_to_ficha(p)
```

- [ ] **Step 4: Wire into cascade**

En `src/scraper/search/cascade.py`, reemplazar el stub de `lookup_db` con:

```python
from scraper.search.level0_db import lookup_db  # noqa: F401
```

Y eliminar la definición stub `async def lookup_db(...)` del archivo. Importante: los tests del Task 7 usaban `monkeypatch.setattr(cascade_mod, "lookup_db", ...)` que sigue funcionando mientras el nombre está disponible en el módulo.

- [ ] **Step 5: Tests pass**

```bash
poetry run pytest tests/unit/test_level0_db.py tests/unit/test_cascade.py -v
```

Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
poetry run ruff check src/scraper/search/level0_db.py src/scraper/search/cascade.py tests/unit/test_level0_db.py
git add src/scraper/search/level0_db.py src/scraper/search/cascade.py tests/unit/test_level0_db.py
git commit -m "feat: N0 DB fuzzy lookup (rapidfuzz ≥85) for search cascade"
```

---

## Task 9: N1 — SiteParser protocol + registry + Credicorp parser (reference)

Protocol común para los 7 parsers. Implementamos el primero (Credicorp Capital) como referencia. Los otros 6 en Task 10.

**Files:**
- Create: `src/scraper/search/level1_scrapers/__init__.py`
- Create: `src/scraper/search/level1_scrapers/base.py`
- Create: `src/scraper/search/level1_scrapers/registry.py`
- Create: `src/scraper/search/level1_scrapers/credicorpcapital_com.py`
- Create: `tests/unit/test_level1_base.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_level1_base.py`:

```python
def test_siteparser_protocol_shape():
    from scraper.search.level1_scrapers.base import SiteParser

    # Protocol must declare `domain`, `search_by_name`, `parse_ficha`
    assert hasattr(SiteParser, "domain")


async def test_credicorp_parser_normalizes_search_url():
    from scraper.search.level1_scrapers.credicorpcapital_com import CredicorpCapitalParser

    p = CredicorpCapitalParser()
    assert p.domain == "credicorpcapital.com"
    urls = await p.search_by_name("Credicorp Crecimiento")
    assert all("credicorpcapital.com" in u for u in urls)


def test_registry_exposes_list():
    from scraper.search.level1_scrapers.registry import TARGETS

    assert len(TARGETS) >= 1  # grows to 7 in Task 10
    domains = [p.domain for p in TARGETS]
    assert "credicorpcapital.com" in domains
```

- [ ] **Step 2: Run — fails**

```bash
poetry run pytest tests/unit/test_level1_base.py -v
```

- [ ] **Step 3: Implement `src/scraper/search/level1_scrapers/base.py`**

```python
"""Protocol for per-site parsers (N1 — targets conocidos)."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from scraper.agents.types import ExtractedFicha
from scraper.llm import LLMClient


@runtime_checkable
class SiteParser(Protocol):
    """One parser per known site. Each declares its domain and owns its URL
    patterns / CSS selectors.

    Implementations must be async-safe and stateless (no per-instance caches
    that leak between requests).
    """

    domain: str  # e.g. "credicorpcapital.com"

    async def search_by_name(self, nombre: str) -> list[str]:
        """Given a product name, return candidate URLs on this site."""
        ...

    async def parse_ficha(self, url: str, llm: LLMClient) -> ExtractedFicha:
        """Fetch url, extract structured ficha (by going through Claude extractor)."""
        ...
```

- [ ] **Step 4: Implement `src/scraper/search/level1_scrapers/credicorpcapital_com.py`**

```python
"""Parser for credicorpcapital.com fund fact sheets."""
from __future__ import annotations

from urllib.parse import quote_plus

import structlog

from scraper.agents.types import ExtractedFicha
from scraper.extract.html import extract_from_url
from scraper.llm import LLMClient

log = structlog.get_logger()


class CredicorpCapitalParser:
    domain = "credicorpcapital.com"

    async def search_by_name(self, nombre: str) -> list[str]:
        """Return search-result URLs. Credicorp Capital has a /fondos/ catalog
        and a search endpoint; we return both plus the on-site search as
        candidates. The HTML extractor + Claude will dedup and pick the right one."""
        q = quote_plus(nombre)
        return [
            f"https://www.credicorpcapital.com/buscar?q={q}",
            f"https://www.credicorpcapital.com/fondos/?q={q}",
        ]

    async def parse_ficha(self, url: str, llm: LLMClient) -> ExtractedFicha:
        ficha = await extract_from_url(url=url, llm=llm)
        # Parsers can adjust source_confidence based on their own heuristics;
        # here we mark high because we know the domain is authoritative.
        return _with_source_confidence(ficha, 0.95)


def _with_source_confidence(ficha: ExtractedFicha, conf: float) -> ExtractedFicha:
    """Return a copy of `ficha` with source_confidence overridden."""
    # Dataclasses are frozen; rebuild with dataclasses.replace
    import dataclasses
    return dataclasses.replace(ficha, source_confidence=conf)
```

- [ ] **Step 5: Implement `src/scraper/search/level1_scrapers/registry.py`**

```python
"""Registry of known-site parsers. Grow as new sites are added."""
from __future__ import annotations

from scraper.search.level1_scrapers.base import SiteParser
from scraper.search.level1_scrapers.credicorpcapital_com import CredicorpCapitalParser

TARGETS: list[SiteParser] = [
    CredicorpCapitalParser(),
]
```

- [ ] **Step 6: Implement `src/scraper/search/level1_scrapers/__init__.py`**

```python
from scraper.search.level1_scrapers.base import SiteParser
from scraper.search.level1_scrapers.registry import TARGETS

__all__ = ["SiteParser", "TARGETS"]
```

- [ ] **Step 7: Tests pass**

```bash
poetry run pytest tests/unit/test_level1_base.py -v
```

- [ ] **Step 8: Commit**

```bash
poetry run ruff check src/scraper/search/level1_scrapers/ tests/unit/test_level1_base.py
git add src/scraper/search/level1_scrapers/ tests/unit/test_level1_base.py
git commit -m "feat: N1 SiteParser protocol + registry + Credicorp Capital parser"
```

---

## Task 10: N1 — 6 parsers adicionales (smv, sbs, bcp, corecapital, sabbi, bvl)

Mismo shape que el de Credicorp, con URLs específicas de cada sitio. Un commit por parser.

**Files por parser (7 total):**
- Create: `src/scraper/search/level1_scrapers/smv_gob_pe.py`
- Create: `src/scraper/search/level1_scrapers/sbs_gob_pe.py`
- Create: `src/scraper/search/level1_scrapers/bcpcapital_com.py`
- Create: `src/scraper/search/level1_scrapers/corecapital_pe.py`
- Create: `src/scraper/search/level1_scrapers/sabbi_pe.py`
- Create: `src/scraper/search/level1_scrapers/bvl_com_pe.py`
- Modify: `src/scraper/search/level1_scrapers/registry.py`
- Modify: `tests/unit/test_level1_base.py`

### Task 10.1 — SMV (smv.gob.pe)

- [ ] **Step 1: Implement `smv_gob_pe.py`**

```python
"""Parser for smv.gob.pe — Superintendencia del Mercado de Valores del Perú."""
from __future__ import annotations

from urllib.parse import quote_plus

import dataclasses

from scraper.agents.types import ExtractedFicha
from scraper.extract.html import extract_from_url
from scraper.llm import LLMClient


class SMVGobPeParser:
    domain = "smv.gob.pe"

    async def search_by_name(self, nombre: str) -> list[str]:
        q = quote_plus(nombre)
        return [f"https://www.smv.gob.pe/ConsultasP8/frm_Home.aspx?data={q}"]

    async def parse_ficha(self, url: str, llm: LLMClient) -> ExtractedFicha:
        ficha = await extract_from_url(url=url, llm=llm)
        return dataclasses.replace(ficha, source_confidence=0.90)
```

- [ ] **Step 2: Register in `registry.py`**

```python
from scraper.search.level1_scrapers.smv_gob_pe import SMVGobPeParser
# ... append SMVGobPeParser() to TARGETS list
```

- [ ] **Step 3: Add test assertion**

En `tests/unit/test_level1_base.py`, dentro de `test_registry_exposes_list` agregar:

```python
assert "smv.gob.pe" in domains
```

Run tests, commit:

```bash
poetry run pytest tests/unit/test_level1_base.py -v
poetry run ruff check src/scraper/search/level1_scrapers/smv_gob_pe.py
git add src/scraper/search/level1_scrapers/smv_gob_pe.py src/scraper/search/level1_scrapers/registry.py tests/unit/test_level1_base.py
git commit -m "feat: N1 SMV (smv.gob.pe) parser"
```

### Task 10.2 — SBS (sbs.gob.pe)

Mismo patrón. Contenido del archivo:

```python
"""Parser for sbs.gob.pe — Superintendencia de Banca, Seguros y AFP del Perú."""
from __future__ import annotations

from urllib.parse import quote_plus

import dataclasses

from scraper.agents.types import ExtractedFicha
from scraper.extract.html import extract_from_url
from scraper.llm import LLMClient


class SBSGobPeParser:
    domain = "sbs.gob.pe"

    async def search_by_name(self, nombre: str) -> list[str]:
        q = quote_plus(nombre)
        return [f"https://www.sbs.gob.pe/usuarios/buscar?term={q}"]

    async def parse_ficha(self, url: str, llm: LLMClient) -> ExtractedFicha:
        ficha = await extract_from_url(url=url, llm=llm)
        return dataclasses.replace(ficha, source_confidence=0.90)
```

- [ ] Registrar en `registry.py`, agregar assert en test, commit:

```bash
git add src/scraper/search/level1_scrapers/sbs_gob_pe.py src/scraper/search/level1_scrapers/registry.py tests/unit/test_level1_base.py
git commit -m "feat: N1 SBS (sbs.gob.pe) parser"
```

### Task 10.3 — BCP Capital (bcpcapital.com)

```python
"""Parser for bcpcapital.com — BCP Capital fund fact sheets."""
from __future__ import annotations

from urllib.parse import quote_plus

import dataclasses

from scraper.agents.types import ExtractedFicha
from scraper.extract.html import extract_from_url
from scraper.llm import LLMClient


class BCPCapitalParser:
    domain = "bcpcapital.com"

    async def search_by_name(self, nombre: str) -> list[str]:
        q = quote_plus(nombre)
        return [
            f"https://www.bcpcapital.com/buscar?q={q}",
            f"https://www.bcpcapital.com/fondos/?q={q}",
        ]

    async def parse_ficha(self, url: str, llm: LLMClient) -> ExtractedFicha:
        ficha = await extract_from_url(url=url, llm=llm)
        return dataclasses.replace(ficha, source_confidence=0.93)
```

- [ ] Registrar, assert, commit:

```bash
git add src/scraper/search/level1_scrapers/bcpcapital_com.py src/scraper/search/level1_scrapers/registry.py tests/unit/test_level1_base.py
git commit -m "feat: N1 BCP Capital (bcpcapital.com) parser"
```

### Task 10.4 — Core Capital (corecapital.pe)

```python
"""Parser for corecapital.pe — Core Capital SAFI fund fact sheets."""
from __future__ import annotations

from urllib.parse import quote_plus

import dataclasses

from scraper.agents.types import ExtractedFicha
from scraper.extract.html import extract_from_url
from scraper.llm import LLMClient


class CoreCapitalParser:
    domain = "corecapital.pe"

    async def search_by_name(self, nombre: str) -> list[str]:
        q = quote_plus(nombre)
        return [
            f"https://www.corecapital.pe/buscar?q={q}",
            f"https://www.corecapital.pe/fondos/?q={q}",
        ]

    async def parse_ficha(self, url: str, llm: LLMClient) -> ExtractedFicha:
        ficha = await extract_from_url(url=url, llm=llm)
        return dataclasses.replace(ficha, source_confidence=0.93)
```

- [ ] Registrar, assert, commit:

```bash
git add src/scraper/search/level1_scrapers/corecapital_pe.py src/scraper/search/level1_scrapers/registry.py tests/unit/test_level1_base.py
git commit -m "feat: N1 Core Capital (corecapital.pe) parser"
```

### Task 10.5 — Sabbi (sabbi.pe)

```python
"""Parser for sabbi.pe — Sabbi's own public product pages."""
from __future__ import annotations

from urllib.parse import quote_plus

import dataclasses

from scraper.agents.types import ExtractedFicha
from scraper.extract.html import extract_from_url
from scraper.llm import LLMClient


class SabbiPeParser:
    domain = "sabbi.pe"

    async def search_by_name(self, nombre: str) -> list[str]:
        q = quote_plus(nombre)
        return [f"https://www.sabbi.pe/buscar?q={q}"]

    async def parse_ficha(self, url: str, llm: LLMClient) -> ExtractedFicha:
        ficha = await extract_from_url(url=url, llm=llm)
        return dataclasses.replace(ficha, source_confidence=0.97)
```

- [ ] Registrar, assert, commit:

```bash
git add src/scraper/search/level1_scrapers/sabbi_pe.py src/scraper/search/level1_scrapers/registry.py tests/unit/test_level1_base.py
git commit -m "feat: N1 Sabbi (sabbi.pe) parser"
```

### Task 10.6 — BVL (bvl.com.pe)

```python
"""Parser for bvl.com.pe — Bolsa de Valores de Lima."""
from __future__ import annotations

from urllib.parse import quote_plus

import dataclasses

from scraper.agents.types import ExtractedFicha
from scraper.extract.html import extract_from_url
from scraper.llm import LLMClient


class BVLComPeParser:
    domain = "bvl.com.pe"

    async def search_by_name(self, nombre: str) -> list[str]:
        q = quote_plus(nombre)
        return [f"https://www.bvl.com.pe/buscar?q={q}"]

    async def parse_ficha(self, url: str, llm: LLMClient) -> ExtractedFicha:
        ficha = await extract_from_url(url=url, llm=llm)
        return dataclasses.replace(ficha, source_confidence=0.93)
```

- [ ] Registrar final `registry.py` — la lista completa debería quedar:

```python
"""Registry of known-site parsers."""
from __future__ import annotations

from scraper.search.level1_scrapers.base import SiteParser
from scraper.search.level1_scrapers.bcpcapital_com import BCPCapitalParser
from scraper.search.level1_scrapers.bvl_com_pe import BVLComPeParser
from scraper.search.level1_scrapers.corecapital_pe import CoreCapitalParser
from scraper.search.level1_scrapers.credicorpcapital_com import CredicorpCapitalParser
from scraper.search.level1_scrapers.sabbi_pe import SabbiPeParser
from scraper.search.level1_scrapers.sbs_gob_pe import SBSGobPeParser
from scraper.search.level1_scrapers.smv_gob_pe import SMVGobPeParser

TARGETS: list[SiteParser] = [
    CredicorpCapitalParser(),
    SMVGobPeParser(),
    SBSGobPeParser(),
    BCPCapitalParser(),
    CoreCapitalParser(),
    SabbiPeParser(),
    BVLComPeParser(),
]
```

- [ ] Update test to assert 7 parsers:

```python
def test_registry_exposes_list():
    from scraper.search.level1_scrapers.registry import TARGETS
    assert len(TARGETS) == 7
    domains = [p.domain for p in TARGETS]
    assert {
        "credicorpcapital.com", "smv.gob.pe", "sbs.gob.pe",
        "bcpcapital.com", "corecapital.pe", "sabbi.pe", "bvl.com.pe",
    }.issubset(set(domains))
```

- [ ] Run tests + commit:

```bash
poetry run pytest tests/unit/test_level1_base.py -v
poetry run ruff check src/scraper/search/level1_scrapers/
git add src/scraper/search/level1_scrapers/bvl_com_pe.py src/scraper/search/level1_scrapers/registry.py tests/unit/test_level1_base.py
git commit -m "feat: N1 BVL (bvl.com.pe) parser — completes 7 known targets"
```

---

## Task 11: N1 circuit breaker + orchestrator `run_n1_parsers`

Circuit breaker por parser. Orquestador de N1 corre todos en paralelo con timeout + respeta breakers.

**Files:**
- Create: `src/scraper/search/circuit_breaker.py`
- Modify: `src/scraper/search/cascade.py` (implement `run_n1_parsers`)
- Create: `tests/unit/test_circuit_breaker.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_circuit_breaker.py`:

```python
import pytest


def test_circuit_breaker_initially_closed():
    from scraper.search.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker(fail_threshold=3, cooldown_seconds=60)
    assert cb.is_open("x.com") is False


def test_circuit_breaker_opens_after_threshold():
    from scraper.search.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker(fail_threshold=3, cooldown_seconds=60)
    cb.record_failure("x.com")
    cb.record_failure("x.com")
    assert cb.is_open("x.com") is False
    cb.record_failure("x.com")
    assert cb.is_open("x.com") is True


def test_circuit_breaker_success_resets():
    from scraper.search.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker(fail_threshold=3, cooldown_seconds=60)
    cb.record_failure("x.com")
    cb.record_failure("x.com")
    cb.record_success("x.com")
    cb.record_failure("x.com")
    cb.record_failure("x.com")
    assert cb.is_open("x.com") is False  # reset on success; only 2 recent fails


def test_circuit_breaker_cooldown_closes():
    import time
    from scraper.search.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker(fail_threshold=2, cooldown_seconds=0.05)
    cb.record_failure("x.com")
    cb.record_failure("x.com")
    assert cb.is_open("x.com") is True
    time.sleep(0.08)
    assert cb.is_open("x.com") is False  # cooldown expired
```

- [ ] **Step 2: Run — fails**

```bash
poetry run pytest tests/unit/test_circuit_breaker.py -v
```

- [ ] **Step 3: Implement `src/scraper/search/circuit_breaker.py`**

```python
"""Simple per-key circuit breaker for cascade parsers."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class _State:
    failures: list[float] = field(default_factory=list)  # timestamps
    opened_at: float | None = None


class CircuitBreaker:
    """Open the circuit after `fail_threshold` failures within the sliding window.

    While open, `is_open(key)` returns True until `cooldown_seconds` elapse since
    opening. Success resets the failure count immediately.
    """

    def __init__(
        self,
        fail_threshold: int = 5,
        window_seconds: float = 600.0,  # 10 min
        cooldown_seconds: float = 900.0,  # 15 min
    ) -> None:
        self.fail_threshold = fail_threshold
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        self._states: dict[str, _State] = {}
        self._lock = threading.Lock()

    def _state(self, key: str) -> _State:
        return self._states.setdefault(key, _State())

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            s = self._state(key)
            s.failures = [t for t in s.failures if now - t <= self.window_seconds]
            s.failures.append(now)
            if len(s.failures) >= self.fail_threshold and s.opened_at is None:
                s.opened_at = now

    def record_success(self, key: str) -> None:
        with self._lock:
            s = self._state(key)
            s.failures.clear()
            s.opened_at = None

    def is_open(self, key: str) -> bool:
        with self._lock:
            s = self._state(key)
            if s.opened_at is None:
                return False
            if time.monotonic() - s.opened_at > self.cooldown_seconds:
                s.opened_at = None
                s.failures.clear()
                return False
            return True


# Process-wide singleton (parsers share it)
BREAKER = CircuitBreaker()
```

- [ ] **Step 4: Implement `run_n1_parsers` in `cascade.py`**

Reemplazar el stub actual:

```python
async def run_n1_parsers(nombre: str, llm: LLMClient | None) -> list[ExtractedFicha]:
    ...
```

Con la implementación real:

```python
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
```

- [ ] **Step 5: Run tests**

```bash
poetry run pytest tests/unit/test_circuit_breaker.py tests/unit/test_cascade.py -v
```

Expected: all pass (the cascade tests still work because they monkeypatch `run_n1_parsers`).

- [ ] **Step 6: Commit**

```bash
poetry run ruff check src/scraper/search/circuit_breaker.py src/scraper/search/cascade.py tests/unit/test_circuit_breaker.py
git add src/scraper/search/circuit_breaker.py src/scraper/search/cascade.py tests/unit/test_circuit_breaker.py
git commit -m "feat: N1 circuit breaker + parallel run_n1_parsers orchestrator"
```

---

## Task 12: N2 — Claude web_search wrapper

Usa el tool `web_search_20250305` de Claude para buscar y extraer en un solo call.

**Files:**
- Create: `src/scraper/search/level2_websearch.py`
- Modify: `src/scraper/search/cascade.py` (wire `run_claude_websearch`)
- Create: `tests/integration/test_level2_websearch_mocked.py`

- [ ] **Step 1: Write failing test**

`tests/integration/test_level2_websearch_mocked.py`:

```python
import json


async def test_websearch_returns_parsed_ficha(mock_llm_client):
    from scraper.search.level2_websearch import run_claude_websearch

    output = json.dumps({
        "source_type": "websearch",
        "source_confidence": 0.78,
        "raw_text": "info from web",
        "tables": [],
        "attributes": {
            "nombre": {"value": "Credicorp Crecimiento", "confidence": 0.9, "reasoning": "", "raw_quote": ""}
        },
        "citations": ["https://credicorpcapital.com/fondo"],
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(output)

    fichas = await run_claude_websearch("Credicorp Crecimiento", mock_llm_client)
    assert len(fichas) == 1
    assert fichas[0].source_type == "websearch"
    assert fichas[0].source_confidence == 0.78


async def test_websearch_returns_empty_on_no_json(mock_llm_client):
    from scraper.search.level2_websearch import run_claude_websearch

    mock_llm_client.call.return_value = mock_llm_client.make_result("no JSON at all")
    fichas = await run_claude_websearch("X", mock_llm_client)
    assert fichas == []


async def test_websearch_passes_websearch_tool(mock_llm_client):
    import json as _j
    from scraper.search.level2_websearch import run_claude_websearch

    mock_llm_client.call.return_value = mock_llm_client.make_result(_j.dumps({
        "source_type": "websearch", "source_confidence": 0.8,
        "raw_text": "", "tables": [], "attributes": {},
        "citations": [],
    }))
    await run_claude_websearch("X", mock_llm_client)

    call = mock_llm_client.call.call_args
    tools = call.kwargs.get("tools")
    assert tools is not None
    assert any(t.get("type", "").startswith("web_search") for t in tools)
```

- [ ] **Step 2: Run — fails**

```bash
poetry run pytest tests/integration/test_level2_websearch_mocked.py -v
```

- [ ] **Step 3: Check `LLMClient.call` signature supports `tools` kwarg**

Revisar `src/scraper/llm/client.py`. Si la función no acepta `tools` actualmente, agregar el parámetro (optional):

En `call(self, *, model, system, messages, max_tokens, temperature=None, extra_headers=None, tools=None)`, y en `create_kwargs`:

```python
if tools is not None:
    create_kwargs["tools"] = tools
```

Si ya se agregó en una tarea previa, skip. Ruff + test para confirmar que el cliente acepta kwargs.

- [ ] **Step 4: Implement `src/scraper/search/level2_websearch.py`**

```python
"""N2 — Claude web_search native tool wrapper."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import structlog

from scraper.agents.classifier import _strip_fences
from scraper.agents.extractor import build_extractor_system_blocks
from scraper.agents.types import AttributeExtraction, ExtractedFicha
from scraper.llm import LLMClient

log = structlog.get_logger()

WEBSEARCH_MODEL = "claude-sonnet-4-6"
_WEBSEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}


async def run_claude_websearch(nombre: str, llm: LLMClient | None) -> list[ExtractedFicha]:
    """Ask Claude to search the web for a product and extract its fact sheet.

    Returns 0-3 ExtractedFicha candidates. On parse failure returns [].
    """
    if llm is None:
        return []

    start = time.monotonic()
    user_msg = (
        f"Buscá en la web la ficha técnica del producto de inversión "
        f"llamado: '{nombre}'. Usá el tool web_search para encontrar páginas "
        f"oficiales (administradora, regulador). Extraé la ficha en el formato "
        f"JSON del system prompt. Si encontrás varias fuentes confiables, "
        f"podés devolver hasta 3 objetos. Responde SOLO el JSON."
    )

    try:
        result = await llm.call(
            model=WEBSEARCH_MODEL,
            system=build_extractor_system_blocks(),
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=4096,
            tools=[_WEBSEARCH_TOOL],
        )
    except Exception as e:
        log.warning("websearch_call_failed", error=str(e))
        return []

    clean = _strip_fences(result.response_text)
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError:
        log.warning("websearch_parse_failed", output=clean[:200])
        return []

    # Payload may be a single object or a list of objects
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
        source_url = citations[0] if citations else None

        fichas.append(
            ExtractedFicha(
                source_url=source_url,
                source_type="websearch",
                source_confidence=float(item.get("source_confidence", 0.65)),
                fetched_at=datetime.now(tz=timezone.utc),
                raw_text=item.get("raw_text", "") or "",
                tables=list(item.get("tables") or []),
                attributes=attrs,
                citations=citations,
                extraction_cost_usd=(
                    result.cost.total_usd if hasattr(result.cost, "total_usd") else 0.0
                ),
                extraction_duration_ms=duration_ms,
            )
        )

    return fichas
```

- [ ] **Step 5: Wire in `cascade.py`**

Reemplazar stub de `run_claude_websearch` con:

```python
from scraper.search.level2_websearch import run_claude_websearch  # noqa: F401
```

- [ ] **Step 6: Tests pass**

```bash
poetry run pytest tests/integration/test_level2_websearch_mocked.py tests/unit/test_cascade.py -v
```

- [ ] **Step 7: Commit**

```bash
poetry run ruff check src/scraper/search/level2_websearch.py src/scraper/search/cascade.py tests/integration/test_level2_websearch_mocked.py
git add src/scraper/search/level2_websearch.py src/scraper/search/cascade.py src/scraper/llm/client.py tests/integration/test_level2_websearch_mocked.py
git commit -m "feat: N2 Claude web_search tool wrapper for search cascade"
```

---

## Task 13: N3 — Claude intensive with kill switch

Versión más agresiva que insiste con web_search hasta 10 iteraciones. Kill switch via env.

**Files:**
- Create: `src/scraper/search/level3_intensive.py`
- Modify: `src/scraper/config.py` (agregar `skip_intensive_search: bool = True`)
- Modify: `src/scraper/search/cascade.py` (wire `run_claude_intensive`)
- Create: `tests/integration/test_level3_intensive_mocked.py`

- [ ] **Step 1: Add setting to `src/scraper/config.py`**

Abrir `src/scraper/config.py`. Dentro de la clase `Settings(BaseSettings)`, agregar:

```python
skip_intensive_search: bool = True  # N3 kill switch, default off
```

- [ ] **Step 2: Write failing test**

`tests/integration/test_level3_intensive_mocked.py`:

```python
import json


async def test_intensive_returns_ficha(mock_llm_client):
    from scraper.search.level3_intensive import run_claude_intensive

    output = json.dumps({
        "source_type": "websearch",
        "source_confidence": 0.72,
        "raw_text": "dug deep",
        "tables": [],
        "attributes": {
            "nombre": {"value": "Obscuro Fondo", "confidence": 0.75, "reasoning": "found after 8 searches", "raw_quote": ""}
        },
        "citations": ["https://obscuro.example/ficha"],
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(output)

    fichas = await run_claude_intensive("Obscuro Fondo", mock_llm_client)
    assert len(fichas) == 1
    assert fichas[0].source_type == "websearch"
    assert fichas[0].attributes["nombre"].value == "Obscuro Fondo"
```

- [ ] **Step 3: Implement `src/scraper/search/level3_intensive.py`**

```python
"""N3 — Claude intensive: longer prompt, up to 10 web_search iterations."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import structlog

from scraper.agents.classifier import _strip_fences
from scraper.agents.extractor import build_extractor_system_blocks
from scraper.agents.types import AttributeExtraction, ExtractedFicha
from scraper.llm import LLMClient

log = structlog.get_logger()

INTENSIVE_MODEL = "claude-sonnet-4-6"
_WEBSEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}


async def run_claude_intensive(nombre: str, llm: LLMClient | None) -> list[ExtractedFicha]:
    """N3 — more aggressive: instruct Claude to keep searching until found or exhausted."""
    if llm is None:
        return []

    start = time.monotonic()
    user_msg = (
        f"No encontramos ficha técnica para: '{nombre}' en DB local, targets "
        f"conocidos ni búsqueda web estándar. Hacé una búsqueda intensiva: "
        f"- Probá variaciones del nombre (siglas, traducciones, ticker). "
        f"- Buscá en sitios de reguladores internacionales (SEC, FCA, BaFin). "
        f"- Buscá prospectos PDF (filetype:pdf). "
        f"- Buscá menciones en Bloomberg, Morningstar, Yahoo Finance. "
        f"Hasta 10 búsquedas. Si no encontrás nada robusto, devolvé un JSON "
        f"con attributes vacío y source_confidence bajo. Responde SOLO el JSON."
    )

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
        fichas.append(
            ExtractedFicha(
                source_url=citations[0] if citations else None,
                source_type=item.get("source_type", "websearch"),
                source_confidence=float(item.get("source_confidence", 0.55)),
                fetched_at=datetime.now(tz=timezone.utc),
                raw_text=item.get("raw_text", "") or "",
                tables=list(item.get("tables") or []),
                attributes=attrs,
                citations=citations,
                extraction_cost_usd=(
                    result.cost.total_usd if hasattr(result.cost, "total_usd") else 0.0
                ),
                extraction_duration_ms=duration_ms,
            )
        )
    return fichas
```

- [ ] **Step 4: Wire in `cascade.py`**

Reemplazar stub con:

```python
from scraper.search.level3_intensive import run_claude_intensive  # noqa: F401
```

- [ ] **Step 5: Tests pass**

```bash
poetry run pytest tests/integration/test_level3_intensive_mocked.py tests/unit/test_cascade.py -v
```

- [ ] **Step 6: Commit**

```bash
poetry run ruff check src/scraper/search/level3_intensive.py src/scraper/config.py tests/integration/test_level3_intensive_mocked.py
git add src/scraper/search/level3_intensive.py src/scraper/config.py src/scraper/search/cascade.py tests/integration/test_level3_intensive_mocked.py
git commit -m "feat: N3 Claude intensive search with SKIP_INTENSIVE_SEARCH kill switch"
```

---

## Task 14: `search_cache` integration with per-level TTL

Persistir resultados de cada nivel en `search_cache` table (ya existe de Phase 1).

**Files:**
- Create: `src/scraper/search/cache.py`
- Modify: `src/scraper/search/cascade.py` (use cache wrapper)
- Create: `tests/unit/test_cache.py`

- [ ] **Step 1: Check existing model**

Verificar que `SearchCache` en `src/scraper/db/models.py` tiene los campos: `query_hash`, `query_text`, `source`, `response` (JSON), `fetched_at`, `ttl_days`. Ya existe desde Phase 1.

- [ ] **Step 2: Write failing test**

`tests/unit/test_cache.py`:

```python
from datetime import datetime, timezone


async def test_cache_roundtrip(seeded_and_split_session):
    from scraper.agents.types import AttributeExtraction, ExtractedFicha
    from scraper.search.cache import get_cached, put_cached

    ficha = ExtractedFicha(
        source_url="https://x/y",
        source_type="websearch",
        source_confidence=0.8,
        fetched_at=datetime.now(tz=timezone.utc),
        raw_text="hi",
        tables=[],
        attributes={
            "nombre": AttributeExtraction(value="T", confidence=1.0, reasoning="", raw_quote="")
        },
        citations=["https://x/y"],
        extraction_cost_usd=0.01,
        extraction_duration_ms=100,
    )

    await put_cached(seeded_and_split_session, "Producto Test", "websearch", [ficha])
    got = await get_cached(seeded_and_split_session, "Producto Test", "websearch")
    assert got is not None
    assert len(got) == 1
    assert got[0].attributes["nombre"].value == "T"


async def test_cache_miss_returns_none(seeded_and_split_session):
    from scraper.search.cache import get_cached

    got = await get_cached(seeded_and_split_session, "Nada", "websearch")
    assert got is None


async def test_cache_respects_ttl(seeded_and_split_session):
    from datetime import timedelta
    from scraper.agents.types import AttributeExtraction, ExtractedFicha
    from scraper.db.models import SearchCache
    from scraper.search.cache import get_cached, put_cached
    from sqlalchemy import select

    old_ficha = ExtractedFicha(
        source_url="https://x",
        source_type="websearch",
        source_confidence=0.8,
        fetched_at=datetime.now(tz=timezone.utc),
        raw_text="",
        tables=[],
        attributes={"nombre": AttributeExtraction(value="Z", confidence=1.0, reasoning="", raw_quote="")},
        citations=[],
        extraction_cost_usd=0.0,
        extraction_duration_ms=0,
    )
    await put_cached(seeded_and_split_session, "Zeta", "websearch", [old_ficha])

    # Age the row beyond TTL
    r = await seeded_and_split_session.execute(
        select(SearchCache).where(SearchCache.query_text == "Zeta")
    )
    row = r.scalar_one()
    row.fetched_at = datetime.now(tz=timezone.utc) - timedelta(days=60)
    await seeded_and_split_session.commit()

    got = await get_cached(seeded_and_split_session, "Zeta", "websearch")
    assert got is None  # expired (TTL for websearch = 30d)
```

- [ ] **Step 3: Implement `src/scraper/search/cache.py`**

```python
"""search_cache wrapper — store/retrieve ExtractedFicha lists per (nombre, source)."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.agents.types import ExtractedFicha
from scraper.db.models import SearchCache

log = structlog.get_logger()

# TTL per cascade level / source_type
_TTL_DAYS: dict[str, int] = {
    "db": 0,              # N0 doesn't use search_cache (it IS the DB)
    "level1": 7,          # N1 — known targets
    "websearch": 30,      # N2 — Claude web_search
    "intensive": 0,       # N3 — don't cache until calibrated; 0 means "never fresh"
}


def _hash_key(nombre: str) -> str:
    normalized = unicodedata.normalize("NFKD", nombre).lower().strip()
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def get_cached(
    session: AsyncSession, nombre: str, source: str
) -> list[ExtractedFicha] | None:
    """Return cached fichas or None if miss/expired."""
    ttl_days = _TTL_DAYS.get(source, 0)
    if ttl_days <= 0:
        return None

    key = _hash_key(nombre)
    r = await session.execute(
        select(SearchCache).where(
            SearchCache.query_hash == key, SearchCache.source == source
        )
    )
    row = r.scalar_one_or_none()
    if row is None:
        return None

    age = datetime.now(tz=timezone.utc) - (
        row.fetched_at if row.fetched_at.tzinfo else row.fetched_at.replace(tzinfo=timezone.utc)
    )
    if age > timedelta(days=ttl_days):
        log.info("cache_expired", nombre=nombre, source=source, age_days=age.days)
        return None

    payload = row.response
    items = payload.get("items", []) if isinstance(payload, dict) else []
    return [ExtractedFicha.from_json(x) for x in items]


async def put_cached(
    session: AsyncSession, nombre: str, source: str, fichas: list[ExtractedFicha]
) -> None:
    """Store fichas in cache (upsert by key + source)."""
    ttl_days = _TTL_DAYS.get(source, 0)
    if ttl_days <= 0:
        return

    key = _hash_key(nombre)
    # Upsert: delete then insert (simpler than dialect-specific upsert for sqlite/pg)
    await session.execute(
        delete(SearchCache).where(
            SearchCache.query_hash == key, SearchCache.source == source
        )
    )
    row = SearchCache(
        query_hash=key,
        query_text=nombre,
        source=source,
        response={"items": [f.to_json() for f in fichas]},
        fetched_at=datetime.now(tz=timezone.utc),
        ttl_days=ttl_days,
    )
    session.add(row)
    await session.commit()
```

- [ ] **Step 4: Wire cache into cascade**

Modificar `src/scraper/search/cascade.py` para consultar el cache antes de N1/N2/N3 y guardar después. Agregar:

```python
from scraper.search.cache import get_cached, put_cached
```

En `run_cascade`, luego de N0 (que ya consulta DB), envolver N1/N2/N3:

```python
# N1 — check cache
cached_n1 = await get_cached(session, nombre, "level1") if session else None
if cached_n1 is not None:
    n1 = cached_n1
else:
    n1 = await run_n1_parsers(nombre, llm)
    if session and n1:
        await put_cached(session, nombre, "level1", n1)

if _best_confidence(n1) >= _N1_SHORT_CIRCUIT_CONF:
    return CascadeResult(level=1, fichas=n1)

# N2
cached_n2 = await get_cached(session, nombre, "websearch") if session else None
if cached_n2 is not None:
    n2 = cached_n2
else:
    n2 = await run_claude_websearch(nombre, llm)
    if session and n2:
        await put_cached(session, nombre, "websearch", n2)

combined = merge_candidates(n1, n2)
if _best_confidence(combined) >= _N2_ENOUGH_CONF:
    return CascadeResult(level=2, fichas=combined)

# N3 (no caching by design, TTL=0)
...
```

- [ ] **Step 5: Tests pass**

```bash
poetry run pytest tests/unit/test_cache.py tests/unit/test_cascade.py -v
```

- [ ] **Step 6: Commit**

```bash
poetry run ruff check src/scraper/search/cache.py src/scraper/search/cascade.py tests/unit/test_cache.py
git add src/scraper/search/cache.py src/scraper/search/cascade.py tests/unit/test_cache.py
git commit -m "feat: search_cache integration with per-level TTLs (level1=7d, websearch=30d)"
```

---

## Task 15: `extract_one` CLI (--url, --pdf)

CLI que toma URL o PDF y devuelve ExtractedFicha JSON.

**Files:**
- Create: `src/scraper/scripts/extract_one.py`
- Create: `tests/integration/test_extract_one_smoke.py`

- [ ] **Step 1: Write failing test**

`tests/integration/test_extract_one_smoke.py`:

```python
import subprocess
import sys
from pathlib import Path


def test_extract_one_requires_url_or_pdf():
    """Calling without --url or --pdf should error."""
    result = subprocess.run(
        [sys.executable, "-m", "scraper.scripts.extract_one"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode != 0


def test_extract_one_mutually_exclusive():
    """--url and --pdf together should error."""
    result = subprocess.run(
        [
            sys.executable, "-m", "scraper.scripts.extract_one",
            "--url", "https://x.com", "--pdf", "x.pdf",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode != 0
```

- [ ] **Step 2: Run — fails**

```bash
poetry run pytest tests/integration/test_extract_one_smoke.py -v
```

- [ ] **Step 3: Implement `src/scraper/scripts/extract_one.py`**

```python
"""CLI: extract ficha from a URL or PDF path.

Usage:
    poetry run python -m scraper.scripts.extract_one --url https://example.com/fondo
    poetry run python -m scraper.scripts.extract_one --pdf path/to/ficha.pdf
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import structlog

from scraper.config import get_settings
from scraper.extract.html import extract_from_url
from scraper.extract.pdf import extract_from_pdf
from scraper.llm import LLMClient
from scraper.logging_config import configure_logging

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

log = structlog.get_logger()


async def _main(url: str | None, pdf: str | None) -> int:
    configure_logging(level="INFO", json_logs=False)

    if (url is None) == (pdf is None):
        print("ERROR: provide exactly one of --url or --pdf", file=sys.stderr)
        return 2

    settings = get_settings()
    if not settings.anthropic_api_key:
        print("ERROR: ANTHROPIC_API_KEY no configurada en .env", file=sys.stderr)
        return 2

    llm = LLMClient()
    if url is not None:
        ficha = await extract_from_url(url=url, llm=llm)
    else:
        ficha = await extract_from_pdf(path=Path(pdf), llm=llm)

    print(json.dumps(ficha.to_json(), ensure_ascii=False, indent=2))
    print(f"\nCost: ${llm.cost.total_usd:.4f}", file=sys.stderr)
    return 0


def cli() -> None:
    parser = argparse.ArgumentParser(description="Extract ficha from URL or PDF.")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--url", help="URL of HTML page to extract")
    g.add_argument("--pdf", help="Path to PDF file to extract")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.url, args.pdf)))


if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: Tests pass**

```bash
poetry run pytest tests/integration/test_extract_one_smoke.py -v
```

- [ ] **Step 5: Commit**

```bash
poetry run ruff check src/scraper/scripts/extract_one.py tests/integration/test_extract_one_smoke.py
git add src/scraper/scripts/extract_one.py tests/integration/test_extract_one_smoke.py
git commit -m "feat: extract_one CLI (--url | --pdf) with mutually exclusive args"
```

---

## Task 16: `find_and_classify` CLI — end-to-end pipeline

Toma nombre de producto, corre la cascada, pasa al classifier, reviewer, decide_flag, guarda en `classifications`.

**Files:**
- Create: `src/scraper/scripts/find_and_classify.py`
- Create: `tests/integration/test_find_and_classify_smoke.py`

- [ ] **Step 1: Inspect existing classifier signature to plan multi-source input**

Abrir `src/scraper/agents/classifier.py`. La función `classify()` recibe un product_context dict con admin/gestor/moneda/liquidez + few_shot_examples.

Para multi-source, vamos a concatenar la evidencia de todas las fichas en el `extra` field del product_context:

```python
evidence_text = render_evidence_blocks(cascade_result.fichas)
context = {
    "administrador": top.attributes["administrador"].value if "administrador" in top.attributes else None,
    "gestor": top.attributes["gestor"].value if "gestor" in top.attributes else None,
    "moneda": top.attributes["moneda"].value if "moneda" in top.attributes else None,
    "liquidez": top.attributes["liquidez"].value if "liquidez" in top.attributes else None,
    "extra": evidence_text,
}
```

- [ ] **Step 2: Write failing smoke test**

`tests/integration/test_find_and_classify_smoke.py`:

```python
import subprocess
import sys


def test_find_and_classify_requires_nombre():
    result = subprocess.run(
        [sys.executable, "-m", "scraper.scripts.find_and_classify"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode != 0


def test_find_and_classify_dry_run(monkeypatch):
    """--dry-run should not call any API — short-circuit and print a message."""
    import subprocess, sys
    result = subprocess.run(
        [
            sys.executable, "-m", "scraper.scripts.find_and_classify",
            "Credicorp Crecimiento", "--dry-run",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "dry-run" in result.stdout.lower()
```

- [ ] **Step 3: Run — fails**

```bash
poetry run pytest tests/integration/test_find_and_classify_smoke.py -v
```

- [ ] **Step 4: Implement `src/scraper/scripts/find_and_classify.py`**

```python
"""CLI: search cascade + extract + classify + review + save.

Usage:
    poetry run python -m scraper.scripts.find_and_classify "Credicorp Crecimiento"
    poetry run python -m scraper.scripts.find_and_classify "X" --rules rules/v3.md
    poetry run python -m scraper.scripts.find_and_classify "X" --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.agents.classifier import classify
from scraper.agents.orchestrator import decide_flag
from scraper.agents.prompts.builder import build_few_shot_from_db
from scraper.agents.reviewer import review
from scraper.agents.types import ExtractedFicha
from scraper.config import get_settings
from scraper.db.models import Classification
from scraper.db.session import get_session
from scraper.llm import LLMClient
from scraper.logging_config import configure_logging
from scraper.search.cascade import run_cascade

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

log = structlog.get_logger()


def _top_ficha(fichas: list[ExtractedFicha]) -> ExtractedFicha | None:
    return max(fichas, key=lambda f: f.source_confidence, default=None) if fichas else None


def _render_evidence(fichas: list[ExtractedFicha]) -> str:
    lines: list[str] = []
    for i, f in enumerate(fichas, 1):
        lines.append(f"=== Fuente {i} ({f.source_type}, conf={f.source_confidence:.2f}) ===")
        if f.source_url:
            lines.append(f"URL: {f.source_url}")
        for attr, ae in f.attributes.items():
            lines.append(f"  {attr}: {ae.value!r}  ({ae.confidence:.2f})  quote: {ae.raw_quote!r}")
        if f.raw_text:
            lines.append(f"  raw_text: {f.raw_text[:500]}")
    return "\n".join(lines)


def _context_from_top(top: ExtractedFicha | None, fichas: list[ExtractedFicha]) -> dict:
    def _v(name: str):
        if top is None or name not in top.attributes:
            return None
        return top.attributes[name].value

    return {
        "administrador": _v("administrador"),
        "gestor": _v("gestor"),
        "moneda": _v("moneda"),
        "liquidez": _v("liquidez"),
        "extra": _render_evidence(fichas),
    }


async def _save_classification(
    session: AsyncSession,
    nombre: str,
    cls_result,
    rev_result,
    flag: str,
    cost_usd: float,
    duration_ms: int,
    source_used: str,
) -> int:
    row = Classification(
        product_name_input=nombre,
        classifier_output=cls_result.to_json() if hasattr(cls_result, "to_json") else {},
        reviewer_output={
            "veredicto": rev_result.veredicto,
            "global_verdict": rev_result.global_verdict,
            "reviewer_confidence": rev_result.reviewer_confidence,
        },
        global_confidence=cls_result.global_confidence,
        per_attribute_confidence={
            k: v.confidence for k, v in cls_result.attributes.items()
        },
        final_status=flag,
        source_used=source_used,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row.id


async def _main(nombre: str, rules_path: Path, dry_run: bool) -> int:
    import time
    configure_logging(level="INFO", json_logs=False)

    settings = get_settings()
    if not dry_run and not settings.anthropic_api_key:
        print("ERROR: ANTHROPIC_API_KEY no configurada. Use --dry-run para smoke test.", file=sys.stderr)
        return 2

    if dry_run:
        print(f"dry-run: would search + classify '{nombre}' with rules={rules_path}")
        return 0

    rules_md = rules_path.read_text(encoding="utf-8")
    llm = LLMClient()
    start = time.monotonic()

    async with get_session() as s:
        few_shot = await build_few_shot_from_db(s, limit=20)
        cascade_result = await run_cascade(nombre=nombre, session=s, llm=llm)

        if not cascade_result.fichas:
            print(f"No se encontró ficha para '{nombre}' en ningún nivel.", file=sys.stderr)
            return 1

        top = _top_ficha(cascade_result.fichas)
        context = _context_from_top(top, cascade_result.fichas)

        cls_result = await classify(
            llm=llm,
            producto_nombre=nombre,
            product_context=context,
            rules_md=rules_md,
            few_shot_examples=few_shot,
        )
        rev_result = await review(
            llm=llm,
            producto_nombre=nombre,
            product_context=context,
            classifier_output=cls_result,
            rules_md=rules_md,
        )
        flag = decide_flag(cls_result, rev_result)

        duration_ms = int((time.monotonic() - start) * 1000)
        cost_usd = llm.cost.total_usd
        source_used = f"cascade_level_{cascade_result.level}"

        classification_id = await _save_classification(
            s, nombre, cls_result, rev_result, flag, cost_usd, duration_ms, source_used
        )

    print(f"\n=== {nombre} ===")
    print(f"Cascade level: {cascade_result.level}  (fichas: {len(cascade_result.fichas)})")
    print(f"Flag: {flag}  Reviewer: {rev_result.global_verdict}  Conf: {cls_result.global_confidence:.2f}")
    print(f"Cost: ${cost_usd:.4f}  Duration: {duration_ms}ms")
    print(f"Classification id: {classification_id}")
    print("\nClasificación:")
    print(cls_result.to_json() if hasattr(cls_result, "to_json") else str(cls_result))

    return 0


def cli() -> None:
    parser = argparse.ArgumentParser(description="Search + extract + classify a product by name.")
    parser.add_argument("nombre", help="Product name (e.g. 'Credicorp Crecimiento')")
    parser.add_argument("--rules", default="rules/v3.md", help="Path to rules markdown (default v3)")
    parser.add_argument("--dry-run", action="store_true", help="Skip all API calls, print plan only")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.nombre, Path(args.rules), dry_run=args.dry_run)))


if __name__ == "__main__":
    cli()
```

- [ ] **Step 5: Tests pass**

```bash
poetry run pytest tests/integration/test_find_and_classify_smoke.py -v
```

- [ ] **Step 6: Commit**

```bash
poetry run ruff check src/scraper/scripts/find_and_classify.py tests/integration/test_find_and_classify_smoke.py
git add src/scraper/scripts/find_and_classify.py tests/integration/test_find_and_classify_smoke.py
git commit -m "feat: find_and_classify CLI — cascade + classify + review + DB persist"
```

---

## Task 17: Integration test end-to-end (mocked everything)

Valida el pipeline completo con todas las dependencias externas mockeadas.

**Files:**
- Create: `tests/integration/test_pipeline_e2e.py`

- [ ] **Step 1: Write the test**

```python
"""End-to-end pipeline test: cascade → extract → classify → review → save."""
import json
from datetime import datetime, timezone


async def test_pipeline_n0_db_hit_short_circuits(seeded_and_split_session, mock_llm_client, monkeypatch):
    """A name that exists in DB should be classified without any LLM search calls."""
    from scraper.search.cascade import run_cascade

    # Pick a product that exists in the seeded DB
    from scraper.db.models import Product
    from sqlalchemy import select
    r = await seeded_and_split_session.execute(select(Product).limit(1))
    existing = r.scalar_one()

    result = await run_cascade(
        nombre=existing.nombre, session=seeded_and_split_session, llm=mock_llm_client
    )
    assert result.level == 0
    assert len(result.fichas) == 1
    assert result.fichas[0].source_type == "db"


async def test_pipeline_n1_to_n2_when_n1_low_confidence(mock_llm_client, monkeypatch):
    """If N1 returns low confidence, cascade escalates to N2."""
    from scraper.agents.types import AttributeExtraction, ExtractedFicha
    from scraper.search import cascade as cascade_mod

    async def no_db(nombre, session):
        return None

    async def low_n1(nombre, llm):
        return [
            ExtractedFicha(
                source_url="https://low.example",
                source_type="html",
                source_confidence=0.60,  # below 0.85
                fetched_at=datetime.now(tz=timezone.utc),
                raw_text="", tables=[],
                attributes={
                    "nombre": AttributeExtraction(value="x", confidence=0.6, reasoning="", raw_quote="")
                },
                citations=[], extraction_cost_usd=0.0, extraction_duration_ms=0,
            )
        ]

    async def good_n2(nombre, llm):
        return [
            ExtractedFicha(
                source_url="https://good.example",
                source_type="websearch",
                source_confidence=0.80,
                fetched_at=datetime.now(tz=timezone.utc),
                raw_text="", tables=[],
                attributes={
                    "nombre": AttributeExtraction(value="x", confidence=0.8, reasoning="", raw_quote="")
                },
                citations=["https://good.example"],
                extraction_cost_usd=0.1, extraction_duration_ms=500,
            )
        ]

    async def no_n3(nombre, llm):
        raise AssertionError("should not reach N3 — N2 was high enough")

    monkeypatch.setattr(cascade_mod, "lookup_db", no_db)
    monkeypatch.setattr(cascade_mod, "run_n1_parsers", low_n1)
    monkeypatch.setattr(cascade_mod, "run_claude_websearch", good_n2)
    monkeypatch.setattr(cascade_mod, "run_claude_intensive", no_n3)

    result = await cascade_mod.run_cascade(nombre="new product", session=None, llm=mock_llm_client)
    assert result.level == 2
    # Combined N1 + N2 — should have both
    assert len(result.fichas) == 2


async def test_pipeline_n3_kill_switch_short_circuits(mock_llm_client, monkeypatch):
    """When all levels fall through and kill switch is on, return low_quality."""
    from scraper.search import cascade as cascade_mod

    async def empty(*args, **kwargs):
        return None if "session" in kwargs else []

    monkeypatch.setattr(cascade_mod, "lookup_db", lambda n, s: empty(session=s))
    monkeypatch.setattr(cascade_mod, "run_n1_parsers", lambda n, l: empty())
    monkeypatch.setattr(cascade_mod, "run_claude_websearch", lambda n, l: empty())

    async def no_n3(*args, **kwargs):
        raise AssertionError("kill switch should prevent N3")
    monkeypatch.setattr(cascade_mod, "run_claude_intensive", no_n3)

    # Ensure kill switch is on (default=True)
    from scraper.config import get_settings
    assert get_settings().skip_intensive_search is True

    result = await cascade_mod.run_cascade(nombre="very obscure", session=None, llm=mock_llm_client)
    assert result.low_quality is True
    assert result.level == 2
```

- [ ] **Step 2: Run tests**

```bash
poetry run pytest tests/integration/test_pipeline_e2e.py -v
```

Expected: 3 passed.

- [ ] **Step 3: Full suite**

```bash
poetry run pytest -q 2>&1 | tail -3
```

- [ ] **Step 4: Commit**

```bash
poetry run ruff check tests/integration/test_pipeline_e2e.py
git add tests/integration/test_pipeline_e2e.py
git commit -m "test: pipeline e2e coverage (N0 short-circuit, N1→N2 escalation, N3 kill switch)"
```

---

## Task 18: Calibración end-to-end vs validation_set

Medir accuracy del pipeline completo (nombre → cascade → classify) contra validation_set. Detecta regresiones por fuente externa.

**Files:**
- Create: `src/scraper/scripts/calibrate_pipeline.py`
- Create: `tests/integration/test_calibrate_pipeline_smoke.py`

- [ ] **Step 1: Write smoke test**

`tests/integration/test_calibrate_pipeline_smoke.py`:

```python
import subprocess
import sys


def test_calibrate_pipeline_dry_run():
    result = subprocess.run(
        [sys.executable, "-m", "scraper.scripts.calibrate_pipeline", "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Calibración pipeline" in result.stdout
```

- [ ] **Step 2: Run — fails**

```bash
poetry run pytest tests/integration/test_calibrate_pipeline_smoke.py -v
```

- [ ] **Step 3: Implement `src/scraper/scripts/calibrate_pipeline.py`**

```python
"""End-to-end calibration: nombre → cascade → classify → accuracy.

Only difference vs `calibrate.py` (Phase 2a): this one uses find_and_classify's
search+extract path to produce input to the classifier, instead of feeding
the classifier directly from DB ground truth context.

Usage:
    poetry run python -m scraper.scripts.calibrate_pipeline              # real API
    poetry run python -m scraper.scripts.calibrate_pipeline --dry-run    # no API
    poetry run python -m scraper.scripts.calibrate_pipeline --rules rules/v3.md
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import structlog
from sqlalchemy import select

from scraper.agents.classifier import ClassifierParseError, classify
from scraper.agents.prompts.builder import build_few_shot_from_db
from scraper.config import get_settings
from scraper.db.models import Product, RulesVersion, ValidationSet
from scraper.db.session import get_session
from scraper.llm import LLMClient
from scraper.logging_config import configure_logging
from scraper.metrics import aggregate_accuracy, compute_product_accuracy
from scraper.scripts.calibrate import _product_to_ground_truth
from scraper.scripts.find_and_classify import _context_from_top, _top_ficha
from scraper.search.cascade import run_cascade

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

log = structlog.get_logger()


async def _main(rules_path: Path, dry_run: bool) -> int:
    configure_logging(level="INFO", json_logs=False)

    if dry_run:
        print("Calibración pipeline (dry-run): no API calls.")
        return 0

    settings = get_settings()
    if not settings.anthropic_api_key:
        print("ERROR: ANTHROPIC_API_KEY no configurada.", file=sys.stderr)
        return 2

    rules_md = rules_path.read_text(encoding="utf-8")
    version = f"pipeline_{rules_path.stem}"

    async with get_session() as s:
        r = await s.execute(
            select(Product).join(ValidationSet, Product.id == ValidationSet.product_id)
        )
        validation = list(r.scalars().all())
        few_shot = await build_few_shot_from_db(s, limit=20)

    print(f"\n=== Calibración pipeline {version} — {len(validation)} productos ===\n")

    llm = LLMClient()
    reports: list[dict[str, bool]] = []
    per_product_details: list[dict] = []

    for i, p in enumerate(validation, 1):
        ground_truth = _product_to_ground_truth(p)
        try:
            async with get_session() as s2:
                cascade = await run_cascade(nombre=p.nombre, session=s2, llm=llm)
            top = _top_ficha(cascade.fichas)
            context = _context_from_top(top, cascade.fichas)

            cls_result = await classify(
                llm=llm,
                producto_nombre=p.nombre,
                product_context=context,
                rules_md=rules_md,
                few_shot_examples=few_shot,
            )
            report = compute_product_accuracy(ground_truth, cls_result)
            reports.append(report)

            correct = sum(1 for v in report.values() if v)
            total = len(report)
            print(
                f"[{i:2d}/{len(validation)}] {p.nombre[:50]:50s} "
                f"{correct}/{total} atr · level={cascade.level} · "
                f"conf={cls_result.global_confidence:.2f}"
            )

            for attr, ok in report.items():
                if ok:
                    continue
                gt = ground_truth.get({"subyacente": "subyacentes"}.get(attr, attr))
                pred = cls_result.attributes[attr].value if attr in cls_result.attributes else None
                print(f"        ✗ {attr:18s} gt={gt!r}  pred={pred!r}")

            per_product_details.append({
                "nombre": p.nombre,
                "cascade_level": cascade.level,
                "accuracy": report,
                "global_confidence": cls_result.global_confidence,
            })
        except ClassifierParseError as e:
            log.warning("pipeline_classifier_parse_error", producto=p.nombre, error=str(e))
            reports.append({attr: False for attr in [
                "foco_geografico", "clase_activo", "subyacente", "comision",
                "moneda", "administrador", "gestor", "liquidez", "minimo_inversion",
            ]})

    accuracy = aggregate_accuracy(reports)
    print(f"\n=== Resultado ({version}) ===")
    print(f"Productos evaluados: {len(reports)}")
    for attr, acc in sorted(accuracy.items()):
        bar = "█" * int(acc * 20) + "░" * (20 - int(acc * 20))
        flag = "✓" if acc >= 0.85 else "✗"
        print(f"  {flag} {attr:20s} [{bar}] {acc:.1%}")
    print(f"\nCosto total: ${llm.cost.total_usd:.3f}")

    async with get_session() as s3:
        r = await s3.execute(select(RulesVersion).where(RulesVersion.version == version))
        rv = r.scalar_one_or_none()
        if rv is None:
            rv = RulesVersion(
                version=version,
                content_md=rules_md,
                notes=f"Calibración pipeline {rules_path.stem}",
            )
            s3.add(rv)
        rv.validation_accuracy = {
            "per_attribute": accuracy,
            "n_products": len(reports),
            "details": per_product_details[:5],
        }
        await s3.commit()

    print(f"\nGuardado en rules_versions.{version}.validation_accuracy")
    min_acc = min(accuracy.values()) if accuracy else 0.0
    return 0 if min_acc >= 0.85 else 1


def cli() -> None:
    parser = argparse.ArgumentParser(description="End-to-end pipeline calibration.")
    parser.add_argument("--rules", default="rules/v3.md")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(Path(args.rules), dry_run=args.dry_run)))


if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: Tests pass**

```bash
poetry run pytest tests/integration/test_calibrate_pipeline_smoke.py -v
```

- [ ] **Step 5: Commit**

```bash
poetry run ruff check src/scraper/scripts/calibrate_pipeline.py tests/integration/test_calibrate_pipeline_smoke.py
git add src/scraper/scripts/calibrate_pipeline.py tests/integration/test_calibrate_pipeline_smoke.py
git commit -m "feat: calibrate_pipeline — end-to-end accuracy measurement (name → cascade → classify)"
```

- [ ] **Step 6 (manual, post-code): run real calibration**

```bash
poetry run python -m scraper.scripts.calibrate_pipeline --rules rules/v3.md
```

Expected: min accuracy ≥85% across 9 attributes. Costo estimado: ~$5-10 (cascada hace más calls que Phase 2a). Resultados se guardan en `rules_versions.pipeline_v3.validation_accuracy`.

---

## Task 19: Phase 2b closure — README + STATUS + tag

Docs + tag.

**Files:**
- Modify: `README.md`
- Create: `docs/superpowers/plans/phase2b-STATUS.md`

- [ ] **Step 1: Update `README.md`**

Editar checklist:

```markdown
- [x] Phase 1: Foundation (DB + seed desde Excel + split 80/20)
- [x] Phase 2a: Agentes + Calibración (Clasificador + Revisor + rules v3)
- [x] Phase 2b: Extract + Search Cascade (HTML + PDF + web_search)
- [ ] Phase 3: Orchestrator + FastAPI
- [ ] Phase 4: (unused — merged into 2b)
- [ ] Phase 5: Streamlit UI
- [ ] Phase 6: Robustez + deploy
```

En la sección "Calibración / clasificación", agregar comandos:

```bash
# Búsqueda + clasificación desde solo el nombre
poetry run python -m scraper.scripts.find_and_classify "Credicorp Crecimiento"

# Extracción directa desde URL o PDF
poetry run python -m scraper.scripts.extract_one --url https://example.com/fondo
poetry run python -m scraper.scripts.extract_one --pdf path/to/ficha.pdf

# Calibración end-to-end (nombre → pipeline completo)
poetry run python -m scraper.scripts.calibrate_pipeline --rules rules/v3.md
```

En "Setup local", agregar:

```bash
# Extras para Phase 2b
poetry run playwright install chromium   # ~300MB download
# poppler para pdf2image:
#   Windows: descargar poppler-windows desde github.com/oschwartz10612/poppler-windows
#   macOS: brew install poppler
#   Linux: apt-get install poppler-utils
```

- [ ] **Step 2: Create `docs/superpowers/plans/phase2b-STATUS.md`**

Template (completar números reales después de la calibración):

```markdown
# Phase 2b — Status

**Completed (code pipeline):** 2026-04-XX
**Tag:** `phase2b-complete`

## Qué se entregó

Phase 2b extends the Phase 2a pipeline with search + extract so the user
can input just a product name:

- 4-level search cascade (DB → 7 known targets → Claude web_search → Claude intensive w/ kill switch)
- HTML extractor (BeautifulSoup + Claude) with Playwright fallback for JS-rendered pages
- PDF text extractor (pypdf + pdfplumber) with Claude vision fallback
- Extractor agent with dedicated prompt (canonical taxonomies, no classification rules)
- 2 new CLIs: `extract_one --url|--pdf` and `find_and_classify "nombre"`
- search_cache integration with per-level TTLs (level1=7d, websearch=30d)
- Per-parser circuit breaker (5 failures in 10min → 15min cooldown)

### Commits
(fill after Task 19 commits)

### Tests
- Full suite at tag: ~100 passing (75 Phase 2a + ~25 new)

## Accuracy end-to-end (pipeline_v3 vs validation_set)

(fill after `calibrate_pipeline --rules rules/v3.md` completes)

| Atributo | Phase 2a v3 (direct) | Phase 2b pipeline_v3 |
|---|---|---|
| administrador | 100.0% | TBD |
| clase_activo | 100.0% | TBD |
| comision | 94.7% | TBD |
| foco_geografico | 94.7% | TBD |
| gestor | 100.0% | TBD |
| liquidez | 100.0% | TBD |
| minimo_inversion | 100.0% | TBD |
| moneda | 100.0% | TBD |
| subyacente | 100.0% | TBD |

Any regression vs Phase 2a direct calibration indicates the cascade+extractor
is losing or distorting information. Investigate before moving to Phase 3.

## Pending / known limitations

- N1 parsers use heuristic URL patterns; cada sitio puede requerir selectores
  específicos cuando HTML cambie. Monitorear tests con fixtures reales.
- Playwright Chromium download pesa ~300MB; solo se invoca lazily cuando httpx
  devuelve HTML que parece JS-rendered.
- PDF vision limitado a 10 páginas por cap de costos (`_MAX_PAGES` en vision.py).
- N3 (Claude intensive) está detrás de `SKIP_INTENSIVE_SEARCH=true` por default.

## Queda para Phase 3

- FastAPI wrapping (endpoints para classify, search, upload PDF)
- Full HITL workflow: ReviewQueue persistence + audit_log
- Rate limiting / budget controls por usuario
```

- [ ] **Step 3: Full suite green**

```bash
poetry run pytest -q 2>&1 | tail -3
```

- [ ] **Step 4: Commit + tag**

```bash
git add README.md docs/superpowers/plans/phase2b-STATUS.md
git commit -m "docs: close Phase 2b — extract + search cascade complete"
git tag phase2b-complete
git log --oneline | head -25
```

---

## Criterios de éxito Phase 2b

- [ ] `rules/v3.md` (o posterior) produce ≥85% accuracy en pipeline_v3 calibration
- [ ] `poetry run python -m scraper.scripts.find_and_classify "X"` funciona end-to-end con nombres reales
- [ ] `poetry run python -m scraper.scripts.extract_one --url URL` y `--pdf PATH` funcionan
- [ ] 7 parsers N1 registrados en `TARGETS`
- [ ] Cascade con umbrales 0.85 (N1→N2 skip) y 0.70 (N2→N3 skip) funcionando
- [ ] search_cache persiste con TTL por nivel
- [ ] Circuit breaker por parser activo
- [ ] Kill switch `SKIP_INTENSIVE_SEARCH` en .env
- [ ] ~100 tests pasando (75 Phase 2a + ~25 nuevos)
- [ ] Tag `phase2b-complete`

---

## Execution handoff

Opciones de ejecución:

**1. Subagent-Driven (recomendado)** — fresh subagent por task, two-stage review (spec + code quality) entre tasks. Alta velocidad de iteración.

**2. Inline Execution** — mismo session con checkpoints. Útil si querés ver cada paso.

**Nota especial:** Task 18 (calibración real) no la puede ejecutar un subagent autónomo — cuesta $5-10 y requiere juicio humano sobre los resultados. Recomiendo: tasks 1-17 via subagent, Task 18 juntos, Task 19 via subagent con los números reales ya conocidos.
