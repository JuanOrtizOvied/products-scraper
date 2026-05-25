def test_run_async_executes_coroutine():
    from scraper.ui.state import run_async

    async def _hello():
        return "hello"

    result = run_async(_hello())
    assert result == "hello"


def test_run_async_preserves_return_value():
    from scraper.ui.state import run_async

    async def _compute():
        return 1 + 2

    assert run_async(_compute()) == 3
