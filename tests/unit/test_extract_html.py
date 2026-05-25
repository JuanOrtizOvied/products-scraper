from pathlib import Path


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

    fixture = (
        Path(__file__).parents[1] / "fixtures" / "html" / "credicorpcapital_sample.html"
    )
    html = fixture.read_text(encoding="utf-8")
    raw_text, tables = clean_html(html)

    assert "Fondo Crecimiento" in raw_text
    assert "Credicorp Capital SAF" in raw_text
    assert len(tables) == 1
    assert any("Comisión" in cell for row in tables[0] for cell in row)


def test_find_pdf_links_detects_explicit_pdf_href():
    from scraper.extract.html import find_pdf_links

    html = """<html><body><main>
        <a href="/docs/folleto.pdf">Folleto Informativo</a>
        <a href="/other">Irrelevant</a>
    </main></body></html>"""
    links = find_pdf_links(html, "https://banchile.cl/fondo/xxx")
    assert len(links) == 1
    assert links[0] == "https://banchile.cl/docs/folleto.pdf"


def test_find_pdf_links_skips_off_origin():
    from scraper.extract.html import find_pdf_links

    html = """<html><body><main>
        <a href="https://other-site.com/folleto.pdf">Folleto</a>
    </main></body></html>"""
    links = find_pdf_links(html, "https://banchile.cl/fondo/xxx")
    assert links == []


def test_find_pdf_links_requires_relevance_signal():
    from scraper.extract.html import find_pdf_links

    html = """<html><body><main>
        <a href="/docs/A.pdf">A</a>
        <a href="/docs/B.pdf">Prospecto</a>
        <a href="/docs/C.pdf">Random text</a>
    </main></body></html>"""
    links = find_pdf_links(html, "https://x.com/fondo")
    # Only B has a relevance keyword in anchor text
    assert links == ["https://x.com/docs/B.pdf"]


def test_find_pdf_links_accepts_keyword_in_url_path():
    """PDF filename contains a keyword — accept even if anchor text is vague."""
    from scraper.extract.html import find_pdf_links

    html = """<html><body><main>
        <a href="/docs/FBA_reglamento_2024.pdf">Descargar</a>
    </main></body></html>"""
    links = find_pdf_links(html, "https://x.com/fondo")
    assert links == ["https://x.com/docs/FBA_reglamento_2024.pdf"]


def test_find_pdf_links_rejects_unrelated_pdf():
    """Same-org .pdf with no keyword in path or anchor — skip."""
    from scraper.extract.html import find_pdf_links

    html = """<html><body><main>
        <a href="/docs/Politica_Salud_y_Seguridad.pdf">Política OSH</a>
        <a href="/docs/Personas-Vinculadas-ComA-7404.pdf">Personas vinculadas</a>
    </main></body></html>"""
    links = find_pdf_links(html, "https://x.com/fondo")
    assert links == []


def test_find_pdf_links_detects_expanded_keywords():
    """New keywords: presentación, cartera, gestión, reporte, informe, memoria."""
    from scraper.extract.html import find_pdf_links

    html = """<html><body><main>
        <a href="/docs/presentacion_comercial.pdf">Presentación comercial</a>
        <a href="/docs/cartera.pdf">Cartera semanal</a>
        <a href="/docs/memoria_2024.pdf">Memoria anual</a>
        <a href="/docs/reglamentos_de_gestion.pdf">Reglamentos de gestión</a>
    </main></body></html>"""
    links = find_pdf_links(html, "https://x.com/fondo")
    assert len(links) == 4


def test_find_pdf_links_caps_at_max():
    from scraper.extract.html import find_pdf_links

    hrefs = [f'<a href="/doc{i}.pdf">Folleto {i}</a>' for i in range(20)]
    html = f"<html><body><main>{''.join(hrefs)}</main></body></html>"
    links = find_pdf_links(html, "https://x.com/fondo")
    assert len(links) == 8  # _MAX_PDFS_PER_PAGE


def test_find_pdf_links_allows_same_registrable_subdomain():
    from scraper.extract.html import find_pdf_links

    # PDF lives on a sibling subdomain of the same organization
    html = """<html><body><main>
        <a href="https://assets.bancochile.cl/uploads/folleto.pdf">Folleto Informativo</a>
    </main></body></html>"""
    links = find_pdf_links(html, "https://sitiospublicos.bancochile.cl/fondo/x")
    assert links == ["https://assets.bancochile.cl/uploads/folleto.pdf"]


