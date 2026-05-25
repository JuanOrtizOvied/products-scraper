import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def session():
    from scraper.db import models  # noqa: F401 — register models on Base.metadata
    from scraper.db.base import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)  # noqa: N806
    async with SessionLocal() as s:
        yield s
    await engine.dispose()


async def test_can_insert_product(session: AsyncSession):
    from scraper.db.models import Product

    p = Product(
        nombre="Test Product",
        foco_geografico={"Perú": 100.0},
        clase_activo={"Club deals": 100.0},
        subyacentes={"Club Deals Real Estate Perú": 100.0},
        comision=0.005,
        moneda="dolares",
        administrador="Test Admin",
        gestor="Test Gestor",
        liquidez="Mediano plazo",
        minimo_inversion="150k dolares",
        source_type="excel_seed",
    )
    session.add(p)
    await session.commit()
    assert p.id is not None
    assert p.created_at is not None


async def test_audit_log_insert(session: AsyncSession):
    from scraper.db.models import AuditLog

    entry = AuditLog(
        event_type="product_approved",
        actor="user:sabbi",
        entity_type="product",
        entity_id="42",
        before_state=None,
        after_state={"status": "active"},
    )
    session.add(entry)
    await session.commit()
    assert entry.id is not None
    assert entry.timestamp is not None


async def test_rules_version_uniqueness(session: AsyncSession):
    from scraper.db.models import RulesVersion

    v1 = RulesVersion(version="v1", content_md="# rules", created_by=None)
    v1_dup = RulesVersion(version="v1", content_md="# dup", created_by=None)
    session.add(v1)
    await session.commit()
    session.add(v1_dup)
    with pytest.raises(Exception, match="UNIQUE constraint failed"):  # noqa: B017
        await session.commit()
