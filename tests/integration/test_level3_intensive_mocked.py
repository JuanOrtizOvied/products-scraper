import json


async def test_intensive_returns_ficha(mock_llm_client):
    from scraper.search.level3_intensive import run_claude_intensive

    output = json.dumps({
        "source_type": "websearch",
        "source_confidence": 0.72,
        "raw_text": "dug deep",
        "tables": [],
        "attributes": {
            "nombre": {
                "value": "Obscuro Fondo",
                "confidence": 0.75,
                "reasoning": "found after 8 searches",
                "raw_quote": "",
            }
        },
        "citations": ["https://obscuro.example/ficha"],
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(output)

    fichas = await run_claude_intensive("Obscuro Fondo", mock_llm_client)
    assert len(fichas) == 1
    assert fichas[0].source_type == "websearch"
    assert fichas[0].attributes["nombre"].value == "Obscuro Fondo"
