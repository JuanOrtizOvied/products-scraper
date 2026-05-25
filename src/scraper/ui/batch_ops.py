"""Batch upload operations — CSV parsing and job creation."""
from __future__ import annotations

import csv
import uuid
from datetime import UTC, datetime
from typing import IO, Any

from sqlalchemy.ext.asyncio import AsyncSession

from scraper.db.models import JobQueue


def parse_products_csv(fileobj: IO[str]) -> list[dict[str, Any]]:
    """Parse a CSV with required column 'nombre' and optional 'pdf_path', 'url'."""
    reader = csv.DictReader(fileobj)
    if reader.fieldnames is None or "nombre" not in reader.fieldnames:
        raise ValueError("CSV must have a 'nombre' column")

    rows: list[dict[str, Any]] = []
    for row_num, raw in enumerate(reader, start=2):
        nombre = (raw.get("nombre") or "").strip()
        if not nombre:
            raise ValueError(f"Row {row_num} has empty nombre")
        rows.append(
            {
                "nombre": nombre,
                "pdf_path": (raw.get("pdf_path") or "").strip() or None,
                "url": (raw.get("url") or "").strip() or None,
            }
        )
    return rows


async def create_batch(
    session: AsyncSession, rows: list[dict[str, Any]]
) -> str:
    """Insert N JobQueue rows with a shared batch_id. Returns the batch_id."""
    batch_id = str(uuid.uuid4())
    now = datetime.now(tz=UTC)
    for row in rows:
        session.add(
            JobQueue(
                batch_id=batch_id,
                nombre=row["nombre"],
                pdf_path=row.get("pdf_path"),
                url=row.get("url"),
                status="pending",
                created_at=now,
            )
        )
    await session.commit()
    return batch_id
