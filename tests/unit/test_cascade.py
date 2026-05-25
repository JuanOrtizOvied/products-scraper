from datetime import UTC, datetime


def _make_ficha(url: str, conf: float):
    from scraper.agents.types import AttributeExtraction, ExtractedFicha
    attr = AttributeExtraction(value="x", confidence=conf, reasoning="", raw_quote="")
    return ExtractedFicha(
        source_url=url,
        source_type="html",
        source_confidence=conf,
        fetched_at=datetime.now(tz=UTC),
        raw_text="",
        tables=[],
        attributes={"nombre": attr},
        citations=[url],
        extraction_cost_usd=0.0,
        extraction_duration_ms=0,
    )


def test_cascade_result_construction():
    from scraper.search.types import CascadeResult

    f = _make_ficha("https://a", 0.9)
    r = CascadeResult(level=1, fichas=[f], low_quality=False)
    assert r.level == 1
    assert r.fichas[0].source_url == "https://a"
    assert r.best_confidence == 0.9


def test_cascade_result_empty_best_confidence_zero():
    from scraper.search.types import CascadeResult

    r = CascadeResult(level=2, fichas=[], low_quality=True)
    assert r.best_confidence == 0.0


def test_merge_candidates_dedup_by_source_url():
    from scraper.search.cascade import merge_candidates

    a = [_make_ficha("https://a", 0.9)]
    b = [_make_ficha("https://a", 0.7), _make_ficha("https://b", 0.8)]
    merged = merge_candidates(a, b)
    urls = sorted(f.source_url for f in merged)
    assert urls == ["https://a", "https://b"]


async def test_run_cascade_short_circuits_on_n0_hit(monkeypatch):
    from scraper.search import cascade as cascade_mod

    async def fake_n0(nombre, session):
        return _make_ficha("db://existing", 1.0)

    async def fail(*args, **kwargs):
        raise AssertionError("should not reach N1")

    monkeypatch.setattr(cascade_mod, "lookup_db", fake_n0)
    monkeypatch.setattr(cascade_mod, "run_n1_parsers", fail)

    result = await cascade_mod.run_cascade(nombre="X", session=None, llm=None)
    assert result.level == 0
    assert len(result.fichas) == 1


async def test_run_cascade_skips_n2_when_n1_high_confidence(monkeypatch):
    from scraper.search import cascade as cascade_mod

    async def no_db(nombre, session):
        return None

    async def hi_n1(nombre, llm):
        return [_make_ficha("https://x", 0.9)]

    async def fail_n2(*args, **kwargs):
        raise AssertionError("should not reach N2")

    monkeypatch.setattr(cascade_mod, "lookup_db", no_db)
    monkeypatch.setattr(cascade_mod, "run_n1_parsers", hi_n1)
    monkeypatch.setattr(cascade_mod, "run_claude_websearch", fail_n2)

    result = await cascade_mod.run_cascade(nombre="X", session=None, llm=None)
    assert result.level == 1
    assert result.best_confidence == 0.9


async def test_run_cascade_skip_n0_bypasses_db_lookup(monkeypatch):
    from scraper.search import cascade as cascade_mod

    n0_called = False

    async def fake_n0(nombre, session):
        nonlocal n0_called
        n0_called = True
        return _make_ficha("db://x", 1.0)

    async def fake_n1(nombre, llm):
        return []

    async def fake_n2(nombre, llm):
        return [_make_ficha("https://web", 0.8)]

    monkeypatch.setattr(cascade_mod, "lookup_db", fake_n0)
    monkeypatch.setattr(cascade_mod, "run_n1_parsers", fake_n1)
    monkeypatch.setattr(cascade_mod, "run_claude_websearch", fake_n2)

    result = await cascade_mod.run_cascade(
        nombre="X", session=None, llm=None, skip_n0=True
    )
    assert n0_called is False, "lookup_db should not have been called with skip_n0=True"
    assert result.level == 2
    assert len(result.fichas) == 1