def test_find_pdf_links_handles_composite_tld():
    """alianza.com.co is a registrable domain — www and assets subdomains should match."""
    from scraper.extract.html import find_pdf_links

    html = """<html><body><main>
        <a href="https://assets.alianza.com.co/docs/reglamento.pdf">Reglamento</a>
    </main></body></html>"""
    links = find_pdf_links(html, "https://www.alianza.com.co/fondo/x")
    assert links == ["https://assets.alianza.com.co/docs/reglamento.pdf"]


def test_find_pdf_links_rejects_different_organization():
    from scraper.extract.html import find_pdf_links

    html = """<html><body><main>
        <a href="https://evil.com/totally-different.pdf">Folleto</a>
    </main></body></html>"""
    links = find_pdf_links(html, "https://bancochile.cl/fondo/x")
    assert links == []


def test_find_pdf_links_skips_javascript_mailto():
    from scraper.extract.html import find_pdf_links

    html = """<html><body><main>
        <a href="javascript:void(0)">Folleto</a>
        <a href="mailto:x@y.com">Folleto</a>
        <a href="#section">Folleto</a>
    </main></body></html>"""
    links = find_pdf_links(html, "https://x.com/fondo")
    assert links == []


def test_looks_like_pdf_url_path_extension():
    from scraper.extract.html import _looks_like_pdf_url

    assert _looks_like_pdf_url("https://a.com/doc.pdf") is True
    assert _looks_like_pdf_url("https://a.com/doc.PDF") is True
    assert _looks_like_pdf_url("https://a.com/docs/file.pdf?x=1") is True


def test_looks_like_pdf_url_query_param():
    from scraper.extract.html import _looks_like_pdf_url

    assert _looks_like_pdf_url("https://a.com/viewer?file=x.pdf") is True
    assert _looks_like_pdf_url("https://a.com/viewer?file=X.PDF") is True


def test_looks_like_pdf_url_view_pdf_endpoint():
    from scraper.extract.html import _looks_like_pdf_url

    assert _looks_like_pdf_url("https://fixscr.com/emisor/view-pdf") is True
    assert _looks_like_pdf_url("https://a.com/docs/pdf") is True
    assert _looks_like_pdf_url("https://a.com/docs/pdf/") is True


def test_looks_like_pdf_url_non_pdf():
    from scraper.extract.html import _looks_like_pdf_url

    assert _looks_like_pdf_url("https://a.com/fondos/detail") is False
    assert _looks_like_pdf_url("https://a.com/") is False
    assert _looks_like_pdf_url("https://a.com/search?q=hello") is False


async def test_extract_from_url_routes_pdf_url_directly(monkeypatch, mock_llm_client):
    """When the URL itself is a PDF, skip HTML pipeline and go to PDF extractor."""
    from datetime import UTC, datetime

    from scraper.agents.types import AttributeExtraction, ExtractedFicha
    from scraper.extract import html as html_mod

    called_pdf_path = []

    async def fake_fetch_pdf(pdf_url, llm, nombre=None):
        called_pdf_path.append(pdf_url)
        return ExtractedFicha(
            source_url=pdf_url,
            source_type="pdf_text",
            source_confidence=0.9,
            fetched_at=datetime.now(tz=UTC),
            raw_text="pdf body",
            tables=[],
            attributes={
                "nombre": AttributeExtraction(
                    value="PDF Fund", confidence=1.0, reasoning="", raw_quote=""
                )
            },
            citations=[pdf_url],
            extraction_cost_usd=0.05,
            extraction_duration_ms=500,
        )

    monkeypatch.setattr(html_mod, "_fetch_and_extract_pdf", fake_fetch_pdf)

    async def should_not_run(*args, **kwargs):
        raise AssertionError("fetch_url should not be called for a .pdf URL")

    monkeypatch.setattr(html_mod, "fetch_url", should_not_run)

    fichas = await html_mod.extract_from_url(
        url="https://pellegrini.com.ar/docs/reglamento.pdf",
        llm=mock_llm_client,
        nombre="Test Fund",
    )
    assert len(fichas) == 1
    assert fichas[0].source_type == "pdf_text"
    assert called_pdf_path == ["https://pellegrini.com.ar/docs/reglamento.pdf"]


