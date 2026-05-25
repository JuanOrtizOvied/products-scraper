"""End-to-end pipeline test: cascade → extract → classify → review → save."""
from datetime import UTC, datetime


async def test_pipeline_n0_db_hit_short_circuits(seeded_and_split_session, mock_llm_client):
    """A name that exists in DB should be classified without any LLM search calls."""
    from sqlalchemy import select

    from scraper.db.models import Product
    from scraper.search.cascade import run_cascade

    # Pick a product that exists in the seeded DB
    r = await seeded_and_split_session.execute(select(Product).limit(1))
    existing = r.scalar_one()

    result = await run_cascade(
        nombre=existing.nombre, session=seeded_and_split_session, llm=mock_llm_client
    )
    assert result.level == 0
    assert len(result.fichas) == 1
    assert result.fichas[0].source_type == "db"


async def test_pipeline_n1_to_n2_when_n1_low_confidence(mock_llm_client, monkeypatch):
    """If N1 returns low confidence, cascade escalates to N2."""
    from scraper.agents.types import AttributeExtraction, ExtractedFicha
    from scraper.search import cascade as cascade_mod

    async def no_db(nombre, session):
        return None

    async def low_n1(nombre, llm):
        return [
            ExtractedFicha(
                source_url="https://low.example",
                source_type="html",
                source_confidence=0.60,  # below 0.85 threshold
                fetched_at=datetime.now(tz=UTC),
                raw_text="",
                tables=[],
                attributes={
                    "nombre": AttributeExtraction(
                        value="x", confidence=0.6, reasoning="", raw_quote=""
                    )
                },
                citations=[],
                extraction_cost_usd=0.0,
                extraction_duration_ms=0,
            )
        ]

    async def good_n2(nombre, llm):
        return [
            ExtractedFicha(
                source_url="https://good.example",
                source_type="websearch",
                source_confidence=0.80,
                fetched_at=datetime.now(tz=UTC),
                raw_text="",
                tables=[],
                attributes={
                    "nombre": AttributeExtraction(
                        value="x", confidence=0.8, reasoning="", raw_quote=""
                    )
                },
                citations=["https://good.example"],
                extraction_cost_usd=0.1,
                extraction_duration_ms=500,
            )
        ]

    async def no_n3(nombre, llm):
        raise AssertionError("should not reach N3 — N2 was high enough")

    monkeypatch.setattr(cascade_mod, "lookup_db", no_db)
    monkeypatch.setattr(cascade_mod, "run_n1_parsers", low_n1)
    monkeypatch.setattr(cascade_mod, "run_claude_websearch", good_n2)
    monkeypatch.setattr(cascade_mod, "run_claude_intensive", no_n3)

    result = await cascade_mod.run_cascade(nombre="new product", session=None, llm=mock_llm_client)
    assert result.level == 2
    # Combined N1 + N2 — should have both
    assert len(result.fichas) == 2


async def test_pipeline_n3_kill_switch_short_circuits(mock_llm_client, monkeypatch):
    """When all levels fall through and kill switch is on, return low_quality."""
    from scraper.search import cascade as cascade_mod

    async def no_db(nombre, session):
        return None

    async def empty_list(nombre, llm):
        return []

    async def no_n3(nombre, llm):
        raise AssertionError("kill switch should prevent N3")

    monkeypatch.setattr(cascade_mod, "lookup_db", no_db)
    monkeypatch.setattr(cascade_mod, "run_n1_parsers", empty_list)
    monkeypatch.setattr(cascade_mod, "run_claude_websearch", empty_list)
    monkeypatch.setattr(cascade_mod, "run_claude_intensive", no_n3)

    # Ensure kill switch is on (default=True)
    from scraper.config import get_settings
    assert get_settings().skip_intensive_search is True

    result = await cascade_mod.run_cascade(
        nombre="very obscure", session=None, llm=mock_llm_client
    )
    assert result.low_quality is True
    assert result.level == 2
