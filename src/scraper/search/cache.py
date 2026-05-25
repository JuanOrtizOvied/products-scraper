"""search_cache wrapper — store/retrieve ExtractedFicha lists per (nombre, source)."""
from __future__ import annotations

import hashlib
import unicodedata
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.agents.types import ExtractedFicha
from scraper.db.models import SearchCache

log = structlog.get_logger()

# TTL per cascade level / source_type
_TTL_DAYS: dict[str, int] = {
    "db": 0,              # N0 doesn't use search_cache (it IS the DB)
    "level1": 7,          # N1 — known targets
    "websearch": 30,      # N2 — Claude web_search
    "intensive": 0,       # N3 — don't cache until calibrated; 0 means "never fresh"
}


def _hash_key(nombre: str) -> str:
    normalized = unicodedata.normalize("NFKD", nombre).lower().strip()
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def get_cached(
    session: AsyncSession, nombre: str, source: str
) -> list[ExtractedFicha] | None:
    """Return cached fichas or None if miss/expired."""
    ttl_days = _TTL_DAYS.get(source, 0)
    if ttl_days <= 0:
        return None

    key = _hash_key(nombre)
    r = await session.execute(
        select(SearchCache).where(
            SearchCache.query_hash == key, SearchCache.source == source
        )
    )
    row = r.scalar_one_or_none()
    if row is None:
        return None

    fetched_at = row.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=UTC)
    age = datetime.now(tz=UTC) - fetched_at
    if age > timedelta(days=ttl_days):
        log.info("cache_expired", nombre=nombre, source=source, age_days=age.days)
        return None

    payload = row.response
    items = payload.get("items", []) if isinstance(payload, dict) else []
    return [ExtractedFicha.from_json(x) for x in items]


async def put_cached(
    session: AsyncSession, nombre: str, source: str, fichas: list[ExtractedFicha]
) -> None:
    """Store fichas in cache (upsert by key + source)."""
    ttl_days = _TTL_DAYS.get(source, 0)
    if ttl_days <= 0:
        return

    key = _hash_key(nombre)
    # Upsert: delete then insert (simpler than dialect-specific upsert for sqlite/pg)
    await session.execute(
        delete(SearchCache).where(
            SearchCache.query_hash == key, SearchCache.source == source
        )
    )
    row = SearchCache(
        query_hash=key,
        query_text=nombre,
        source=source,
        response={"items": [f.to_json() for f in fichas]},
        fetched_at=datetime.now(tz=UTC),
        ttl_days=ttl_days,
    )
    session.add(row)
    await session.commit()
