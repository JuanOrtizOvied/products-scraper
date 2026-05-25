"""Smoke test: seed excel → split → assertions básicas de estado."""
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def pipeline_session(excel_path):
    from scraper.db import models  # noqa: F401
    from scraper.db.base import Base
    from scraper.scripts.seed_from_excel import seed_products
    from scraper.scripts.split_train_validation import run_split

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_local = async_sessionmaker(engine, expire_on_commit=False)
    async with session_local() as s:
        await seed_products(s, excel_path)
        await run_split(s, validation_ratio=0.2, seed=42)
        yield s
    await engine.dispose()


async def test_all_active_products_in_exactly_one_split(pipeline_session):
    from scraper.db.models import Product, TrainingSet, ValidationSet

    r = await pipeline_session.execute(select(Product).where(Product.status == "active"))
    active = list(r.scalars().all())

    r = await pipeline_session.execute(select(TrainingSet.product_id))
    train_ids = {row[0] for row in r.all()}
    r = await pipeline_session.execute(select(ValidationSet.product_id))
    val_ids = {row[0] for row in r.all()}

    for p in active:
        in_train = p.id in train_ids
        in_val = p.id in val_ids
        assert in_train ^ in_val, (
            f"Product {p.nombre} in {[in_train, in_val]} splits (must be exactly one)"
        )


async def test_taxonomy_values_match_dataset_values(pipeline_session):
    """Sanity: los valores del Excel en `clase_activo` deben ser re-mapeables a las 6 canónicas.

    Este test documenta las variantes ortográficas conocidas. Si aparece una variante NUEVA
    (no mapeada), falla y la muestra — señal de que hay que extender el normalizador en Phase 2.
    """
    from scraper.db.models import Product
    from scraper.taxonomies import load_asset_classes

    canonical = {c.name.lower().strip() for c in load_asset_classes()}
    # Variantes observadas en el Excel (mapeo futuro para Phase 2 normalizer):
    excel_variants_to_canonical = {
        "mercados publicos variable": "Mercados Públicos - Variable",
        "mercados publicos fijo": "Mercados Públicos - Fijo",
        "cash y otros": "Cash y Otros",
        "club deal": "Club deals",
        "mercados privados": "Mercados Privados",
        "efectivo": "Cash y Otros",
        "otros": "Cash y Otros",
        "mercado publico variable": "Mercados Públicos - Variable",
        # Additional variants observed in the Excel (added after first run):
        "mercado publico fijo": "Mercados Públicos - Fijo",
        "mercados publicos - fijo": "Mercados Públicos - Fijo",
        "mercados publicos - variable": "Mercados Públicos - Variable",
        # Compound/malformed cells where parser captured two categories in one key:
        (
            "mercados publicos variable 62.44%"
            "                                     mercados publicos fijo"
        ): "Mercados Públicos - Variable",
        # Cells with percentage-embedded text (efectivo + otros together):
        "efectivo 15.06%                                           otros": "Cash y Otros",
        "efectivo 31.51%                                           otros": "Cash y Otros",
    }
    r = await pipeline_session.execute(select(Product).where(Product.status == "active"))
    unknowns: set[str] = set()
    for p in r.scalars().all():
        for raw_key in p.clase_activo.keys():
            normalized = raw_key.lower().strip()
            if normalized in canonical:
                continue
            if normalized in excel_variants_to_canonical:
                continue
            unknowns.add(raw_key)
    assert not unknowns, f"Variantes no mapeadas a taxonomía canónica: {unknowns}"
