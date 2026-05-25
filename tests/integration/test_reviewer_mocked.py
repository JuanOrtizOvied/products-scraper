import json


async def test_reviewer_agrees(mock_llm_client):
    from scraper.agents.reviewer import review
    from scraper.agents.types import AttributeClassification, ClassificationResult

    output = json.dumps({
        "veredicto": "agree",
        "attribute_reviews": {
            "foco_geografico": {"verdict": "agree", "reason": "", "suggested_value": None},
        },
        "global_verdict": "auto_approvable",
        "reviewer_confidence": 0.95,
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(
        output, model="claude-opus-4-7"
    )

    classifier_output = ClassificationResult(
        producto="X",
        attributes={
            "foco_geografico": AttributeClassification(
                value={"Perú": 100.0}, confidence=0.95, reasoning="", rule_applied=""
            ),
        },
        global_confidence=0.95,
        unknowns=[],
    )
    result = await review(
        llm=mock_llm_client,
        producto_nombre="X",
        product_context={},
        classifier_output=classifier_output,
        rules_md="#",
    )
    assert result.global_verdict == "auto_approvable"
    assert result.has_disagreement() is False


async def test_reviewer_disagrees(mock_llm_client):
    from scraper.agents.reviewer import review
    from scraper.agents.types import AttributeClassification, ClassificationResult

    output = json.dumps({
        "veredicto": "disagree",
        "attribute_reviews": {
            "clase_activo": {
                "verdict": "disagree",
                "reason": "debería ser Club deals, no Mercados Privados",
                "suggested_value": {"Club deals": 100.0},
            },
        },
        "global_verdict": "needs_review",
        "reviewer_confidence": 0.88,
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(
        output, model="claude-opus-4-7"
    )

    classifier_output = ClassificationResult(
        producto="X",
        attributes={
            "clase_activo": AttributeClassification(
                value={"Mercados Privados": 100.0}, confidence=0.88, reasoning="", rule_applied=""
            ),
        },
        global_confidence=0.88,
        unknowns=[],
    )
    result = await review(
        llm=mock_llm_client,
        producto_nombre="X",
        product_context={},
        classifier_output=classifier_output,
        rules_md="#",
    )
    assert result.has_disagreement() is True
    assert result.global_verdict == "needs_review"
