from collections import Counter

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def seeded_session(excel_path):
    from scraper.db import models  # noqa: F401
    from scraper.db.base import Base
    from scraper.scripts.seed_from_excel import seed_products

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_local = async_sessionmaker(engine, expire_on_commit=False)
    async with session_local() as s:
        await seed_products(s, excel_path)
        yield s
    await engine.dispose()


def test_dominant_class_picks_highest_percentage():
    from scraper.scripts.split_train_validation import dominant_macro_class
    assert (
        dominant_macro_class(
            {
                "Mercados publicos variable": 62.44,
                "Mercados publicos fijo": 21.78,
                "Efectivo": 15.06,
            }
        )
        == "Mercados publicos variable"
    )


def test_dominant_class_returns_none_for_empty():
    from scraper.scripts.split_train_validation import dominant_macro_class
    assert dominant_macro_class({}) is None


async def test_split_excludes_incomplete_products(seeded_session):
    from scraper.db.models import Product, TrainingSet, ValidationSet
    from scraper.scripts.split_train_validation import run_split

    await run_split(seeded_session, validation_ratio=0.2, seed=42)

    r = await seeded_session.execute(select(Product).where(Product.status == "incomplete"))
    incomplete_ids = {p.id for p in r.scalars().all()}

    r = await seeded_session.execute(select(TrainingSet.product_id))
    training_ids = {row[0] for row in r.all()}

    r = await seeded_session.execute(select(ValidationSet.product_id))
    validation_ids = {row[0] for row in r.all()}

    assert training_ids.isdisjoint(incomplete_ids)
    assert validation_ids.isdisjoint(incomplete_ids)
    assert training_ids.isdisjoint(validation_ids)


async def test_split_ratio_approximately_80_20(seeded_session):
    from scraper.scripts.split_train_validation import run_split

    train_count, val_count = await run_split(seeded_session, validation_ratio=0.2, seed=42)
    total = train_count + val_count
    ratio = val_count / total
    assert 0.15 <= ratio <= 0.25, f"Validation ratio {ratio:.2%} outside 15-25%"


async def test_split_stratified_covers_multiple_macro_classes(seeded_session):
    from scraper.db.models import Product, ValidationSet
    from scraper.scripts.split_train_validation import dominant_macro_class, run_split

    await run_split(seeded_session, validation_ratio=0.2, seed=42)

    r = await seeded_session.execute(
        select(Product).join(ValidationSet, Product.id == ValidationSet.product_id)
    )
    val_products = list(r.scalars().all())

    macro_counts = Counter(
        dominant_macro_class(p.clase_activo) for p in val_products if p.clase_activo
    )
    # At least 4 different macro classes should be represented in validation
    assert len(macro_counts) >= 4, (
        f"Only {len(macro_counts)} macro classes in validation: {macro_counts}"
    )


async def test_split_is_db_idempotent_without_manual_cleanup(seeded_session):
    """Calling run_split twice in a row must not crash — second call returns existing counts."""
    from scraper.scripts.split_train_validation import run_split

    t1, v1 = await run_split(seeded_session, validation_ratio=0.2, seed=42)
    t2, v2 = await run_split(seeded_session, validation_ratio=0.2, seed=42)
    assert (t1, v1) == (t2, v2)
    assert t1 > 0 and v1 > 0


async def test_split_is_idempotent_with_same_seed(seeded_session):
    from scraper.db.models import TrainingSet, ValidationSet
    from scraper.scripts.split_train_validation import run_split

    await run_split(seeded_session, validation_ratio=0.2, seed=42)
    r1 = await seeded_session.execute(select(ValidationSet.product_id))
    first_val_ids = sorted([row[0] for row in r1.all()])

    await seeded_session.execute(TrainingSet.__table__.delete())
    await seeded_session.execute(ValidationSet.__table__.delete())
    await seeded_session.commit()

    await run_split(seeded_session, validation_ratio=0.2, seed=42)
    r2 = await seeded_session.execute(select(ValidationSet.product_id))
    second_val_ids = sorted([row[0] for row in r2.all()])

    assert first_val_ids == second_val_ids
