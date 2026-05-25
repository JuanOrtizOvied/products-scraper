"""End-to-end: CSV → queue → worker → review → approve → Product."""
from datetime import UTC, datetime
from io import StringIO


async def test_e2e_csv_to_approved_product(seeded_and_split_session, mock_llm_client, monkeypatch):
    from sqlalchemy import select

    from scraper.agents.types import AttributeClassification, ClassificationResult
    from scraper.db.models import Product, ReviewQueue
    from scraper.scripts.worker_ops import claim_pending_jobs
    from scraper.ui.batch_ops import create_batch, parse_products_csv
    from scraper.ui.review_logic import approve_classification

    csv = "nombre\nTest E2E Product\n"
    rows = parse_products_csv(StringIO(csv))
    batch_id = await create_batch(seeded_and_split_session, rows)
    assert batch_id

    claimed = await claim_pending_jobs(seeded_and_split_session, limit=1)
    assert len(claimed) == 1
    job = claimed[0]

    fake_cls = ClassificationResult(
        producto="Test E2E Product",
        attributes={
            "nombre": AttributeClassification(
                value="Test E2E Product", confidence=1.0, reasoning="", rule_applied=""
            ),
            "moneda": AttributeClassification(
                value="soles", confidence=1.0, reasoning="", rule_applied=""
            ),
        },
        global_confidence=0.9,
        unknowns=[],
    )

    async def fake_pipeline(*args, **kwargs):
        return (
            fake_cls,
            {"veredicto": "agree", "global_verdict": "auto_approvable", "reviewer_confidence": 0.9},
            "auto_approvable",
            "cascade_level_0",
            0.05,
            100,
            [],
            [{"url": "http://example.com", "label": "test", "document_date": None, "source_type": "html"}],
            None,
        )

    monkeypatch.setattr(
        "scraper.scripts.worker_pipeline._run_cascade_classify_review", fake_pipeline
    )

    from scraper.scripts.worker_pipeline import process_job_via_cascade

    cls_id = await process_job_via_cascade(
        session=seeded_and_split_session,
        job=job,
        llm=mock_llm_client,
        rules_md="# rules",
    )

    r = await seeded_and_split_session.execute(
        select(ReviewQueue).where(ReviewQueue.classification_id == cls_id)
    )
    rev = r.scalar_one()
    assert rev.flag == "auto_approvable"

    edited = {
        "nombre": "Test E2E Product",
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
        edited_values=edited,
        operator="e2e_test",
    )

    r = await seeded_and_split_session.execute(
        select(Product).where(Product.id == product_id)
    )
    p = r.scalar_one()
    assert p.nombre == "Test E2E Product"
    assert p.administrador == "Credicorp Capital"
