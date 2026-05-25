"""Tests for multi-source merge logic."""
from datetime import UTC, datetime

from scraper.agents.types import AttributeExtraction, ExtractedFicha
from scraper.search.merge import merge_fichas


def _make_ficha(url="https://a.com", source_type="html", doc_date=None, fetched_at=None, attrs=None):
    return ExtractedFicha(
        source_url=url, source_type=source_type, source_confidence=0.8,
        fetched_at=fetched_at or datetime.now(tz=UTC),
        raw_text="text", tables=[], attributes=attrs or {},
        citations=[url] if url else [], extraction_cost_usd=0.0,
        extraction_duration_ms=0, document_date=doc_date,
    )


def _attr(value, confidence=0.9, quote=None):
    return AttributeExtraction(value=value, confidence=confidence, reasoning="r", raw_quote=quote)


def test_merge_single_ficha():
    ficha = _make_ficha(attrs={"moneda": _attr("soles")})
    result = merge_fichas([ficha])
    assert result.primary is ficha
    assert len(result.all_sources) == 1
    assert result.conflicts == []


def test_merge_sorts_by_document_date_descending():
    old = _make_ficha(url="https://old.com", doc_date=datetime(2026, 1, 1, tzinfo=UTC))
    new = _make_ficha(url="https://new.com", doc_date=datetime(2026, 3, 1, tzinfo=UTC))
    result = merge_fichas([old, new])
    assert result.primary.source_url == "https://new.com"


def test_merge_null_date_sorted_last():
    dated = _make_ficha(url="https://dated.com", doc_date=datetime(2026, 1, 1, tzinfo=UTC))
    undated = _make_ficha(url="https://undated.com", doc_date=None)
    result = merge_fichas([undated, dated])
    assert result.primary.source_url == "https://dated.com"


def test_merge_fallback_to_fetched_at_when_no_dates():
    old = _make_ficha(url="https://old.com", fetched_at=datetime(2026, 1, 1, tzinfo=UTC))
    new = _make_ficha(url="https://new.com", fetched_at=datetime(2026, 3, 1, tzinfo=UTC))
    result = merge_fichas([old, new])
    assert result.primary.source_url == "https://new.com"


def test_merge_detects_categorical_conflict():
    ficha_a = _make_ficha(url="https://a.com", doc_date=datetime(2026, 3, 1, tzinfo=UTC),
        attrs={"liquidez": _attr("Inmediata", quote="disponibilidad inmediata")})
    ficha_b = _make_ficha(url="https://b.com", doc_date=datetime(2026, 1, 1, tzinfo=UTC),
        attrs={"liquidez": _attr("Corto plazo", quote="rescate T+2")})
    result = merge_fichas([ficha_a, ficha_b])
    assert len(result.conflicts) == 1
    assert result.conflicts[0].attribute == "liquidez"
    assert result.conflicts[0].chosen_value == "Inmediata"
    assert result.conflicts[0].alternatives[0].value == "Corto plazo"


def test_merge_no_conflict_on_same_value():
    ficha_a = _make_ficha(url="https://a.com", doc_date=datetime(2026, 3, 1, tzinfo=UTC),
        attrs={"moneda": _attr("soles")})
    ficha_b = _make_ficha(url="https://b.com", doc_date=datetime(2026, 1, 1, tzinfo=UTC),
        attrs={"moneda": _attr("soles")})
    result = merge_fichas([ficha_a, ficha_b])
    assert result.conflicts == []


def test_merge_dict_conflict_above_5pp():
    ficha_a = _make_ficha(url="https://a.com", doc_date=datetime(2026, 3, 1, tzinfo=UTC),
        attrs={"clase_activo": _attr({"Renta Variable": 70, "Renta Fija": 30})})
    ficha_b = _make_ficha(url="https://b.com", doc_date=datetime(2026, 1, 1, tzinfo=UTC),
        attrs={"clase_activo": _attr({"Renta Variable": 60, "Renta Fija": 40})})
    result = merge_fichas([ficha_a, ficha_b])
    assert len(result.conflicts) == 1
    assert result.conflicts[0].attribute == "clase_activo"


def test_merge_dict_no_conflict_within_5pp():
    ficha_a = _make_ficha(url="https://a.com", doc_date=datetime(2026, 3, 1, tzinfo=UTC),
        attrs={"clase_activo": _attr({"Renta Variable": 70, "Renta Fija": 30})})
    ficha_b = _make_ficha(url="https://b.com", doc_date=datetime(2026, 1, 1, tzinfo=UTC),
        attrs={"clase_activo": _attr({"Renta Variable": 67, "Renta Fija": 33})})
    result = merge_fichas([ficha_a, ficha_b])
    assert result.conflicts == []


def test_merge_format_difference_not_conflict():
    ficha_a = _make_ficha(url="https://a.com", doc_date=datetime(2026, 3, 1, tzinfo=UTC),
        attrs={"comision": _attr(0.015)})
    ficha_b = _make_ficha(url="https://b.com", doc_date=datetime(2026, 1, 1, tzinfo=UTC),
        attrs={"comision": _attr(0.015)})
    result = merge_fichas([ficha_a, ficha_b])
    assert result.conflicts == []


def test_merge_builds_source_summaries():
    ficha_a = _make_ficha(url="https://a.com", source_type="pdf_text", doc_date=datetime(2026, 3, 1, tzinfo=UTC))
    ficha_b = _make_ficha(url="https://b.com", source_type="html", doc_date=datetime(2026, 1, 1, tzinfo=UTC))
    result = merge_fichas([ficha_a, ficha_b])
    assert len(result.all_sources) == 2
    assert result.all_sources[0].source_type == "pdf_text"
    assert result.all_sources[1].source_type == "html"


def test_merge_context_includes_all_sources():
    ficha_a = _make_ficha(url="https://a.com", doc_date=datetime(2026, 3, 1, tzinfo=UTC),
        attrs={"moneda": _attr("soles", quote="Moneda: PEN")})
    ficha_b = _make_ficha(url="https://b.com", doc_date=datetime(2026, 1, 1, tzinfo=UTC),
        attrs={"moneda": _attr("soles", quote="Currency: PEN")})
    result = merge_fichas([ficha_a, ficha_b])
    assert "https://a.com" in result.merged_context
    assert "https://b.com" in result.merged_context
