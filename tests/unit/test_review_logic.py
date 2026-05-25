from datetime import UTC, datetime


async def test_approve_creates_product_and_audit_log(seeded_and_split_session):
    from sqlalchemy import select

    from scraper.db.models import AuditLog, Classification, Product, ReviewQueue
    from scraper.ui.review_logic import approve_classification

    cls = Classification(
        product_name_input="Test Approve",
        classifier_output={
            "attributes": {
                "nombre": {"value": "Test Approve", "confidence": 1.0},
            }
        },
        reviewer_output={},
        global_confidence=0.9,
        per_attribute_confidence={},
        final_status="needs_review",
        source_used="cascade_level_0",
        duration_ms=100,
        cost_usd=0.3,
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(cls)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(cls)

    rev = ReviewQueue(
        classification_id=cls.id,
        flag="needs_review",
        priority=1,
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(rev)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(rev)

    edited_values = {
        "nombre": "Test Approve",
        "foco_geografico": {"Perú": 100.0},
        "clase_activo": {"Mercados Públicos - Variable": 100.0},
        "subyacente": {"Acciones Peru": 100.0},
        "moneda": "soles",
        "administrador": "Credicorp Capital",
        "gestor": "Credicorp Capital",
        "liquidez": "Inmediata",
        "minimo_inversion": None,
        "comision": 0.0065,
    }

    product_id = await approve_classification(
        seeded_and_split_session,
        review_id=rev.id,
        edited_values=edited_values,
        operator="test_operator",
    )

    r = await seeded_and_split_session.execute(
        select(Product).where(Product.id == product_id)
    )
    p = r.scalar_one()
    assert p.nombre == "Test Approve"
    assert p.moneda == "soles"
    assert p.administrador == "Credicorp Capital"

    r = await seeded_and_split_session.execute(
        select(ReviewQueue).where(ReviewQueue.id == rev.id)
    )
    updated_rev = r.scalar_one()
    assert updated_rev.human_decision == "approved"
    assert updated_rev.final_product_id == product_id
    assert updated_rev.resolved_at is not None

    r = await seeded_and_split_session.execute(
        select(AuditLog)
        .where(AuditLog.entity_type == "product")
        .where(AuditLog.entity_id == str(product_id))
    )
    logs = list(r.scalars().all())
    assert len(logs) == 1
    assert logs[0].event_type == "approval"


async def test_reject_updates_review_without_creating_product(seeded_and_split_session):
    from sqlalchemy import select

    from scraper.db.models import AuditLog, Classification, ReviewQueue
    from scraper.ui.review_logic import reject_classification

    cls = Classification(
        product_name_input="Test Reject",
        classifier_output={"attributes": {}},
        reviewer_output={},
        global_confidence=0.3,
        per_attribute_confidence={},
        final_status="low_quality",
        source_used="cascade_level_3",
        duration_ms=10,
        cost_usd=0.5,
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(cls)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(cls)

    rev = ReviewQueue(
        classification_id=cls.id,
        flag="low_quality",
        priority=0,
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(rev)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(rev)

    await reject_classification(
        seeded_and_split_session,
        review_id=rev.id,
        notes="producto no existe en universo Sabbi",
        operator="test_op",
    )

    r = await seeded_and_split_session.execute(
        select(ReviewQueue).where(ReviewQueue.id == rev.id)
    )
    updated = r.scalar_one()
    assert updated.human_decision == "rejected"
    assert updated.human_notes == "producto no existe en universo Sabbi"
    assert updated.resolved_at is not None
    assert updated.final_product_id is None

    r = await seeded_and_split_session.execute(
        select(AuditLog).where(AuditLog.event_type == "rejection")
    )
    logs = list(r.scalars().all())
    assert len(logs) == 1
