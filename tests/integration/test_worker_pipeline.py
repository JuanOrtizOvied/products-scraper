from datetime import UTC, datetime


async def test_process_job_cascade_saves_classification_and_review_entry(
    seeded_and_split_session, mock_llm_client, monkeypatch
):
    from sqlalchemy import select

    from scraper.agents.types import AttributeClassification, ClassificationResult
    from scraper.db.models import Classification, JobQueue, ReviewQueue
    from scraper.scripts.worker_pipeline import process_job_via_cascade

    job = JobQueue(nombre="Test Product", status="in_progress", created_at=datetime.now(tz=UTC))
    seeded_and_split_session.add(job)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(job)

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

    async def fake_run(nombre, rules_md, llm, session):
        return fake_cls_result, {
            "veredicto": "agree",
            "global_verdict": "auto_approvable",
            "reviewer_confidence": 0.9,
        }, "auto_approvable", "cascade_level_0", 0.12, 1500, [nombre], [{"url": "http://example.com", "label": "test", "document_date": None, "source_type": "html"}], None

    monkeypatch.setattr(
        "scraper.scripts.worker_pipeline._run_cascade_classify_review", fake_run
    )

    await process_job_via_cascade(
        session=seeded_and_split_session,
        job=job,
        llm=mock_llm_client,
        rules_md="# rules",
    )

    r = await seeded_and_split_session.execute(
        select(Classification).where(Classification.product_name_input == "Test Product")
    )
    cls = r.scalar_one()
    assert cls.global_confidence == 0.85
    assert cls.final_status == "auto_approvable"

    r = await seeded_and_split_session.execute(
        select(ReviewQueue).where(ReviewQueue.classification_id == cls.id)
    )
    review = r.scalar_one()
    assert review.flag == "auto_approvable"
