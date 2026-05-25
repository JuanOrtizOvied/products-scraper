from datetime import UTC, datetime


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
        fetched_at=datetime(2026, 4, 18, 12, 0, tzinfo=UTC),
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
        fetched_at=datetime(2026, 4, 18, tzinfo=UTC),
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
