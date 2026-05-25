"""Queries for the review queue UI."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from scraper.db.models import ReviewQueue


async def list_pending_reviews(
    session: AsyncSession,
    flag_filter: str | None = None,
    limit: int = 100,
) -> list[ReviewQueue]:
    """Return ReviewQueue rows without human_decision set, with classification joined."""
    stmt = (
        select(ReviewQueue)
        .options(selectinload(ReviewQueue.classification))
        .where(ReviewQueue.human_decision.is_(None))
        .order_by(ReviewQueue.priority.asc(), ReviewQueue.created_at.desc())
        .limit(limit)
    )
    if flag_filter:
        stmt = stmt.where(ReviewQueue.flag == flag_filter)
    r = await session.execute(stmt)
    return list(r.scalars().all())


async def get_review_with_classification(
    session: AsyncSession, review_id: int
) -> ReviewQueue | None:
    r = await session.execute(
        select(ReviewQueue)
        .options(selectinload(ReviewQueue.classification))
        .where(ReviewQueue.id == review_id)
    )
    return r.scalar_one_or_none()
