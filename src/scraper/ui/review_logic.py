"""Approve / reject logic."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.db.models import AuditLog, Classification, JobQueue, Product, ReviewQueue


async def approve_classification(
    session: AsyncSession,
    review_id: int,
    edited_values: dict,
    operator: str,
) -> int:
    """Create a Product from edited values, mark review as approved, log in audit_log."""
    r = await session.execute(select(ReviewQueue).where(ReviewQueue.id == review_id))
    rev = r.scalar_one()

    r = await session.execute(
        select(Classification).where(Classification.id == rev.classification_id)
    )
    cls = r.scalar_one()

    product = Product(
        nombre=edited_values.get("nombre") or cls.product_name_input,
        foco_geografico=edited_values.get("foco_geografico") or {},
        clase_activo=edited_values.get("clase_activo") or {},
        subyacentes=edited_values.get("subyacente") or {},
        comision=_to_float(edited_values.get("comision")),
        comision_raw=(
            edited_values.get("comision")
            if isinstance(edited_values.get("comision"), str)
            else None
        ),
        moneda=edited_values.get("moneda"),
        administrador=edited_values.get("administrador"),
        gestor=edited_values.get("gestor"),
        liquidez=edited_values.get("liquidez"),
        minimo_inversion=edited_values.get("minimo_inversion"),
        source_type="pipeline_approved",
        status="active",
    )
    session.add(product)
    await session.commit()
    await session.refresh(product)

    rev.human_decision = "approved"
    rev.final_product_id = product.id
    rev.resolved_at = datetime.now(tz=UTC)
    await session.commit()

    await session.execute(
        update(JobQueue)
        .where(JobQueue.classification_id == cls.id)
        .values(status="approved")
    )
    await session.commit()

    audit = AuditLog(
        event_type="approval",
        actor=operator,
        entity_type="product",
        entity_id=str(product.id),
        before_state={"classification_output": cls.classifier_output},
        after_state=edited_values,
    )
    session.add(audit)
    await session.commit()
    return product.id


async def reject_classification(
    session: AsyncSession,
    review_id: int,
    notes: str,
    operator: str,
) -> None:
    r = await session.execute(select(ReviewQueue).where(ReviewQueue.id == review_id))
    rev = r.scalar_one()

    rev.human_decision = "rejected"
    rev.human_notes = notes
    rev.resolved_at = datetime.now(tz=UTC)
    await session.commit()

    audit = AuditLog(
        event_type="rejection",
        actor=operator,
        entity_type="review_queue",
        entity_id=str(review_id),
        before_state=None,
        after_state={"notes": notes},
    )
    session.add(audit)
    await session.commit()


def _to_float(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val) if val else None
        except ValueError:
            return None
    return None
