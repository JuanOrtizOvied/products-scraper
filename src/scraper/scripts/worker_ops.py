"""Database operations for the worker."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.db.models import JobQueue

_STALE_IN_PROGRESS_MIN = 30


async def claim_pending_jobs(session: AsyncSession, limit: int) -> list[JobQueue]:
    """Mark up to `limit` pending jobs as in_progress and return them.

    Also resets any jobs stuck in 'in_progress' for more than 30 minutes
    back to 'pending' (assumed crashed worker).
    """
    now = datetime.now(tz=UTC)

    stale_threshold = datetime.now(tz=UTC).timestamp() - _STALE_IN_PROGRESS_MIN * 60
    r = await session.execute(
        select(JobQueue).where(JobQueue.status == "in_progress")
    )
    for stale in r.scalars().all():
        if stale.started_at and stale.started_at.timestamp() < stale_threshold:
            stale.status = "pending"
            stale.started_at = None

    r = await session.execute(
        select(JobQueue)
        .where(JobQueue.status == "pending")
        .order_by(JobQueue.created_at)
        .limit(limit)
    )
    jobs = list(r.scalars().all())
    for job in jobs:
        job.status = "in_progress"
        job.started_at = now
    await session.commit()
    return jobs


async def mark_job_done(
    session: AsyncSession, job_id: int, classification_id: int | None
) -> None:
    await session.execute(
        update(JobQueue)
        .where(JobQueue.id == job_id)
        .values(
            status="done",
            classification_id=classification_id,
            completed_at=datetime.now(tz=UTC),
        )
    )
    await session.commit()


async def mark_job_failed(session: AsyncSession, job_id: int, error: str) -> None:
    await session.execute(
        update(JobQueue)
        .where(JobQueue.id == job_id)
        .values(
            status="failed",
            error=error[:2000],
            completed_at=datetime.now(tz=UTC),
        )
    )
    await session.commit()