async def test_extract_from_url_detects_pdf_magic_bytes(monkeypatch, mock_llm_client):
    """If server returns PDF bytes for a non-.pdf URL, still route to PDF extractor."""
    from datetime import UTC, datetime

    from scraper.agents.types import ExtractedFicha
    from scraper.extract import html as html_mod

    async def fake_fetch(url, timeout=30.0):
        # Looks like HTML URL but server returned PDF bytes
        return "%PDF-1.5\n%..."

    monkeypatch.setattr(html_mod, "fetch_url", fake_fetch)

    called = []

    async def fake_fetch_pdf(pdf_url, llm, nombre=None):
        called.append(pdf_url)
        return ExtractedFicha(
            source_url=pdf_url,
            source_type="pdf_text",
            source_confidence=0.9,
            fetched_at=datetime.now(tz=UTC),
            raw_text="",
            tables=[],
            attributes={},
            citations=[pdf_url],
            extraction_cost_usd=0.0,
            extraction_duration_ms=0,
        )

    monkeypatch.setattr(html_mod, "_fetch_and_extract_pdf", fake_fetch_pdf)

    fichas = await html_mod.extract_from_url(
        url="https://obscure.com/download/123",  # no .pdf in URL
        llm=mock_llm_client,
    )
    assert len(fichas) == 1
    assert called == ["https://obscure.com/download/123"]


async def test_extract_from_url_orchestrates_fetch_and_claude(monkeypatch, mock_llm_client):
    from scraper.extract import html as html_mod

    async def fake_fetch(url: str, timeout: float = 30.0) -> str:
        return (
            "<html><body><main>"
            + "<p>meaningful content here. </p>" * 100
            + "</main></body></html>"
        )

    monkeypatch.setattr(html_mod, "fetch_url", fake_fetch)

    async def fake_extract(**kwargs):
        from datetime import UTC, datetime

        from scraper.agents.types import AttributeExtraction, ExtractedFicha
        return ExtractedFicha(
            source_url=kwargs["source_url"],
            source_type="html",
            source_confidence=0.9,
            fetched_at=datetime.now(tz=UTC),
            raw_text=kwargs["raw_text"],
            tables=kwargs["tables"],
            attributes={
                "nombre": AttributeExtraction(
                    value="X", confidence=1.0, reasoning="r", raw_quote="q"
                )
            },
            citations=[kwargs["source_url"]],
            extraction_cost_usd=0.01,
            extraction_duration_ms=500,
        )

    monkeypatch.setattr(html_mod, "extract_with_claude", fake_extract)

    fichas = await html_mod.extract_from_url(
        url="https://example.com/x", llm=mock_llm_client, follow_pdfs=False
    )
    assert len(fichas) == 1
    assert fichas[0].source_url == "https://example.com/x"
    assert "meaningful content" in fichas[0].raw_text


async def test_extract_from_url_follows_llm_selected_links(monkeypatch, mock_llm_client):
    from datetime import UTC, datetime

    from scraper.agents.types import AttributeExtraction, ExtractedFicha
    from scraper.extract import html as html_mod

    async def fake_fetch(url: str, timeout: float = 30.0) -> str:
        return (
            "<html><body><main>"
            + "<p>HTML content with enough body text to clear threshold. </p>" * 60
            + '<a href="/folleto.pdf">Folleto Informativo</a>'
            + "</main></body></html>"
        )

    monkeypatch.setattr(html_mod, "fetch_url", fake_fetch)

    async def fake_extract(**kwargs):
        return ExtractedFicha(
            source_url=kwargs["source_url"],
            source_type="html",
            source_confidence=0.9,
            fetched_at=datetime.now(tz=UTC),
            raw_text=kwargs["raw_text"],
            tables=kwargs["tables"],
            attributes={
                "nombre": AttributeExtraction(
                    value="X", confidence=1.0, reasoning="r", raw_quote="q"
                )
            },
            citations=[kwargs["source_url"]],
            extraction_cost_usd=0.01,
            extraction_duration_ms=500,
        )

    monkeypatch.setattr(html_mod, "extract_with_claude", fake_extract)

    async def fake_classify_links(html, base_url, nombre, llm):
        return ["https://banchile.cl/fondo/x/folleto.pdf"]

    monkeypatch.setattr(html_mod, "classify_links_with_llm", fake_classify_links)

    async def fake_pdf(pdf_url, llm, nombre=None):
        return ExtractedFicha(
            source_url=pdf_url,
            source_type="pdf_text",
            source_confidence=0.85,
            fetched_at=datetime.now(tz=UTC),
            raw_text="pdf body",
            tables=[],
            attributes={
                "moneda": AttributeExtraction(
                    value="EUR", confidence=1.0, reasoning="pdf", raw_quote="EUR"
                )
            },
            citations=[pdf_url],
            extraction_cost_usd=0.02,
            extraction_duration_ms=300,
        )

    monkeypatch.setattr(html_mod, "_fetch_and_extract_pdf", fake_pdf)

    fichas = await html_mod.extract_from_url(
        url="https://banchile.cl/fondo/x", llm=mock_llm_client, follow_pdfs=True
    )
    assert len(fichas) == 2
    assert fichas[0].source_type == "html"
    assert fichas[1].source_type == "pdf_text"
    assert fichas[1].attributes["moneda"].value == "EUR"


