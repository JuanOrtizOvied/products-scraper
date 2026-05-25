# Scrapling Integration + Rules v7 + Calibration Benchmark — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace httpx + Playwright with Scrapling for anti-bot bypass and better extraction, add Scrapling MCP for Claude Level 3, create rules v7, and run A/B calibration benchmark comparing v6 (legacy) vs v7 (Scrapling).

**Architecture:** Feature flag `FETCHER_BACKEND=legacy|scrapling` in config.py routes fetch.py to either the old httpx/Playwright path or the new Scrapling StealthyFetcher. Level 3 intensive gains Scrapling MCP as an additional Claude tool. A new `compare_calibrations.py` script produces a side-by-side accuracy table.

**Tech Stack:** Python 3.11+, Scrapling (StealthyFetcher, Fetcher, AsyncStealthySession, MCP server), existing SQLAlchemy/Alembic/Streamlit/Claude stack.

---

## File Map

| Layer | File | Action | Responsibility |
|-------|------|--------|----------------|
| Dependencies | `pyproject.toml` | Modify | Add `scrapling[all]` |
| Config | `src/scraper/config.py` | Modify | Add `fetcher_backend` field |
| Fetcher | `src/scraper/extract/fetch.py` | Rewrite | Dual-backend with feature flag |
| HTML extract | `src/scraper/extract/html.py` | Modify | Use Scrapling session for link following |
| Level 3 | `src/scraper/search/level3_intensive.py` | Modify | Add Scrapling MCP tools to Claude |
| Rules | `rules/v7.md` | Create | v7 rules (R-FETCH + R-CAL + all v6 rules) |
| Calibration | `src/scraper/scripts/calibrate_pipeline.py` | Modify | Add `--output` flag for JSON export |
| Comparison | `src/scraper/scripts/compare_calibrations.py` | Create | Side-by-side v6 vs v7 report |
| Tests | `tests/unit/test_fetch_scrapling.py` | Create | Tests for Scrapling fetcher backend |
| Tests | `tests/unit/test_compare_calibrations.py` | Create | Tests for comparison script |

---

### Task 1: Install Scrapling + Add Config Flag

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/scraper/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Add Scrapling dependency**

Run:
```bash
poetry add "scrapling[all]"
```

Then run the browser install:
```bash
poetry run scrapling install
```

- [ ] **Step 2: Add fetcher_backend to Settings**

In `src/scraper/config.py`, add after the `skip_intensive_search` field:

```python
    # Fetcher backend
    fetcher_backend: str = Field(default="scrapling", description="legacy | scrapling")
```

- [ ] **Step 3: Add to .env.example**

Add after the `SKIP_INTENSIVE_SEARCH` line:

```
# Fetcher backend (legacy = httpx+playwright, scrapling = Scrapling StealthyFetcher)
FETCHER_BACKEND=scrapling
```

- [ ] **Step 4: Add to .env**

Add to `.env`:

```
FETCHER_BACKEND=scrapling
```

- [ ] **Step 5: Verify import works**

Run: `poetry run python -c "from scrapling.fetchers import Fetcher, StealthyFetcher; print('Scrapling OK')"`
Expected: `Scrapling OK`

- [ ] **Step 6: Verify config reads the flag**

