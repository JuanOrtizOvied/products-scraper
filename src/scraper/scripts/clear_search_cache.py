"""Clear all rows from search_cache. Useful between calibration runs.

Usage:
    poetry run python -m scraper.scripts.clear_search_cache
"""
from __future__ import annotations

import asyncio

from sqlalchemy import delete

from scraper.db.models import SearchCache
from scraper.db.session import get_session


async def _main() -> None:
    async with get_session() as s:
        result = await s.execute(delete(SearchCache))
        await s.commit()
        print(f"cleared {result.rowcount} search_cache rows")


if __name__ == "__main__":
    asyncio.run(_main())
