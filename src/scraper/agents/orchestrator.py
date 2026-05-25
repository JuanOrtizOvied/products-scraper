"""Pure decision logic for classification flag assignment.

Priority order: low_quality > needs_review > auto_approvable.
"""
from __future__ import annotations

from scraper.agents.types import ClassificationResult, ReviewResult

GLOBAL_CONFIDENCE_THRESHOLD = 0.70
PER_ATTRIBUTE_THRESHOLD = 0.90


def decide_flag(classifier: ClassificationResult, reviewer: ReviewResult) -> str:
    """Return one of: low_quality, needs_review, auto_approvable."""
    # 1. Low quality — worst case
    if (
        classifier.global_confidence < GLOBAL_CONFIDENCE_THRESHOLD
        or reviewer.global_verdict == "low_quality"
    ):
        return "low_quality"

    # 2. Needs review — disagreement or low attribute confidence
    if reviewer.has_disagreement():
        return "needs_review"
    if classifier.min_attribute_confidence() < PER_ATTRIBUTE_THRESHOLD:
        return "needs_review"

    return "auto_approvable"
