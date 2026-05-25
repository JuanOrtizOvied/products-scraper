import json
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def _write_empty_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    c.showPage()
    c.save()


async def test_extract_from_pdf_vision_sends_images_to_claude(
    tmp_path, monkeypatch, mock_llm_client
):
    from scraper.extract import vision as vision_mod

    pdf_path = tmp_path / "scan.pdf"
    _write_empty_pdf(pdf_path)

    # Monkeypatch PDF rendering to avoid needing poppler in tests
    fake_png = b"\x89PNG\r\n\x1a\nfake"
    monkeypatch.setattr(vision_mod, "_pdf_pages_to_png_bytes", lambda p: [fake_png])

    # Mock llm response
    output_json = json.dumps({
        "source_type": "pdf_vision",
        "source_confidence": 0.75,
        "raw_text": "",
        "tables": [],
        "attributes": {
            "nombre": {
                "value": "Scanned Fondo",
                "confidence": 0.8,
                "reasoning": "vision",
                "raw_quote": "",
            }
        },
        "citations": [],
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(output_json)

    ficha = await vision_mod.extract_from_pdf_vision(path=pdf_path, llm=mock_llm_client)

    assert ficha.source_type == "pdf_vision"
    assert ficha.attributes["nombre"].value == "Scanned Fondo"
    # Confirm user message contained an image block
    call = mock_llm_client.call.call_args
    msgs = call.kwargs["messages"]
    content = msgs[0]["content"]
    assert isinstance(content, list)
    assert any(block["type"] == "image" for block in content)
