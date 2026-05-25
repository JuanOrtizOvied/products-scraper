from datetime import UTC, datetime


async def test_cache_roundtrip(seeded_and_split_session):
    from scraper.agents.types import AttributeExtraction, ExtractedFicha
    from scraper.search.cache import get_cached, put_cached

    ficha = ExtractedFicha(
        source_url="https://x/y",
        source_type="websearch",
        source_confidence=0.8,
        fetched_at=datetime.now(tz=UTC),
        raw_text="hi",
        tables=[],
        attributes={
            "nombre": AttributeExtraction(value="T", confidence=1.0, reasoning="", raw_quote="")
        },
        citations=["https://x/y"],
        extraction_cost_usd=0.01,
        extraction_duration_ms=100,
    )

    await put_cached(seeded_and_split_session, "Producto Test", "websearch", [ficha])
    got = await get_cached(seeded_and_split_session, "Producto Test", "websearch")
    assert got is not None
    assert len(got) == 1
    assert got[0].attributes["nombre"].value == "T"


async def test_cache_miss_returns_none(seeded_and_split_session):
    from scraper.search.cache import get_cached

    got = await get_cached(seeded_and_split_session, "Nada", "websearch")
    assert got is None


async def test_cache_respects_ttl(seeded_and_split_session):
    from datetime import timedelta

    from sqlalchemy import select

    from scraper.agents.types import AttributeExtraction, ExtractedFicha
    from scraper.db.models import SearchCache
    from scraper.search.cache import get_cached, put_cached

    old_ficha = ExtractedFicha(
        source_url="https://x",
        source_type="websearch",
        source_confidence=0.8,
        fetched_at=datetime.now(tz=UTC),
        raw_text="",
        tables=[],
        attributes={
            "nombre": AttributeExtraction(value="Z", confidence=1.0, reasoning="", raw_quote="")
        },
        citations=[],
        extraction_cost_usd=0.0,
        extraction_duration_ms=0,
    )
    await put_cached(seeded_and_split_session, "Zeta", "websearch", [old_ficha])

    # Age the row beyond TTL
    r = await seeded_and_split_session.execute(
        select(SearchCache).where(SearchCache.query_text == "Zeta")
    )
    row = r.scalar_one()
    row.fetched_at = datetime.now(tz=UTC) - timedelta(days=60)
    await seeded_and_split_session.commit()

    got = await get_cached(seeded_and_split_session, "Zeta", "websearch")
    assert got is None  # expired (TTL for websearch = 30d)
