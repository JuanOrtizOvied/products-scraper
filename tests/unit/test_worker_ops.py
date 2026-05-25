from datetime import UTC, datetime


async def test_claim_pending_jobs_marks_in_progress(seeded_and_split_session):
    from scraper.db.models import JobQueue
    from scraper.scripts.worker_ops import claim_pending_jobs

    for i in range(3):
        seeded_and_split_session.add(
            JobQueue(nombre=f"Product {i}", status="pending", created_at=datetime.now(tz=UTC))
        )
    await seeded_and_split_session.commit()

    claimed = await claim_pending_jobs(seeded_and_split_session, limit=2)
    assert len(claimed) == 2
    for job in claimed:
        assert job.status == "in_progress"
        assert job.started_at is not None


async def test_claim_pending_jobs_returns_empty_when_no_pending(seeded_and_split_session):
    from scraper.scripts.worker_ops import claim_pending_jobs

    claimed = await claim_pending_jobs(seeded_and_split_session, limit=5)
    assert claimed == []


async def test_mark_job_done_sets_completed_and_classification_id(seeded_and_split_session):
    from sqlalchemy import select

    from scraper.db.models import JobQueue
    from scraper.scripts.worker_ops import mark_job_done

    job = JobQueue(nombre="X", status="in_progress", created_at=datetime.now(tz=UTC))
    seeded_and_split_session.add(job)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(job)

    await mark_job_done(seeded_and_split_session, job.id, classification_id=42)

    r = await seeded_and_split_session.execute(
        select(JobQueue).where(JobQueue.id == job.id)
    )
    updated = r.scalar_one()
    assert updated.status == "done"
    assert updated.classification_id == 42
    assert updated.completed_at is not None


async def test_mark_job_failed_records_error(seeded_and_split_session):
    from sqlalchemy import select

    from scraper.db.models import JobQueue
    from scraper.scripts.worker_ops import mark_job_failed

    job = JobQueue(nombre="X", status="in_progress", created_at=datetime.now(tz=UTC))
    seeded_and_split_session.add(job)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(job)

    await mark_job_failed(seeded_and_split_session, job.id, error="network timeout")

    r = await seeded_and_split_session.execute(
        select(JobQueue).where(JobQueue.id == job.id)
    )
    updated = r.scalar_one()
    assert updated.status == "failed"
    assert updated.error == "network timeout"
