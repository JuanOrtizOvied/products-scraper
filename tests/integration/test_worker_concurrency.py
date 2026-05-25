import asyncio
from datetime import UTC, datetime


async def test_worker_gather_processes_multiple_jobs(seeded_and_split_session):
    from scraper.db.models import JobQueue
    from scraper.scripts.worker_ops import claim_pending_jobs

    for i in range(3):
        seeded_and_split_session.add(
            JobQueue(nombre=f"P{i}", status="pending", created_at=datetime.now(tz=UTC))
        )
    await seeded_and_split_session.commit()

    claimed = await claim_pending_jobs(seeded_and_split_session, limit=3)

    processed = []
    lock = asyncio.Lock()
    max_concurrent = 0
    current = 0

    async def fake_process(job):
        nonlocal max_concurrent, current
        async with lock:
            current += 1
            max_concurrent = max(max_concurrent, current)
        await asyncio.sleep(0.05)
        async with lock:
            current -= 1
            processed.append(job.nombre)

    tasks = [fake_process(job) for job in claimed]
    await asyncio.gather(*tasks)

    assert len(processed) == 3
    assert max_concurrent >= 2
