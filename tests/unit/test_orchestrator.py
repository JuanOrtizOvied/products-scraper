def _cls(attr_confs: dict, global_conf: float):
    from scraper.agents.types import AttributeClassification, ClassificationResult

    attrs = {
        k: AttributeClassification(value=None, confidence=c, reasoning="", rule_applied="")
        for k, c in attr_confs.items()
    }
    return ClassificationResult(
        producto="x", attributes=attrs, global_confidence=global_conf, unknowns=[]
    )


def _rev(verdict: str, has_disagreement: bool):
    from scraper.agents.types import ReviewResult

    return ReviewResult(
        veredicto="disagree" if has_disagreement else "agree",
        attribute_reviews={},
        global_verdict=verdict,
        reviewer_confidence=0.9,
    )


def test_decide_flag_low_quality_when_global_below_70():
    from scraper.agents.orchestrator import decide_flag

    c = _cls({"a": 0.95}, global_conf=0.65)
    r = _rev(verdict="low_quality", has_disagreement=False)
    assert decide_flag(c, r) == "low_quality"


def test_decide_flag_needs_review_on_disagreement():
    from scraper.agents.orchestrator import decide_flag

    c = _cls({"a": 0.95, "b": 0.95}, global_conf=0.95)
    r = _rev(verdict="needs_review", has_disagreement=True)
    assert decide_flag(c, r) == "needs_review"


def test_decide_flag_needs_review_on_low_attribute_confidence():
    from scraper.agents.orchestrator import decide_flag

    c = _cls({"a": 0.95, "b": 0.80}, global_conf=0.87)
    r = _rev(verdict="agree", has_disagreement=False)
    assert decide_flag(c, r) == "needs_review"


def test_decide_flag_auto_approvable_when_all_clean():
    from scraper.agents.orchestrator import decide_flag

    c = _cls({"a": 0.95, "b": 0.92}, global_conf=0.94)
    r = _rev(verdict="agree", has_disagreement=False)
    assert decide_flag(c, r) == "auto_approvable"


def test_decide_flag_priority_low_quality_over_needs_review():
    from scraper.agents.orchestrator import decide_flag

    c = _cls({"a": 0.95}, global_conf=0.60)
    r = _rev(verdict="low_quality", has_disagreement=True)
    assert decide_flag(c, r) == "low_quality"
