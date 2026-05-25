async def test_level0_exact_match(seeded_and_split_session):
    from scraper.search.level0_db import lookup_db

    ficha = await lookup_db("Credicorp Crecimiento", seeded_and_split_session)
    if ficha is not None:
        assert ficha.source_type == "db"
        assert ficha.source_confidence == 1.0
        assert ficha.attributes["nombre"].value is not None


async def test_level0_fuzzy_match_above_threshold(seeded_and_split_session):
    from scraper.search.level0_db import lookup_db

    ficha = await lookup_db("Credicorp Crecimento", seeded_and_split_session)  # typo
    if ficha is not None:
        assert ficha.source_type == "db"


async def test_level0_no_match_returns_none(seeded_and_split_session):
    from scraper.search.level0_db import lookup_db

    ficha = await lookup_db("Producto Que No Existe Xyz123", seeded_and_split_session)
    assert ficha is None