Run: `poetry run python -c "from scraper.config import get_settings; print(get_settings().fetcher_backend)"`
Expected: `scrapling`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml poetry.lock src/scraper/config.py .env.example
git commit -m "feat: add scrapling[all] dependency and fetcher_backend config flag"
```

---

### Task 2: Rewrite fetch.py with Dual Backend

**Files:**
- Rewrite: `src/scraper/extract/fetch.py`
- Create: `tests/unit/test_fetch_scrapling.py`

- [ ] **Step 1: Write tests for Scrapling backend**

```python
# tests/unit/test_fetch_scrapling.py
"""Tests for Scrapling fetcher backend routing."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scraper.extract.fetch import FetchError, is_js_rendered


def test_is_js_rendered_short_body():
    html = "<html><body></body></html>"
    assert is_js_rendered(html) is True


def test_is_js_rendered_normal_content():
    html = "<html><body>" + ("<p>real content here</p>" * 100) + "</body></html>"
    assert is_js_rendered(html) is False


def test_fetch_error_is_runtime_error():
    err = FetchError("test")
    assert isinstance(err, RuntimeError)


@pytest.mark.asyncio
async def test_fetch_url_scrapling_backend():
    """When backend=scrapling, fetch_url uses StealthyFetcher."""
    mock_page = MagicMock()
    mock_page.html = "<html><body>scrapling content</body></html>"

    with patch("scraper.extract.fetch._get_backend", return_value="scrapling"), \
         patch("scraper.extract.fetch._fetch_with_scrapling", new_callable=AsyncMock, return_value=mock_page.html) as mock_fetch:
        from scraper.extract.fetch import fetch_url
        html = await fetch_url("https://example.com")
        assert "scrapling content" in html
        mock_fetch.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_url_legacy_backend(httpx_mock):
    """When backend=legacy, fetch_url uses httpx."""
    httpx_mock.add_response(
        url="https://example.com/ficha",
        text="<html><body>legacy content</body></html>",
        status_code=200,
    )
    with patch("scraper.extract.fetch._get_backend", return_value="legacy"):
        from scraper.extract.fetch import fetch_url
        html = await fetch_url("https://example.com/ficha")
        assert "legacy content" in html


@pytest.mark.asyncio
async def test_fetch_url_bytes_scrapling_backend():
    """fetch_url_bytes uses basic Fetcher (no stealth needed for PDFs)."""
    with patch("scraper.extract.fetch._get_backend", return_value="scrapling"), \
         patch("scraper.extract.fetch._fetch_bytes_with_scrapling", new_callable=AsyncMock, return_value=b"%PDF-1.4 fake") as mock_fetch:
        from scraper.extract.fetch import fetch_url_bytes
        data = await fetch_url_bytes("https://example.com/doc.pdf")
        assert data.startswith(b"%PDF")
        mock_fetch.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_url_scrapling_error_wraps_in_fetch_error():
    """Scrapling errors are wrapped in FetchError."""
    with patch("scraper.extract.fetch._get_backend", return_value="scrapling"), \
         patch("scraper.extract.fetch._fetch_with_scrapling", new_callable=AsyncMock, side_effect=Exception("connection refused")):
        from scraper.extract.fetch import FetchError, fetch_url
        with pytest.raises(FetchError, match="connection refused"):
            await fetch_url("https://example.com")
```

- [ ] **Step 2: Run tests — fail**

Run: `poetry run pytest tests/unit/test_fetch_scrapling.py -v`
Expected: FAIL — `_get_backend`, `_fetch_with_scrapling` don't exist.

- [ ] **Step 3: Rewrite fetch.py**

Replace the entire content of `src/scraper/extract/fetch.py`:

```python
"""HTTP fetcher with dual backend: legacy (httpx+Playwright) or Scrapling."""
from __future__ import annotations

import asyncio
import re

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
    """Raised when a URL cannot be fetched."""


def _get_backend() -> str:
    from scraper.config import get_settings
    return get_settings().fetcher_backend


def is_js_rendered(html: str) -> bool:
    if _NOSCRIPT_JS_PATTERN.search(html):
        return True
    num_links = len(re.findall(r"<a\b", html, re.IGNORECASE))
    visible = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    visible = re.sub(r"<style[^>]*>.*?</style>", "", visible, flags=re.DOTALL | re.IGNORECASE)
    visible = re.sub(r"<[^>]+>", "", visible)
    body_len = len(visible.strip())
    if body_len < 1500:
        return True
    if body_len < 3000 and num_links >= 30:
        return True
    return False


# ---------------------------------------------------------------------------
# Scrapling backend
# ---------------------------------------------------------------------------

async def _fetch_with_scrapling(url: str, timeout: float = _DEFAULT_TIMEOUT) -> str:
    from scrapling.fetchers import StealthyFetcher
    loop = asyncio.get_event_loop()
    page = await loop.run_in_executor(
        None, lambda: StealthyFetcher.fetch(url, headless=True, network_idle=True)
    )
    return page.html


async def _fetch_bytes_with_scrapling(url: str, timeout: float = _DEFAULT_TIMEOUT) -> bytes:
    from scrapling.fetchers import Fetcher
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None, lambda: Fetcher.get(url)
    )
    return response.content


# ---------------------------------------------------------------------------
# Legacy backend (httpx + Playwright)
# ---------------------------------------------------------------------------

import httpx

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


@retry(
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    reraise=True,
)
async def _fetch_bytes_with_httpx(url: str, timeout: float) -> bytes:
    headers = {"User-Agent": _USER_AGENT}
    async with httpx.AsyncClient(
        timeout=timeout, headers=headers, follow_redirects=True
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


async def fetch_with_playwright(url: str, timeout: float = _DEFAULT_TIMEOUT) -> str:
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


# ---------------------------------------------------------------------------
# Public API (routes to backend based on feature flag)
# ---------------------------------------------------------------------------

async def fetch_url(url: str, timeout: float = _DEFAULT_TIMEOUT) -> str:
    backend = _get_backend()
    try:
        if backend == "scrapling":
            html = await _fetch_with_scrapling(url, timeout)
            log.info("fetch_url_success", url=url, backend="scrapling", length=len(html))
            return html
        else:
            html = await _fetch_with_httpx(url, timeout)
            log.info("fetch_url_success", url=url, backend="legacy", length=len(html))
            return html
    except FetchError:
        raise
    except httpx.TimeoutException as e:
        raise FetchError(f"Timeout fetching {url}: {e}") from e
    except httpx.HTTPStatusError as e:
        raise FetchError(f"HTTP {e.response.status_code} for {url}") from e
    except httpx.TransportError as e:
        raise FetchError(f"Transport error for {url}: {e}") from e
    except Exception as e:
        raise FetchError(f"Fetch failed for {url} ({backend}): {e}") from e


async def fetch_url_bytes(url: str, timeout: float = _DEFAULT_TIMEOUT) -> bytes:
    backend = _get_backend()
    try:
        if backend == "scrapling":
            data = await _fetch_bytes_with_scrapling(url, timeout)
            log.info("fetch_url_bytes_success", url=url, backend="scrapling", bytes=len(data))
            return data
        else:
            data = await _fetch_bytes_with_httpx(url, timeout)
            log.info("fetch_url_bytes_success", url=url, backend="legacy", bytes=len(data))
            return data
    except FetchError:
        raise
    except httpx.TimeoutException as e:
        raise FetchError(f"Timeout fetching {url}: {e}") from e
    except httpx.HTTPStatusError as e:
        raise FetchError(f"HTTP {e.response.status_code} for {url}") from e
    except httpx.TransportError as e:
        raise FetchError(f"Transport error for {url}: {e}") from e
    except Exception as e:
        raise FetchError(f"Fetch bytes failed for {url} ({backend}): {e}") from e
```

- [ ] **Step 4: Run tests — pass**

Run: `poetry run pytest tests/unit/test_fetch_scrapling.py -v`
Expected: All PASS.

- [ ] **Step 5: Run full suite**

Run: `poetry run pytest --tb=short -q`
Expected: All pass (existing test_fetch.py tests still work via legacy path).

- [ ] **Step 6: Commit**

```bash
git add src/scraper/extract/fetch.py tests/unit/test_fetch_scrapling.py
git commit -m "feat(fetch): dual backend with Scrapling StealthyFetcher + legacy httpx"
```

---

### Task 3: Update html.py for Scrapling Session Fetching

**Files:**
- Modify: `src/scraper/extract/html.py`

- [ ] **Step 1: Add session-based multi-fetch helper**

In `src/scraper/extract/html.py`, add after the existing imports (around line 30):

```python
from scraper.config import get_settings
```

Then find the `_fetch_and_extract_pdf` and `_fetch_and_extract_html_subpage` section. The current code calls `fetch_url_bytes` and `fetch_url` individually. Add a session-based batch fetch function before `extract_from_url`:

```python
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
                    results[url] = page.html
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
```

- [ ] **Step 2: Run existing html tests**

Run: `poetry run pytest tests/unit/test_extract_html.py -v`
Expected: PASS (no behavioral change to existing functions).

- [ ] **Step 3: Commit**

```bash
git add src/scraper/extract/html.py
git commit -m "feat(html): add session-based batch fetch for Scrapling backend"
```

---

### Task 4: Rules v7

**Files:**
- Create: `rules/v7.md`

- [ ] **Step 1: Create rules/v7.md**

Copy rules/v6.md as base, then add the new sections. The file should start with the v7 header and contain ALL v6 rules plus the new ones. Here are the additions to make at the appropriate locations:

**Replace the header:**
```markdown
# Sabbi — Filosofía de Clasificación de Productos de Inversión — v7

**Fecha:** 2026-05-03
**Autor:** Sabbi + Claude
**Status:** Iteración post-Scrapling integration — fetch mejorado + calibración obligatoria
**Base:** v6 + reglas de fetching mejorado (R-FETCH) y calibración (R-CAL)
```

**Add "Cambios vs v6" section after the header:**
```markdown
## Cambios vs v6

1. **Fetching mejorado (R-FETCH-1/2/3).** StealthyFetcher con bypass anti-bot reemplaza httpx+Playwright. Retry automático con stealth antes de marcar low_quality.
2. **Calibración obligatoria (R-CAL-1/2).** Todo cambio de fetcher o reglas requiere benchmark comparativo con métricas de aceptación definidas.
```

**Add new rule sections before "## Proceso cuando hay duda":**

```markdown
## NUEVO: Reglas de Fetching Mejorado

### R-FETCH-1: Retry con stealth

Si el primer intento de fetch devuelve contenido vacío (raw_text < 200 chars) o error de protección anti-bot (Cloudflare challenge page, 403, 503 con challenge), re-intentar automáticamente con StealthyFetcher antes de marcar como `low_quality`. El pipeline solo declara "no hay datos" si AMBOS intentos fallan.

### R-FETCH-2: Re-clasificar documentos sin datos

Documentos que en v6 se clasificaban con `confidence=0.0` por falta de acceso al contenido (fetch vacío, página protegida) deben re-intentarse con stealth fetch. Solo marcar `confidence=0.0` si el stealth fetch también falla y no hay contenido útil.

### R-FETCH-3: Preferir versión con más contenido

Cuando Scrapling obtiene más contenido que el fetch básico (medido en caracteres de raw_text), usar la versión con más contenido como fuente primaria. Esto es especialmente relevante para sitios con JS-rendered content donde StealthyFetcher obtiene el DOM completo y el fetch HTTP plano solo obtiene el shell.

---

## NUEVO: Reglas de Calibración

### R-CAL-1: Benchmark obligatorio

Todo cambio de fetcher o reglas debe ir acompañado de un run de `calibrate_pipeline.py` sobre el validation set completo (19 productos). El reporte debe mostrar delta por atributo vs la versión anterior y guardarse como artefacto.

### R-CAL-2: Criterio de aceptación

Un cambio se considera mejora solo si cumple AL MENOS UNA de estas condiciones:
- (a) Ningún atributo baja más de 2 puntos porcentuales, Y al menos un atributo sube más de 3pp
- (b) El promedio global de accuracy sube más de 1 punto porcentual sin que ningún atributo baje más de 5pp

Si el cambio no cumple ninguna, se revierte o se itera.
```

**Update the Versionado section at the end:**
```markdown
- **v7** (2026-05-03): Scrapling integration — fetching mejorado con StealthyFetcher (R-FETCH), calibración obligatoria (R-CAL).
```

- [ ] **Step 2: Verify file is valid markdown**

Run: `poetry run python -c "from pathlib import Path; print(len(Path('rules/v7.md').read_text(encoding='utf-8')), 'chars')"` 
Expected: File size > v6.md (which is ~8000 chars).

- [ ] **Step 3: Commit**

```bash
git add rules/v7.md
git commit -m "docs: rules v7 with R-FETCH and R-CAL for Scrapling integration"
```

---

### Task 5: Add --output Flag to calibrate_pipeline.py

**Files:**
- Modify: `src/scraper/scripts/calibrate_pipeline.py`

- [ ] **Step 1: Add --output argument to CLI parser**

In `cli()` (around line 246), add after `--only-nombres`:

```python
    parser.add_argument(
        "--output",
        default=None,
        help="Path to write JSON results (for compare_calibrations.py)",
    )
```

- [ ] **Step 2: Pass output to _main**

Update the `_main` signature to accept `output_path: str | None = None`:

```python
async def _main(
    rules_path: Path,
    dry_run: bool,
    limit: int | None,
    exclude_clase: str = "",
    only_nombres: str = "",
    output_path: str | None = None,
) -> int:
```

- [ ] **Step 3: Write JSON output at end of _main**

After the `rv.validation_accuracy = ...` block (around line 238), before the final print, add:

```python
    if output_path:
        import json
        output_data = {
            "version": version,
            "rules_path": str(rules_path),
            "fetcher_backend": get_settings().fetcher_backend,
            "n_products": len(reports),
            "per_attribute_accuracy": accuracy,
            "total_cost_usd": llm.cost.total_usd,
            "details": per_product_details,
        }
        Path(output_path).write_text(
            json.dumps(output_data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"Results written to {output_path}")
```

- [ ] **Step 4: Update cli() call to pass output**

```python
    sys.exit(
        asyncio.run(
            _main(
                Path(args.rules),
                dry_run=args.dry_run,
                limit=args.limit,
                exclude_clase=args.exclude_clase,
                only_nombres=args.only_nombres,
                output_path=args.output,
            )
        )
    )
```

- [ ] **Step 5: Verify the flag is accepted**

Run: `poetry run python -m scraper.scripts.calibrate_pipeline --dry-run --output test.json`
Expected: `Calibración pipeline (dry-run): would run rules=...`

- [ ] **Step 6: Commit**

```bash
git add src/scraper/scripts/calibrate_pipeline.py
git commit -m "feat(calibrate): add --output flag for JSON results export"
```

---

### Task 6: Create compare_calibrations.py Script

**Files:**
- Create: `src/scraper/scripts/compare_calibrations.py`
- Create: `tests/unit/test_compare_calibrations.py`

- [ ] **Step 1: Write tests**

```python
# tests/unit/test_compare_calibrations.py
"""Tests for calibration comparison script."""
import json
from scraper.scripts.compare_calibrations import compare, format_report


def _make_results(accuracy: dict, cost: float = 0.05, n: int = 19) -> dict:
    return {
        "version": "test",
        "rules_path": "rules/test.md",
        "fetcher_backend": "legacy",
        "n_products": n,
        "per_attribute_accuracy": accuracy,
        "total_cost_usd": cost,
        "details": [
            {"nombre": f"p{i}", "global_confidence": 0.8, "elapsed_s": 10.0}
            for i in range(n)
        ],
    }


def test_compare_detects_improvement():
    v6 = _make_results({"comision": 0.895, "moneda": 1.0})
    v7 = _make_results({"comision": 0.947, "moneda": 1.0})
    result = compare(v6, v7)
    assert result["comision"]["delta"] > 0
    assert result["comision"]["status"] == "improved"
    assert result["moneda"]["status"] == "unchanged"


def test_compare_detects_regression():
    v6 = _make_results({"comision": 0.947})
    v7 = _make_results({"comision": 0.842})
    result = compare(v6, v7)
    assert result["comision"]["delta"] < 0
    assert result["comision"]["status"] == "regressed"


def test_format_report_produces_table():
    v6 = _make_results({"comision": 0.895, "moneda": 1.0}, cost=0.04)
    v7 = _make_results({"comision": 0.947, "moneda": 1.0}, cost=0.06)
    report = format_report(v6, v7)
    assert "comision" in report
    assert "COMPARISON" in report
```

- [ ] **Step 2: Run tests — fail**

Run: `poetry run pytest tests/unit/test_compare_calibrations.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement compare_calibrations.py**

```python
# src/scraper/scripts/compare_calibrations.py
"""Compare two calibration JSON result files and produce a report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean


