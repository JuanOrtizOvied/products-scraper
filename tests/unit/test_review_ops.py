from datetime import UTC, datetime


async def test_list_pending_reviews_returns_unresolved(seeded_and_split_session):
    from scraper.db.models import Classification, ReviewQueue
    from scraper.ui.review_ops import list_pending_reviews

    cls = Classification(
        product_name_input="Test",
        classifier_output={},
        reviewer_output=None,
        global_confidence=0.8,
        per_attribute_confidence={},
        final_status="needs_review",
        source_used="cascade_level_2",
        duration_ms=1000,
        cost_usd=0.5,
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

    pending = await list_pending_reviews(seeded_and_split_session)
    assert len(pending) >= 1
    assert any(r.classification.product_name_input == "Test" for r in pending)


async def test_list_pending_reviews_excludes_resolved(seeded_and_split_session):
    from scraper.db.models import Classification, ReviewQueue
    from scraper.ui.review_ops import list_pending_reviews

    cls = Classification(
        product_name_input="ResolvedOne",
        classifier_output={},
        reviewer_output=None,
        global_confidence=0.9,
        per_attribute_confidence={},
        final_status="auto_approvable",
        source_used="cascade_level_0",
        duration_ms=10,
        cost_usd=0.0,
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(cls)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(cls)

    rev = ReviewQueue(
        classification_id=cls.id,
        flag="auto_approvable",
        priority=2,
        human_decision="approved",
        resolved_at=datetime.now(tz=UTC),
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(rev)
    await seeded_and_split_session.commit()

    pending = await list_pending_reviews(seeded_and_split_session)
    assert not any(r.classification.product_name_input == "ResolvedOne" for r in pending)