async def test_extract_from_url_link_follow_failure_non_fatal(
    monkeypatch, mock_llm_client
):
    from datetime import UTC, datetime

    from scraper.agents.types import AttributeExtraction, ExtractedFicha
    from scraper.extract import html as html_mod

    async def fake_fetch(url: str, timeout: float = 30.0) -> str:
        return (
            "<html><body><main>"
            + "<p>HTML content with enough body text to clear threshold. </p>" * 60
            + "</main></body></html>"
        )

    monkeypatch.setattr(html_mod, "fetch_url", fake_fetch)

    async def fake_extract(**kwargs):
        return ExtractedFicha(
            source_url=kwargs["source_url"],
            source_type="html",
            source_confidence=0.9,
            fetched_at=datetime.now(tz=UTC),
            raw_text=kwargs["raw_text"],
            tables=kwargs["tables"],
            attributes={
                "nombre": AttributeExtraction(
                    value="X", confidence=1.0, reasoning="r", raw_quote="q"
                )
            },
            citations=[kwargs["source_url"]],
            extraction_cost_usd=0.01,
            extraction_duration_ms=500,
        )

    monkeypatch.setattr(html_mod, "extract_with_claude", fake_extract)

    async def fake_classify_links(html, base_url, nombre, llm):
        return ["https://banchile.cl/broken.pdf"]

    monkeypatch.setattr(html_mod, "classify_links_with_llm", fake_classify_links)

    async def fake_pdf_fail(pdf_url, llm, nombre=None):
        raise RuntimeError("pdf download failed")

    monkeypatch.setattr(html_mod, "_fetch_and_extract_pdf", fake_pdf_fail)

    fichas = await html_mod.extract_from_url(
        url="https://banchile.cl/fondo/x", llm=mock_llm_client, follow_pdfs=True
    )
    # PDF fail doesn't break HTML ficha
    assert len(fichas) == 1
    assert fichas[0].source_type == "html"


async def test_classify_links_with_llm_selects_relevant(monkeypatch, mock_llm_client):
    import json as _j

    from scraper.extract.html import classify_links_with_llm

    html = """<html><body><main>
        <a href="https://admin.com/docs/Fact_Sheet_A.pdf">Conocé toda la información</a>
        <a href="https://admin.com/docs/Politica_OSH.pdf">Política OSH</a>
        <a href="https://admin.com/contacto">Contacto</a>
        <a href="https://admin.com/docs/Reglamento.pdf">Reglamento de gestión</a>
    </main></body></html>"""

    # Simulate Claude returning only the fund-relevant URLs
    selected_json = _j.dumps(
        [
            "https://admin.com/docs/Fact_Sheet_A.pdf",
            "https://admin.com/docs/Reglamento.pdf",
        ]
    )
    mock_llm_client.call.return_value = mock_llm_client.make_result(selected_json)

    urls = await classify_links_with_llm(
        html, "https://admin.com/fondo/x", "Test Fondo", mock_llm_client
    )
    assert urls == [
        "https://admin.com/docs/Fact_Sheet_A.pdf",
        "https://admin.com/docs/Reglamento.pdf",
    ]


