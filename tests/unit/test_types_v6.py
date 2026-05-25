"""Tests for v6 source traceability type extensions."""
from datetime import datetime, UTC
from scraper.agents.types import (
    AttributeClassification,
    ClassificationResult,
    ConflictEntry,
    ExtractedFicha,
    FieldConflict,
    MergeResult,
    SourceSummary,
    AttributeExtraction,
)


def test_attribute_classification_with_source_fields():
    ac = AttributeClassification(
        value=0.015,
        confidence=0.92,
        reasoning="Ficha dice 1.50%",
        rule_applied="comision-annual-fee",
        source_url="https://bbva.pe/ficha.pdf",
        source_label="Ficha BBVA (Mar 2026)",
        raw_quote="Comisión de administración: 1.50% anual",
    )
    assert ac.source_url == "https://bbva.pe/ficha.pdf"
    assert ac.source_label == "Ficha BBVA (Mar 2026)"
    assert ac.raw_quote == "Comisión de administración: 1.50% anual"


def test_attribute_classification_defaults_none():
    ac = AttributeClassification(
        value="soles", confidence=1.0, reasoning="PEN", rule_applied="moneda"
    )
    assert ac.source_url is None
    assert ac.source_label is None
    assert ac.raw_quote is None


def test_classification_result_roundtrip_with_sources():
    ac = AttributeClassification(
        value="soles", confidence=1.0, reasoning="r", rule_applied="x",
        source_url="https://a.com", source_label="A", raw_quote="PEN",
    )
    cr = ClassificationResult(
        producto="Test", attributes={"moneda": ac}, global_confidence=0.9
    )
    json_str = cr.to_json()
    restored = ClassificationResult.from_json(json_str)
    assert restored.attributes["moneda"].source_url == "https://a.com"
    assert restored.attributes["moneda"].raw_quote == "PEN"


def test_extracted_ficha_document_date():
    ficha = ExtractedFicha(
        source_url="https://x.com",
        source_type="html",
        source_confidence=0.8,
        fetched_at=datetime.now(tz=UTC),
        document_date=datetime(2026, 3, 31, tzinfo=UTC),
        raw_text="test",
        tables=[],
        attributes={},
        citations=[],
        extraction_cost_usd=0.0,
        extraction_duration_ms=100,
    )
    assert ficha.document_date == datetime(2026, 3, 31, tzinfo=UTC)


def test_extracted_ficha_document_date_default_none():
    ficha = ExtractedFicha(
        source_url=None,
        source_type="pdf_text",
        source_confidence=0.5,
        fetched_at=datetime.now(tz=UTC),
        raw_text="t",
        tables=[],
        attributes={},
        citations=[],
        extraction_cost_usd=0.0,
        extraction_duration_ms=0,
    )
    assert ficha.document_date is None


def test_extracted_ficha_json_roundtrip_with_document_date():
    dt = datetime(2026, 3, 15, tzinfo=UTC)
    ficha = ExtractedFicha(
        source_url="https://x.com", source_type="html",
        source_confidence=0.9, fetched_at=datetime.now(tz=UTC),
        document_date=dt, raw_text="t", tables=[], attributes={},
        citations=[], extraction_cost_usd=0.0, extraction_duration_ms=0,
    )
    payload = ficha.to_json()
    assert payload["document_date"] == dt.isoformat()
    restored = ExtractedFicha.from_json(payload)
    assert restored.document_date == dt


def test_conflict_entry_creation():
    ce = ConflictEntry(
        value=0.015, source_url="https://a.com",
        source_label="Ficha A", document_date=None,
        raw_quote="1.50% anual",
    )
    assert ce.value == 0.015
    assert ce.source_label == "Ficha A"


def test_field_conflict_creation():
    alt = ConflictEntry(
        value=0.0175, source_url="https://b.com",
        source_label="Web B", document_date=None,
        raw_quote="1.75%",
    )
    fc = FieldConflict(
        attribute="comision",
        chosen_value=0.015,
        chosen_source="https://a.com",
        alternatives=[alt],
    )
    assert fc.attribute == "comision"
    assert len(fc.alternatives) == 1
    assert fc.alternatives[0].value == 0.0175


def test_source_summary_creation():
    ss = SourceSummary(
        url="https://x.com", label="Ficha X",
        document_date=datetime(2026, 3, 1, tzinfo=UTC),
        source_type="pdf_text",
    )
    assert ss.url == "https://x.com"
    assert ss.source_type == "pdf_text"
