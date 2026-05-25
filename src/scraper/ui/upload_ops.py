"""Upload handlers for reactive PDF-triggered reclassification."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from scraper.db.models import JobQueue, UploadedDocument


async def reclassify_with_pdf(
    session: AsyncSession,
    nombre: str,
    pdf_bytes: bytes,
    operator: str,
    target_classification_id: int | None = None,
) -> int:
    """Save uploaded PDF to disk, insert uploaded_documents row, queue new JobQueue.

    If target_classification_id is provided, the worker will update that existing
    Classification + ReviewQueue instead of creating new rows.
    """
    uploads_dir = Path.cwd() / "data" / "uploaded_pdfs"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    h = hashlib.sha256(pdf_bytes).hexdigest()[:16]
    pdf_path = uploads_dir / f"{h}.pdf"
    if not pdf_path.exists():
        pdf_path.write_bytes(pdf_bytes)

    doc = UploadedDocument(
        product_name=nombre,
        file_path=str(pdf_path),
        mime_type="application/pdf",
    )
    session.add(doc)
    await session.commit()

    job = JobQueue(
        nombre=nombre,
        pdf_path=str(pdf_path),
        status="pending",
        target_classification_id=target_classification_id,
        created_at=datetime.now(tz=UTC),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job.id