async def test_classify_links_with_llm_filters_non_candidate_urls(mock_llm_client):
    """If Claude returns a URL not in our candidates list, reject it (sanity)."""
    import json as _j

    from scraper.extract.html import classify_links_with_llm

    html = """<html><body><main>
        <a href="https://admin.com/docs/A.pdf">Folleto</a>
    </main></body></html>"""

    bogus = _j.dumps(["https://attacker.com/evil.pdf"])
    mock_llm_client.call.return_value = mock_llm_client.make_result(bogus)

    urls = await classify_links_with_llm(
        html, "https://admin.com/fondo/x", None, mock_llm_client
    )
    assert urls == []  # Not in candidates → rejected


async def test_classify_links_with_llm_handles_bad_json(mock_llm_client):
    from scraper.extract.html import classify_links_with_llm

    html = """<html><body><main>
        <a href="https://admin.com/docs/A.pdf">Folleto</a>
    </main></body></html>"""

    mock_llm_client.call.return_value = mock_llm_client.make_result("no json at all")

    urls = await classify_links_with_llm(
        html, "https://admin.com/fondo/x", None, mock_llm_client
    )
    assert urls == []


async def test_classify_links_with_llm_empty_page(mock_llm_client):
    from scraper.extract.html import classify_links_with_llm

    html = "<html><body><main>No links here</main></body></html>"

    urls = await classify_links_with_llm(
        html, "https://admin.com/fondo/x", None, mock_llm_client
    )
    assert urls == []
    # Claude should NOT have been called with no candidates
    assert mock_llm_client.call.call_count == 0


async def test_extract_from_url_fetches_links_in_parallel(monkeypatch, mock_llm_client):
    """Verify sub-link extractions run concurrently, not serially."""
    import asyncio
    from datetime import UTC, datetime

    from scraper.agents.types import AttributeExtraction, ExtractedFicha
    from scraper.extract import html as html_mod

    async def fake_fetch(url: str, timeout: float = 30.0) -> str:
        return "<html><body><main>" + "<p>content. </p>" * 200 + "</main></body></html>"

    monkeypatch.setattr(html_mod, "fetch_url", fake_fetch)

    async def fake_extract(**kwargs):
        return ExtractedFicha(
            source_url=kwargs["source_url"],
            source_type="html",
            source_confidence=0.9,
            fetched_at=datetime.now(tz=UTC),
            raw_text=kwargs["raw_text"],
            tables=kwargs["tables"],
            attributes={
                "nombre": AttributeExtraction(
                    value="X", confidence=1.0, reasoning="r", raw_quote="q"
                )
            },
            citations=[kwargs["source_url"]],
            extraction_cost_usd=0.01,
            extraction_duration_ms=500,
        )

    monkeypatch.setattr(html_mod, "extract_with_claude", fake_extract)

    async def fake_classify_links(html, base_url, nombre, llm):
        return [
            "https://banchile.cl/a.pdf",
            "https://banchile.cl/b.pdf",
            "https://banchile.cl/c.pdf",
        ]

    monkeypatch.setattr(html_mod, "classify_links_with_llm", fake_classify_links)

    concurrent_count = 0
    max_concurrent = 0
    lock = asyncio.Lock()

    async def fake_extract_link(link_url, llm, nombre=None):
        nonlocal concurrent_count, max_concurrent
        async with lock:
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
        await asyncio.sleep(0.05)  # simulate IO
        async with lock:
            concurrent_count -= 1
        return [
            ExtractedFicha(
                source_url=link_url,
                source_type="pdf_text",
                source_confidence=0.8,
                fetched_at=datetime.now(tz=UTC),
                raw_text="",
                tables=[],
                attributes={},
                citations=[link_url],
                extraction_cost_usd=0.01,
                extraction_duration_ms=50,
            )
        ]

    monkeypatch.setattr(html_mod, "_fetch_and_extract_link", fake_extract_link)

    fichas = await html_mod.extract_from_url(
        url="https://banchile.cl/fondo/x", llm=mock_llm_client, follow_pdfs=True
    )
    assert len(fichas) == 4  # 1 HTML + 3 sub-extractions
    assert max_concurrent >= 2, "sub-extractions should run concurrently"
