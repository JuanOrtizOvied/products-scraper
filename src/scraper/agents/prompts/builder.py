"""Assemble system prompts for classifier and reviewer agents."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.db.models import Product, TrainingSet
from scraper.taxonomies import load_asset_classes, load_canonical_assets, load_regions

_THIS_DIR = Path(__file__).parent
_CLASSIFIER_TEMPLATE = _THIS_DIR / "classifier_system.md"
_REVIEWER_TEMPLATE = _THIS_DIR / "reviewer_system.md"
_RULES_PATH = Path(__file__).resolve().parents[4] / "rules" / "v1.md"


def _render_taxonomies() -> dict[str, str]:
    classes = load_asset_classes()
    assets = load_canonical_assets()
    regions = load_regions()

    asset_classes_md = "\n".join(f"- {c.name}" for c in classes)
    canonical_assets_md = "\n".join(
        f"- **{a.name}** → macro: {a.macro_class} (score {a.score})" for a in assets
    )
    regions_md = "\n".join(
        f"- {r.name} (benchmark weight: {r.benchmark_weight:.3f})" for r in regions
    )

    return {
        "ASSET_CLASSES": asset_classes_md,
        "N_CANONICAL_ASSETS": str(len(assets)),
        "CANONICAL_ASSETS": canonical_assets_md,
        "REGIONS": regions_md,
    }


def _render_few_shot(examples: list[dict[str, Any]]) -> str:
    if not examples:
        return "_(sin ejemplos en este run — clasifica usando solo las reglas)_"
    blocks: list[str] = []
    for i, ex in enumerate(examples, 1):
        blocks.append(
            f"### Ejemplo {i}\n\n"
            f"**Input:**\n```\n{ex['input_text']}\n```\n\n"
            f"**Output esperado:**\n```json\n"
            f"{json.dumps(ex['expected_output'], ensure_ascii=False, indent=2)}\n```"
        )
    return "\n\n".join(blocks)


def load_rules_md() -> str:
    if not _RULES_PATH.exists():
        raise FileNotFoundError(f"Rules file not found: {_RULES_PATH}")
    return _RULES_PATH.read_text(encoding="utf-8")


def build_classifier_system_prompt(
    rules_md: str,
    few_shot_examples: list[dict[str, Any]],
) -> str:
    """Single-string system prompt. Useful for non-caching contexts."""
    template = _CLASSIFIER_TEMPLATE.read_text(encoding="utf-8")
    tax = _render_taxonomies()
    return (
        template.replace("{{RULES_MD}}", rules_md)
        .replace("{{ASSET_CLASSES}}", tax["ASSET_CLASSES"])
        .replace("{{N_CANONICAL_ASSETS}}", tax["N_CANONICAL_ASSETS"])
        .replace("{{CANONICAL_ASSETS}}", tax["CANONICAL_ASSETS"])
        .replace("{{REGIONS}}", tax["REGIONS"])
        .replace("{{FEW_SHOT_EXAMPLES}}", _render_few_shot(few_shot_examples))
    )


def build_classifier_system_blocks(
    rules_md: str,
    few_shot_examples: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return Anthropic messages API system blocks with prompt caching."""
    full_prompt = build_classifier_system_prompt(rules_md, few_shot_examples)
    return [
        {
            "type": "text",
            "text": full_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def build_reviewer_system_blocks(rules_md: str) -> list[dict[str, Any]]:
    template = _REVIEWER_TEMPLATE.read_text(encoding="utf-8")
    tax = _render_taxonomies()
    prompt = (
        template.replace("{{RULES_MD}}", rules_md)
        .replace("{{ASSET_CLASSES}}", tax["ASSET_CLASSES"])
        .replace("{{N_CANONICAL_ASSETS}}", tax["N_CANONICAL_ASSETS"])
        .replace("{{CANONICAL_ASSETS}}", tax["CANONICAL_ASSETS"])
        .replace("{{REGIONS}}", tax["REGIONS"])
    )
    return [
        {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}
    ]


def _product_to_example(p: Product) -> dict[str, Any]:
    input_parts = [f'Producto: "{p.nombre}"']
    admin = p.administrador_producto or p.administrador
    gestor = p.gestor_producto or p.gestor
    if admin:
        input_parts.append(f"Administrador: {admin}")
    if gestor:
        input_parts.append(f"Gestor: {gestor}")
    if p.moneda:
        input_parts.append(f"Moneda: {p.moneda}")
    liq = p.liquidez_producto or p.liquidez
    if liq:
        input_parts.append(f"Liquidez: {liq}")
    input_text = "\n".join(input_parts)

    comision_val = p.comision_producto if p.comision_producto is not None else p.comision
    comision_conf = 1.0 if comision_val is not None else 0.8

    expected = {
        "producto": p.nombre,
        "attributes": {
            "foco_geografico": {
                "value": p.foco_geografico,
                "confidence": 1.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
                "source_url": None,
                "source_label": "training data",
                "raw_quote": None,
            },
            "clase_activo": {
                "value": p.clase_activo,
                "confidence": 1.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
                "source_url": None,
                "source_label": "training data",
                "raw_quote": None,
            },
            "subyacente": {
                "value": p.subyacentes,
                "confidence": 1.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
                "source_url": None,
                "source_label": "training data",
                "raw_quote": None,
            },
            "comision": {
                "value": comision_val if comision_val is not None else (p.comision_raw or None),
                "confidence": comision_conf,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
                "source_url": None,
                "source_label": "training data",
                "raw_quote": None,
            },
            "moneda": {
                "value": p.moneda,
                "confidence": 1.0 if p.moneda else 0.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
                "source_url": None,
                "source_label": "training data",
                "raw_quote": None,
            },
            "administrador": {
                "value": admin,
                "confidence": 1.0 if admin else 0.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
                "source_url": None,
                "source_label": "training data",
                "raw_quote": None,
            },
            "gestor": {
                "value": gestor,
                "confidence": 1.0 if gestor else 0.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
                "source_url": None,
                "source_label": "training data",
                "raw_quote": None,
            },
            "liquidez": {
                "value": liq,
                "confidence": 1.0 if liq else 0.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
                "source_url": None,
                "source_label": "training data",
                "raw_quote": None,
            },
        },
        "global_confidence": 1.0,
        "unknowns": [],
    }
    return {"producto": p.nombre, "input_text": input_text, "expected_output": expected}


async def build_few_shot_from_db(
    session: AsyncSession,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch training_set products and format as few-shot examples."""
    q = select(Product).join(TrainingSet, Product.id == TrainingSet.product_id)
    if limit is not None:
        q = q.limit(limit)
    r = await session.execute(q)
    products = list(r.scalars().all())
    return [_product_to_example(p) for p in products]
