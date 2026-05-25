import json


async def test_intensive_rejects_ficha_without_citations(mock_llm_client):
    """A ficha with no web citations is discarded (pure training-data guess)."""
    from scraper.search.level3_intensive import run_claude_intensive

    output = json.dumps(
        {
            "source_type": "websearch",
            "source_confidence": 0.72,
            "raw_text": "model guessing",
            "tables": [],
            "attributes": {
                "nombre": {
                    "value": "Hallucinated Fund",
                    "confidence": 0.75,
                    "reasoning": "I think this exists",
                    "raw_quote": "",
                }
            },
            "citations": [],  # no citations -> reject
        }
    )
    mock_llm_client.call.return_value = mock_llm_client.make_result(output)

    fichas = await run_claude_intensive("Some Obscure Fund", mock_llm_client)
    assert fichas == []


async def test_intensive_accepts_ficha_with_real_citations(mock_llm_client):
    """A ficha with at least one http(s) citation is accepted."""
    from scraper.search.level3_intensive import run_claude_intensive

    output = json.dumps(
        {
            "source_type": "websearch",
            "source_confidence": 0.72,
            "raw_text": "real content",
            "tables": [],
            "attributes": {
                "nombre": {
                    "value": "Real Fund",
                    "confidence": 0.75,
                    "reasoning": "found online",
                    "raw_quote": "",
                }
            },
            "citations": ["https://real-admin.com/fondo/x"],
        }
    )
    mock_llm_client.call.return_value = mock_llm_client.make_result(output)

    fichas = await run_claude_intensive("Real Fund", mock_llm_client)
    assert len(fichas) == 1
    assert fichas[0].citations == ["https://real-admin.com/fondo/x"]


async def test_intensive_filters_non_http_citations(mock_llm_client):
    """Non-URL strings in citations don't count as real sources."""
    from scraper.search.level3_intensive import run_claude_intensive

    output = json.dumps(
        {
            "source_type": "websearch",
            "source_confidence": 0.72,
            "raw_text": "",
            "tables": [],
            "attributes": {
                "nombre": {"value": "X", "confidence": 0.5, "reasoning": "", "raw_quote": ""}
            },
            "citations": ["page 1", "reference document A"],
        }
    )
    mock_llm_client.call.return_value = mock_llm_client.make_result(output)

    fichas = await run_claude_intensive("Whatever", mock_llm_client)
    assert fichas == []  # no http(s) citations
