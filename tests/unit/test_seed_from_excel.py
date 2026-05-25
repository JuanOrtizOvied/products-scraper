import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def session_with_schema():
    from scraper.db import models  # noqa: F401 — register models
    from scraper.db.base import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_local = async_sessionmaker(engine, expire_on_commit=False)
    async with session_local() as s:
        yield s
    await engine.dispose()


async def test_seed_imports_128_unique_products(session_with_schema, excel_path):
    from scraper.db.models import Product
    from scraper.scripts.seed_from_excel import seed_products

    # Excel has 8 duplicate product names (second occurrence is NaN) — seeder dedupes
    # by nombre, giving 128 unique products.
    count = await seed_products(session_with_schema, excel_path)
    assert count == 128

    result = await session_with_schema.execute(select(Product))
    products = list(result.scalars().all())
    assert len(products) == 128


async def test_seed_parses_percentages_into_json(session_with_schema, excel_path):
    from scraper.db.models import Product
    from scraper.scripts.seed_from_excel import seed_products

    await seed_products(session_with_schema, excel_path)
    result = await session_with_schema.execute(
        select(Product).where(Product.nombre == "Credicorp Crecimiento")
    )
    p = result.scalar_one()
    assert p.foco_geografico == pytest.approx(
        {"Perú": 75.0, "Emergentes ex-Perú": 15.0, "Latam ex-Perú": 10.0}
    )
    assert p.source_type == "excel_seed"


async def test_seed_handles_nan_rows_gracefully(session_with_schema, excel_path):
    from scraper.db.models import Product
    from scraper.scripts.seed_from_excel import seed_products

    await seed_products(session_with_schema, excel_path)
    result = await session_with_schema.execute(
        select(Product).where(Product.nombre == "Sabbi Dividendos")
    )
    p = result.scalar_one_or_none()
    assert p is not None
    assert p.foco_geografico == {}
    assert p.status == "incomplete"


async def test_seed_is_idempotent(session_with_schema, excel_path):
    from scraper.scripts.seed_from_excel import seed_products

    count1 = await seed_products(session_with_schema, excel_path)
    count2 = await seed_products(session_with_schema, excel_path)
    assert count1 == 128
    assert count2 == 0
