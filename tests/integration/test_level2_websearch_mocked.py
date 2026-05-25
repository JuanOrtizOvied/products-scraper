import json
from datetime import UTC, datetime


def _make_ficha(source_url: str, source_type: str = "html", source_confidence: float = 0.85):
    from scraper.agents.types import AttributeExtraction, ExtractedFicha

    return ExtractedFicha(
        source_url=source_url,
        source_type=source_type,
        source_confidence=source_confidence,
        fetched_at=datetime.now(tz=UTC),
        raw_text="content",
        tables=[],
        attributes={
            "nombre": AttributeExtraction(
                value="X", confidence=0.9, reasoning="r", raw_quote=""
            )
        },
        citations=[source_url],
        extraction_cost_usd=0.05,
        extraction_duration_ms=500,
    )


async def test_discover_urls_returns_parsed_list(mock_llm_client):
    from scraper.search.level2_websearch import _discover_urls

    urls_json = json.dumps(
        [
            "https://bancochile.cl/fondo/x",
            "https://cmfchile.cl/fondo/y",
        ]
    )
    mock_llm_client.call.return_value = mock_llm_client.make_result(urls_json)

    urls = await _discover_urls("Test Fund", mock_llm_client)
    assert urls == [
        "https://bancochile.cl/fondo/x",
        "https://cmfchile.cl/fondo/y",
    ]


async def test_discover_urls_handles_noisy_response(mock_llm_client):
    """Claude sometimes prefaces JSON with explanatory text. Regex should extract."""
    from scraper.search.level2_websearch import _discover_urls

    noisy = (
        'Basado en las búsquedas encontré: ["https://a.com/f"] '
        "Espero que sirva."
    )
    mock_llm_client.call.return_value = mock_llm_client.make_result(noisy)

    urls = await _discover_urls("X", mock_llm_client)
    assert urls == ["https://a.com/f"]


async def test_discover_urls_returns_empty_on_bad_json(mock_llm_client):
    from scraper.search.level2_websearch import _discover_urls

    mock_llm_client.call.return_value = mock_llm_client.make_result(
        "no json at all here"
    )
    urls = await _discover_urls("X", mock_llm_client)
    assert urls == []


async def test_discover_urls_passes_web_search_tool(mock_llm_client):
    from scraper.search.level2_websearch import _discover_urls

    mock_llm_client.call.return_value = mock_llm_client.make_result("[]")
    await _discover_urls("X", mock_llm_client)

    call = mock_llm_client.call.call_args
    tools = call.kwargs.get("tools")
    assert tools is not None
    assert any(t.get("type", "").startswith("web_search") for t in tools)


async def test_discover_urls_filters_invalid(mock_llm_client):
    from scraper.search.level2_websearch import _discover_urls

    mixed = json.dumps(
        [
            "https://ok.com/x",
            "not a url",
            12345,
            "ftp://old-school.com/x",  # wrong scheme
            "https://ok.com/y",
        ]
    )
    mock_llm_client.call.return_value = mock_llm_client.make_result(mixed)

    urls = await _discover_urls("X", mock_llm_client)
    assert urls == ["https://ok.com/x", "https://ok.com/y"]


async def test_discover_urls_caps_at_max(mock_llm_client):
    from scraper.search.level2_websearch import _discover_urls

    many = json.dumps([f"https://a.com/{i}" for i in range(20)])
    mock_llm_client.call.return_value = mock_llm_client.make_result(many)

    urls = await _discover_urls("X", mock_llm_client)
    assert len(urls) == 7


async def test_run_claude_websearch_flattens_per_url_fichas(monkeypatch, mock_llm_client):
    from scraper.search import level2_websearch as mod

    async def fake_discover(nombre, llm):
        return ["https://a.com/x", "https://b.com/y"]

    async def fake_extract(*, url, llm, **kwargs):
        # One URL returns HTML only, the other returns HTML + a PDF
        if "a.com" in url:
            return [_make_ficha(url, "html")]
        return [_make_ficha(url, "html"), _make_ficha(url + "/doc.pdf", "pdf_text")]

    monkeypatch.setattr(mod, "_discover_urls", fake_discover)
    monkeypatch.setattr(mod, "extract_from_url", fake_extract)

    fichas = await mod.run_claude_websearch("Test", mock_llm_client)
    assert len(fichas) == 3
    urls = sorted(f.source_url for f in fichas)
    assert urls == [
        "https://a.com/x",
        "https://b.com/y",
        "https://b.com/y/doc.pdf",
    ]


async def test_run_claude_websearch_handles_extract_failure_per_url(
    monkeypatch, mock_llm_client
):
    from scraper.search import level2_websearch as mod

    async def fake_discover(nombre, llm):
        return ["https://good.com/x", "https://bad.com/y"]

    async def fake_extract(*, url, llm, **kwargs):
        if "bad" in url:
            raise RuntimeError("simulated extract failure")
        return [_make_ficha(url, "html")]

    monkeypatch.setattr(mod, "_discover_urls", fake_discover)
    monkeypatch.setattr(mod, "extract_from_url", fake_extract)

    fichas = await mod.run_claude_websearch("Test", mock_llm_client)
    # The failure shouldn't kill the whole N2; good URL's ficha comes through
    assert len(fichas) == 1
    assert fichas[0].source_url == "https://good.com/x"


async def test_run_claude_websearch_empty_on_no_urls(monkeypatch, mock_llm_client):
    from scraper.search import level2_websearch as mod

    async def fake_discover(nombre, llm):
        return []

    monkeypatch.setattr(mod, "_discover_urls", fake_discover)

    fichas = await mod.run_claude_websearch("Test", mock_llm_client)
    assert fichas == []
