def test_classification_result_roundtrip_json():
    from scraper.agents.types import AttributeClassification, ClassificationResult

    r = ClassificationResult(
        producto="Test",
        attributes={
            "foco_geografico": AttributeClassification(
                value={"Perú": 100.0},
                confidence=0.95,
                reasoning="Ficha dice Perú",
                rule_applied="regla_geografica_explicita",
            ),
        },
        global_confidence=0.95,
        unknowns=[],
    )
    j = r.to_json()
    r2 = ClassificationResult.from_json(j)
    assert r2.producto == r.producto
    assert r2.attributes["foco_geografico"].value == {"Perú": 100.0}


def test_classification_result_min_attribute_confidence():
    from scraper.agents.types import AttributeClassification, ClassificationResult

    r = ClassificationResult(
        producto="X",
        attributes={
            "a": AttributeClassification(value="a", confidence=0.95, reasoning="", rule_applied=""),
            "b": AttributeClassification(value="b", confidence=0.70, reasoning="", rule_applied=""),
        },
        global_confidence=0.80,
        unknowns=[],
    )
    assert r.min_attribute_confidence() == 0.70


def test_review_result_from_json():
    import json

    from scraper.agents.types import ReviewResult

    payload = {
        "veredicto": "disagree",
        "attribute_reviews": {
            "clase_activo": {
                "verdict": "disagree",
                "reason": "should be Club deals",
                "suggested_value": {"Club deals": 100.0},
            },
        },
        "global_verdict": "needs_review",
        "reviewer_confidence": 0.88,
    }
    r = ReviewResult.from_json(json.dumps(payload))
    assert r.global_verdict == "needs_review"
    assert r.has_disagreement() is True
