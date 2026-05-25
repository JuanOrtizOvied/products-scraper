from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def mock_llm_client():
    """LLMClient mock that returns a pre-configured response."""
    from scraper.llm.client import CallResult
    from scraper.llm.cost import ClaudeCost

    client = MagicMock()
    client.call = AsyncMock()
    client.cost = MagicMock()

    def make_result(response_text: str, model: str = "claude-sonnet-4-6") -> CallResult:
        msg = MagicMock()
        msg.usage.input_tokens = 100
        msg.usage.output_tokens = 50
        return CallResult(
            model=model,
            response_text=response_text,
            raw_message=msg,
            cost=ClaudeCost(
                input_usd=0.0003,
                output_usd=0.00075,
                cache_read_usd=0.0,
                cache_write_usd=0.0,
            ),
            duration_ms=1234,
        )

    client.make_result = make_result  # helper for tests
    return client


@pytest.fixture
def excel_path(repo_root: Path) -> Path:
    return repo_root / "BD_Productos Sabbi.xlsx"


@pytest_asyncio.fixture
async def seeded_and_split_session(excel_path: Path):
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
