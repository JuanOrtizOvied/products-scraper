from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def _write_text_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica", 14)
    c.drawString(72, 740, "Ficha Técnica - Fondo Ejemplo")
    c.setFont("Helvetica", 10)
    c.drawString(72, 710, "Administrador: Ejemplo Capital SAF")
    c.drawString(72, 690, "Moneda: Soles (PEN)")
    c.drawString(72, 670, "Comisión: 2.50% anual")
    c.drawString(72, 650, "Clase: Mercados Públicos - Fijo")
    c.drawString(72, 630, "Descripción: Este fondo invierte en instrumentos de renta fija")
    c.drawString(72, 610, "emitidos por entidades peruanas con calificación AA o superior.")
    c.drawString(72, 590, "Plazo objetivo: entre 2 y 5 años. Riesgo: moderado-bajo.")
    c.drawString(72, 570, "Patrimonio administrado: S/ 150 millones.")
    c.drawString(72, 550, "Suscripción mínima: S/ 1,000. Rescate: T+2 días hábiles.")
    c.drawString(72, 530, "Benchmark: 80% Indice Renta Fija PEN + 20% depósitos a plazo.")
    c.showPage()
    c.save()


def _write_empty_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    c.showPage()
    c.save()


def test_extract_pdf_text_happy_path(tmp_path):
    from scraper.extract.pdf import extract_pdf_text

    pdf = tmp_path / "ficha.pdf"
    _write_text_pdf(pdf)

    text, tables = extract_pdf_text(pdf)
    assert "Ejemplo Capital SAF" in text
    assert "Moneda" in text or "Comisión" in text


def test_extract_pdf_text_detects_empty(tmp_path):
    from scraper.extract.pdf import extract_pdf_text, looks_scanned

    pdf = tmp_path / "empty.pdf"
    _write_empty_pdf(pdf)

    text, _ = extract_pdf_text(pdf)
    assert looks_scanned(text) is True


async def test_extract_from_pdf_uses_text_mode(tmp_path, monkeypatch, mock_llm_client):
    from scraper.extract import pdf as pdf_mod

    pdf_path = tmp_path / "ficha.pdf"
    _write_text_pdf(pdf_path)

    seen_args: dict = {}

    async def fake_extract(**kwargs):
        from datetime import UTC, datetime

        from scraper.agents.types import AttributeExtraction, ExtractedFicha
        seen_args.update(kwargs)
        return ExtractedFicha(
            source_url=None,
            source_type=kwargs["source_type"],
            source_confidence=0.9,
            fetched_at=datetime.now(tz=UTC),
            raw_text=kwargs["raw_text"],
            tables=kwargs["tables"],
            attributes={
                "nombre": AttributeExtraction(value="F", confidence=1.0, reasoning="", raw_quote="")
            },
            citations=[],
            extraction_cost_usd=0.0,
            extraction_duration_ms=0,
        )

    monkeypatch.setattr(pdf_mod, "extract_with_claude", fake_extract)

    ficha = await pdf_mod.extract_from_pdf(path=pdf_path, llm=mock_llm_client)
    assert ficha.source_type == "pdf_text"
    assert seen_args["source_type"] == "pdf_text"
