"""Classifier agent — uses Claude Sonnet 4.6."""
from __future__ import annotations

import json
from typing import Any

import structlog

from scraper.agents.parsing import strip_fences, try_parse_json
from scraper.agents.prompts.builder import build_classifier_system_blocks
from scraper.agents.types import ClassificationResult
from scraper.llm import LLMClient
from scraper.taxonomies.normalizer import (
    normalize_percentage_dict_asset_class,
    normalize_percentage_dict_region,
    normalize_percentage_dict_subyacente,
)

log = structlog.get_logger()

CLASSIFIER_MODEL = "claude-sonnet-4-6"


_strip_fences = strip_fences


class ClassifierParseError(ValueError):
    """Raised when classifier output can't be parsed as valid ClassificationResult."""


def _build_user_message(nombre: str, context: dict[str, Any]) -> str:
    parts = [f'Producto: "{nombre}"']
    for key in ("administrador", "gestor", "moneda", "liquidez"):
        if context.get(key):
            parts.append(f"{key.capitalize()}: {context[key]}")
    if "extra" in context and context["extra"]:
        parts.append(f"Información adicional: {context['extra']}")
    return "\n".join(parts)


def _rescale_to_100(d: dict[str, float]) -> dict[str, float]:
    """Rescale percentage dict values so they sum to exactly 100."""
    total = sum(d.values())
    if total <= 0:
        return d
    if abs(total - 100) < 2:
        return d
    return {k: round(v * 100 / total, 1) for k, v in d.items()}


def _normalize_output(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize non-canonical values in output."""
    attrs = payload.get("attributes", {})

    for key, normalizer in [
        ("clase_activo", normalize_percentage_dict_asset_class),
        ("foco_geografico", normalize_percentage_dict_region),
        ("subyacente", normalize_percentage_dict_subyacente),
    ]:
        val = attrs.get(key, {}).get("value")
        if isinstance(val, dict):
            normalized = normalizer(val)
            attrs[key]["value"] = _rescale_to_100(normalized)

    return payload


async def classify(
    *,
    llm: LLMClient,
    producto_nombre: str,
    product_context: dict[str, Any],
    rules_md: str,
    few_shot_examples: list[dict[str, Any]],
) -> ClassificationResult:
    """Classify a single product using Claude Sonnet 4.6."""
    system_blocks = build_classifier_system_blocks(rules_md, few_shot_examples)
    user_message = _build_user_message(producto_nombre, product_context)

    result = await llm.call(
        model=CLASSIFIER_MODEL,
        system=system_blocks,
        messages=[{"role": "user", "content": user_message}],
        max_tokens=4096,
    )

    clean = strip_fences(result.response_text)
    payload = try_parse_json(clean)
    if payload is None:
        raise ClassifierParseError(
            f"Model output is not valid JSON: cannot parse\nOutput: {clean[:500]}"
        )

    payload = _normalize_output(payload)

    try:
        return ClassificationResult.from_json(payload)
    except (KeyError, ValueError, TypeError) as e:
        raise ClassifierParseError(f"JSON doesn't match ClassificationResult schema: {e}") from e
