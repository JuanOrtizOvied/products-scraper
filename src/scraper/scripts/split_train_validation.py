"""Stratified 80/20 split of products into training / validation.

Stratified by dominant macro class to ensure each class is represented in both sets.
Excludes products with status='incomplete'.
"""
from __future__ import annotations

import asyncio
import random
from collections import defaultdict

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.db.models import Product, TrainingSet, ValidationSet
from scraper.db.session import get_session

log = structlog.get_logger()


def dominant_macro_class(clase_activo: dict[str, float]) -> str | None:
    """Return the class with highest percentage. None if dict is empty."""
    if not clase_activo:
        return None
    return max(clase_activo.items(), key=lambda kv: kv[1])[0]


async def run_split(
    session: AsyncSession,
    validation_ratio: float = 0.2,
    seed: int = 42,
) -> tuple[int, int]:
    """Populate training_set and validation_set tables.

    Returns (training_count, validation_count).
    """
    # Idempotency: if split already exists, return existing counts instead of re-inserting
    existing = await session.execute(select(TrainingSet).limit(1))
    if existing.scalar_one_or_none() is not None:
        r_train = await session.execute(select(func.count()).select_from(TrainingSet))
        r_val = await session.execute(select(func.count()).select_from(ValidationSet))
        log.info("split_already_exists_skipping")
        return r_train.scalar_one(), r_val.scalar_one()

    r = await session.execute(select(Product).where(Product.status == "active"))
    products = list(r.scalars().all())

    by_class: dict[str, list[Product]] = defaultdict(list)
    for p in products:
        key = dominant_macro_class(p.clase_activo) or "__unknown__"
        by_class[key].append(p)

    rng = random.Random(seed)
    training: list[int] = []
    validation: list[int] = []
    for macro_class, group in sorted(by_class.items()):
        group_sorted = sorted(group, key=lambda p: p.id)
        shuffled = group_sorted[:]
        rng.shuffle(shuffled)
        n_val = max(1, round(len(shuffled) * validation_ratio)) if len(shuffled) >= 5 else 0
        val_ids = [p.id for p in shuffled[:n_val]]
        train_ids = [p.id for p in shuffled[n_val:]]
        validation.extend(val_ids)
        training.extend(train_ids)
        log.info(
            "split_bucket",
            macro=macro_class,
            total=len(group),
            train=len(train_ids),
            val=len(val_ids),
        )

    for pid in training:
        session.add(TrainingSet(product_id=pid))
    for pid in validation:
        session.add(ValidationSet(product_id=pid))
    await session.commit()
    log.info("split_done", training=len(training), validation=len(validation))
    return len(training), len(validation)


async def _main() -> None:
    async with get_session() as s:
        t, v = await run_split(s)
        print(f"Training: {t} | Validation: {v}")


if __name__ == "__main__":
    asyncio.run(_main())