def compare(v6: dict, v7: dict) -> dict[str, dict]:
    """Compare per-attribute accuracy between two calibration runs."""
    all_attrs = set(v6.get("per_attribute_accuracy", {})) | set(v7.get("per_attribute_accuracy", {}))
    result = {}
    for attr in sorted(all_attrs):
        acc_v6 = v6.get("per_attribute_accuracy", {}).get(attr, 0.0)
        acc_v7 = v7.get("per_attribute_accuracy", {}).get(attr, 0.0)
        delta = acc_v7 - acc_v6
        if abs(delta) < 0.001:
            status = "unchanged"
        elif delta > 0:
            status = "improved"
        else:
            status = "regressed"
        result[attr] = {"v6": acc_v6, "v7": acc_v7, "delta": delta, "status": status}
    return result


def _avg_confidence(data: dict) -> float:
    details = data.get("details", [])
    confs = [d.get("global_confidence", 0) for d in details if d.get("global_confidence") is not None]
    return mean(confs) if confs else 0.0


def _avg_duration(data: dict) -> float:
    details = data.get("details", [])
    durs = [d.get("elapsed_s", 0) for d in details]
    return mean(durs) if durs else 0.0


def format_report(v6: dict, v7: dict) -> str:
    """Produce a formatted comparison report."""
    comp = compare(v6, v7)
    lines = [
        f"=== CALIBRATION COMPARISON v6 ({v6.get('fetcher_backend', '?')}) vs v7 ({v7.get('fetcher_backend', '?')}) ===",
        "",
        f"{'Attribute':<22s} | {'v6 acc':>8s} | {'v7 acc':>8s} | {'Delta':>8s} | Status",
        "-" * 70,
    ]
    for attr, d in comp.items():
        status_icon = {"improved": "improved", "regressed": "REGRESSED", "unchanged": "-"}.get(d["status"], "?")
        lines.append(
            f"{attr:<22s} | {d['v6']:>7.1%} | {d['v7']:>7.1%} | {d['delta']:>+7.1%} | {status_icon}"
        )

    lines.append("")
    lines.append(f"{'Global confidence':<22s} | {_avg_confidence(v6):>8.2f} | {_avg_confidence(v7):>8.2f}")
    lines.append(f"{'Avg cost USD':<22s} | ${v6.get('total_cost_usd', 0) / max(v6.get('n_products', 1), 1):>7.3f} | ${v7.get('total_cost_usd', 0) / max(v7.get('n_products', 1), 1):>7.3f}")
    lines.append(f"{'Avg duration (s)':<22s} | {_avg_duration(v6):>8.1f} | {_avg_duration(v7):>8.1f}")

    return "\n".join(lines)


