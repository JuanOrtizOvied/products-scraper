from datetime import UTC, datetime


async def test_job_queue_can_be_inserted_and_queried(seeded_and_split_session):
    from sqlalchemy import select

    from scraper.db.models import JobQueue

    row = JobQueue(
        batch_id="batch-uuid-1",
        nombre="Test Product",
        pdf_path=None,
        url=None,
        status="pending",
        classification_id=None,
        error=None,
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(row)
    await seeded_and_split_session.commit()

    r = await seeded_and_split_session.execute(
        select(JobQueue).where(JobQueue.nombre == "Test Product")
    )
    fetched = r.scalar_one()
    assert fetched.status == "pending"
    assert fetched.batch_id == "batch-uuid-1"
    assert fetched.classification_id is None


async def test_job_queue_status_transitions(seeded_and_split_session):
    from sqlalchemy import select

    from scraper.db.models import JobQueue

    row = JobQueue(nombre="X", status="pending", created_at=datetime.now(tz=UTC))
    seeded_and_split_session.add(row)
    await seeded_and_split_session.commit()

    # Transition: pending → in_progress
    row.status = "in_progress"
    row.started_at = datetime.now(tz=UTC)
    await seeded_and_split_session.commit()

    r = await seeded_and_split_session.execute(
        select(JobQueue).where(JobQueue.nombre == "X")
    )
    fetched = r.scalar_one()
    assert fetched.status == "in_progress"
    assert fetched.started_at is not None
