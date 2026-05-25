from datetime import UTC, datetime


async def test_process_job_via_url_saves_classification(
    seeded_and_split_session, mock_llm_client, monkeypatch
):
    from sqlalchemy import select

    from scraper.agents.types import (
        AttributeClassification,
        AttributeExtraction,
        ClassificationResult,
        ExtractedFicha,
    )
    from scraper.db.models import Classification, JobQueue
    from scraper.scripts.worker_pipeline import process_job_via_url

    job = JobQueue(
        nombre="Test Product",
        url="https://example.com/fondo",
        status="in_progress",
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(job)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(job)

    async def fake_extract_url(*, url, llm, follow_pdfs=True, nombre=None):
        return [
            ExtractedFicha(
                source_url="https://example.com/fondo",
                source_type="html",
                source_confidence=0.9,
                fetched_at=datetime.now(tz=UTC),
                raw_text="html content",
                tables=[],
                attributes={
                    "nombre": AttributeExtraction(
                        value="Test Product", confidence=1.0, reasoning="", raw_quote=""
                    )
                },
                citations=["https://example.com/fondo"],
                extraction_cost_usd=0.04,
                extraction_duration_ms=800,
            )
        ]

    fake_cls_result = ClassificationResult(
        producto="Test Product",
        attributes={
            "nombre": AttributeClassification(
                value="Test Product", confidence=1.0, reasoning="", rule_applied=""
            ),
        },
        global_confidence=0.85,
        unknowns=[],
    )

    async def fake_classify(**kwargs):
        return fake_cls_result

    async def fake_review(**kwargs):
        class _RV:
            veredicto = "agree"
            global_verdict = "auto_approvable"
            reviewer_confidence = 0.88
            attribute_reviews = {}

            def has_disagreement(self):
                return False

        return _RV()

    monkeypatch.setattr("scraper.scripts.worker_pipeline.extract_from_url", fake_extract_url)
    monkeypatch.setattr("scraper.scripts.worker_pipeline.classify", fake_classify)
    monkeypatch.setattr("scraper.scripts.worker_pipeline.review", fake_review)

    cls_id = await process_job_via_url(
        session=seeded_and_split_session,
        job=job,
        llm=mock_llm_client,
        rules_md="# rules",
    )

    r = await seeded_and_split_session.execute(
        select(Classification).where(Classification.id == cls_id)
    )
    cls = r.scalar_one()
    assert cls.source_used == "direct_url"
