import json

import pytest


async def test_classify_parses_valid_json_output(mock_llm_client):
    from scraper.agents.classifier import classify

    output_json = json.dumps({
        "producto": "Test Fondo",
        "attributes": {
            "foco_geografico": {
                "value": {"Perú": 100.0},
                "confidence": 0.95,
                "reasoning": "ficha dice Perú",
                "rule_applied": "regla_geografica_explicita",
            },
            "clase_activo": {
                "value": {"Mercados Públicos - Variable": 100.0},
                "confidence": 0.90,
                "reasoning": "acciones Peru",
                "rule_applied": "etf_replica_indice",
            },
        },
        "global_confidence": 0.92,
        "unknowns": [],
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(output_json)

    result = await classify(
        llm=mock_llm_client,
        producto_nombre="Test Fondo",
        product_context={"administrador": "X"},
        rules_md="# rules",
        few_shot_examples=[],
    )
    assert result.producto == "Test Fondo"
    assert result.attributes["foco_geografico"].value == {"Perú": 100.0}
    assert result.global_confidence == 0.92


async def test_classify_strips_markdown_fences(mock_llm_client):
    from scraper.agents.classifier import classify

    fenced = (
        '```json\n'
        '{"producto": "X", "attributes": {}, "global_confidence": 0.5, "unknowns": []}'
        '\n```'
    )
    mock_llm_client.call.return_value = mock_llm_client.make_result(fenced)

    result = await classify(
        llm=mock_llm_client,
        producto_nombre="X",
        product_context={},
        rules_md="# r",
        few_shot_examples=[],
    )
    assert result.producto == "X"


async def test_classify_raises_on_invalid_json(mock_llm_client):
    from scraper.agents.classifier import ClassifierParseError, classify

    mock_llm_client.call.return_value = mock_llm_client.make_result("not json at all")

    with pytest.raises(ClassifierParseError):
        await classify(
            llm=mock_llm_client,
            producto_nombre="X",
            product_context={},
            rules_md="#",
            few_shot_examples=[],
        )


async def test_classify_validates_canonical_vocabulary(mock_llm_client):
    """Si el LLM devuelve un valor no canónico en clase_activo, debe rechazarlo o normalizar."""
    from scraper.agents.classifier import classify

    output = json.dumps({
        "producto": "X",
        "attributes": {
            "clase_activo": {
                "value": {"Club deal": 100.0},  # variante, no canónica
                "confidence": 0.9,
                "reasoning": "...",
                "rule_applied": "...",
            },
        },
        "global_confidence": 0.9,
        "unknowns": [],
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(output)

    result = await classify(
        llm=mock_llm_client,
        producto_nombre="X",
        product_context={},
        rules_md="#",
        few_shot_examples=[],
    )
    # El classifier normaliza: "Club deal" → "Club deals"
    assert "Club deals" in result.attributes["clase_activo"].value


@pytest.mark.asyncio
async def test_classifier_parses_source_fields(mock_llm_client):
    from scraper.agents.classifier import classify

    classifier_output = json.dumps({
        "producto": "Test Fund",
        "attributes": {
            "moneda": {
                "value": "soles",
                "confidence": 1.0,
                "reasoning": "PEN en ficha",
                "rule_applied": "moneda",
                "source_url": "https://test.com/ficha.pdf",
                "source_label": "Ficha Test (Mar 2026)",
                "raw_quote": "Moneda: PEN (Nuevos Soles)",
            }
        },
        "global_confidence": 0.95,
        "unknowns": [],
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(classifier_output)

    result = await classify(
        llm=mock_llm_client,
        producto_nombre="Test Fund",
        product_context={"administrador": None, "gestor": None, "moneda": None, "liquidez": None},
        rules_md="# rules",
        few_shot_examples=[],
    )
    assert result.attributes["moneda"].source_url == "https://test.com/ficha.pdf"
    assert result.attributes["moneda"].source_label == "Ficha Test (Mar 2026)"
    assert result.attributes["moneda"].raw_quote == "Moneda: PEN (Nuevos Soles)"
