from datetime import UTC, datetime


async def test_process_job_via_pdf_saves_classification(
    seeded_and_split_session, mock_llm_client, monkeypatch, tmp_path
):
    from sqlalchemy import select

    from scraper.agents.types import (
        AttributeClassification,
        AttributeExtraction,
        ClassificationResult,
        ExtractedFicha,
    )
    from scraper.db.models import Classification, JobQueue
    from scraper.scripts.worker_pipeline import process_job_via_pdf

    pdf_path = tmp_path / "ficha.pdf"
    pdf_path.write_bytes(b"%PDF-1.5 fake content")

    job = JobQueue(
        nombre="Test Product",
        pdf_path=str(pdf_path),
        status="in_progress",
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(job)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(job)

    async def fake_extract_pdf(*, path, llm, nombre):
        return ExtractedFicha(
            source_url=None,
            source_type="pdf_text",
            source_confidence=0.9,
            fetched_at=datetime.now(tz=UTC),
            raw_text="pdf content",
            tables=[],
            attributes={
                "nombre": AttributeExtraction(
                    value="Test Product", confidence=1.0, reasoning="", raw_quote=""
                )
            },
            citations=[str(pdf_path)],
            extraction_cost_usd=0.03,
            extraction_duration_ms=500,
        )

    fake_cls_result = ClassificationResult(
        producto="Test Product",
        attributes={
            "nombre": AttributeClassification(
                value="Test Product", confidence=1.0, reasoning="", rule_applied=""
            ),
        },
        global_confidence=0.80,
        unknowns=[],
    )

    async def fake_classify(**kwargs):
        return fake_cls_result

    async def fake_review(**kwargs):
        class _RV:
            veredicto = "agree"
            global_verdict = "auto_approvable"
            reviewer_confidence = 0.85
            attribute_reviews = {}

            def has_disagreement(self):
                return False

        return _RV()

    monkeypatch.setattr("scraper.scripts.worker_pipeline.extract_from_pdf", fake_extract_pdf)
    monkeypatch.setattr("scraper.scripts.worker_pipeline.classify", fake_classify)
    monkeypatch.setattr("scraper.scripts.worker_pipeline.review", fake_review)

    cls_id = await process_job_via_pdf(
        session=seeded_and_split_session,
        job=job,
        llm=mock_llm_client,
        rules_md="# rules",
    )

    r = await seeded_and_split_session.execute(
        select(Classification).where(Classification.id == cls_id)
    )
    cls = r.scalar_one()
    assert cls.product_name_input == "Test Product"
    assert cls.source_used == "direct_pdf"
