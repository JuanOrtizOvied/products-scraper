"""Reviewer agent — uses Claude Opus 4.7 to critique classifier output."""
from __future__ import annotations

import json
from typing import Any

import structlog

from scraper.agents.classifier import ClassifierParseError, _strip_fences
from scraper.agents.prompts.builder import build_reviewer_system_blocks
from scraper.agents.types import ClassificationResult, ReviewResult
from scraper.llm import LLMClient

log = structlog.get_logger()

REVIEWER_MODEL = "claude-opus-4-7"


async def review(
    *,
    llm: LLMClient,
    producto_nombre: str,
    product_context: dict[str, Any],
    classifier_output: ClassificationResult,
    rules_md: str,
) -> ReviewResult:
    """Critique a classifier output using Claude Opus 4.7."""
    system_blocks = build_reviewer_system_blocks(rules_md)

    user_parts = [
        "# Input original",
        f'Producto: "{producto_nombre}"',
    ]
    for key in ("administrador", "gestor", "moneda", "liquidez"):
        if product_context.get(key):
            user_parts.append(f"{key.capitalize()}: {product_context[key]}")

    user_parts.append("\n# Clasificación a revisar")
    user_parts.append(f"```json\n{classifier_output.to_json()}\n```")
    user_parts.append("\nRevisa la clasificación y responde con el JSON de veredicto.")

    user_message = "\n".join(user_parts)

    result = await llm.call(
        model=REVIEWER_MODEL,
        system=system_blocks,
        messages=[{"role": "user", "content": user_message}],
        max_tokens=2048,
    )

    clean = _strip_fences(result.response_text)
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError as e:
        raise ClassifierParseError(
            f"Reviewer output is not valid JSON: {e}\nOutput: {clean[:500]}"
        ) from e

    return ReviewResult.from_json(payload)
