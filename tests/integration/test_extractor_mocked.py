import json


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
            "attributes": {
                "nombre": {
                    "value": "Y",
                    "confidence": 1.0,
                    "reasoning": "",
                    "raw_quote": "Y",
                },
            },
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


async def test_extractor_parses_document_date(mock_llm_client):
    from scraper.agents.extractor import extract_with_claude

    extractor_output = json.dumps({
        "source_type": "pdf_text",
        "source_confidence": 0.85,
        "document_date": "2026-03-31",
        "raw_text": "Ficha técnica",
        "tables": [],
        "attributes": {
            "nombre": {"value": "Test Fund", "confidence": 0.9, "reasoning": "r", "raw_quote": "q"}
        },
        "citations": [],
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(extractor_output)

    ficha = await extract_with_claude(
        llm=mock_llm_client,
        source_url="https://test.com",
        source_type="pdf_text",
        raw_text="Vigente al 31 de marzo de 2026",
        tables=[],
        nombre="Test Fund",
    )
    assert ficha.document_date is not None
    assert ficha.document_date.year == 2026
    assert ficha.document_date.month == 3
    assert ficha.document_date.day == 31


async def test_extractor_null_document_date(mock_llm_client):
    from scraper.agents.extractor import extract_with_claude

    extractor_output = json.dumps({
        "source_type": "html",
        "source_confidence": 0.7,
        "raw_text": "no date here",
        "tables": [],
        "attributes": {},
        "citations": [],
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(extractor_output)

    ficha = await extract_with_claude(
        llm=mock_llm_client,
        source_url="https://test.com",
        source_type="html",
        raw_text="no date here",
        tables=[],
    )
    assert ficha.document_date is None