def cli() -> None:
    parser = argparse.ArgumentParser(description="Compare two calibration JSON results.")
    parser.add_argument("v6_path", help="Path to v6 results JSON")
    parser.add_argument("v7_path", help="Path to v7 results JSON")
    args = parser.parse_args()

    v6 = json.loads(Path(args.v6_path).read_text(encoding="utf-8"))
    v7 = json.loads(Path(args.v7_path).read_text(encoding="utf-8"))

    print(format_report(v6, v7))


if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: Run tests — pass**

Run: `poetry run pytest tests/unit/test_compare_calibrations.py -v`
Expected: All 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scraper/scripts/compare_calibrations.py tests/unit/test_compare_calibrations.py
git commit -m "feat: add compare_calibrations.py for v6 vs v7 benchmark"
```

---

### Task 7: Update Level 3 Intensive with Scrapling MCP Info

**Files:**
- Modify: `src/scraper/search/level3_intensive.py`

- [ ] **Step 1: Update the Level 3 prompt**

In `run_claude_intensive()`, update the `user_msg` to inform Claude about Scrapling MCP tools when available. Replace the current `user_msg` assignment (lines 27-36) with:

```python
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
```

- [ ] **Step 2: Run existing Level 3 tests**

Run: `poetry run pytest tests/integration/test_level3_intensive_mocked.py -v`
Expected: PASS (the hint is additive, doesn't change behavior).

- [ ] **Step 3: Commit**

```bash
git add src/scraper/search/level3_intensive.py
git commit -m "feat(level3): inform Claude about Scrapling MCP tools when available"
```

---

### Task 8: Configure Scrapling MCP Server

**Files:**
- Modify: `.claude/settings.local.json`

- [ ] **Step 1: Add Scrapling MCP server to Claude Code settings**

Read the current `.claude/settings.local.json` and add the MCP server config. Add a `mcpServers` section:

```json
{
  "permissions": {
    "allow": [
      ... (existing entries)
    ]
  },
  "mcpServers": {
    "ScraplingServer": {
      "command": "scrapling",
      "args": ["mcp"]
    }
  }
}
```

Note: Find the full path to scrapling executable first:
```bash
where scrapling   # Windows
```

And use the full path in the config if needed.

- [ ] **Step 2: Verify MCP server starts**

Run: `scrapling mcp --http --host 127.0.0.1 --port 8765` in background and verify it responds.

- [ ] **Step 3: Commit**

```bash
git add .claude/settings.local.json
git commit -m "feat: configure Scrapling MCP server for Claude Code"
```

Note: `.claude/` is in .gitignore, so this won't be committed to the repo. Instead, document the setup in the spec.

---

### Task 9: Final Integration Test + Push

**Files:**
- Run full test suite
- Push to GitHub

- [ ] **Step 1: Run full test suite**

Run: `poetry run pytest --tb=short -q`
Expected: All pass (except pre-existing failure).

- [ ] **Step 2: Verify Scrapling fetcher works end-to-end**

Run: `poetry run python -c "
import asyncio
from scraper.extract.fetch import fetch_url
html = asyncio.run(fetch_url('https://quotes.toscrape.com/'))
print(f'Fetched {len(html)} chars with Scrapling')
assert len(html) > 1000
print('OK')
"`
Expected: `Fetched XXXXX chars with Scrapling` and `OK`.

- [ ] **Step 3: Verify legacy fallback works**

Run: `FETCHER_BACKEND=legacy poetry run python -c "
import asyncio
from scraper.extract.fetch import fetch_url
html = asyncio.run(fetch_url('https://quotes.toscrape.com/'))
print(f'Fetched {len(html)} chars with legacy')
assert len(html) > 1000
print('OK')
"`
Expected: `Fetched XXXXX chars with legacy` and `OK`.

- [ ] **Step 4: Push to GitHub**

```bash
git push origin master
```

- [ ] **Step 5: Document calibration commands for the user**

Print the commands the user needs to run the benchmark:

```bash
# Run v6 baseline (legacy fetcher)
FETCHER_BACKEND=legacy poetry run python -m scraper.scripts.calibrate_pipeline --rules rules/v6.md --output results_v6.json

# Run v7 with Scrapling
FETCHER_BACKEND=scrapling poetry run python -m scraper.scripts.calibrate_pipeline --rules rules/v7.md --output results_v7.json

# Compare
poetry run python -m scraper.scripts.compare_calibrations results_v6.json results_v7.json
```
