"""CLI: run classifier over validation_set, compute accuracy, save report.

Usage:
    poetry run python -m scraper.scripts.calibrate                      # use rules/v1.md
    poetry run python -m scraper.scripts.calibrate --rules rules/v2.md  # specify version
    poetry run python -m scraper.scripts.calibrate --dry-run            # no LLM calls (dummy 100%)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Windows default console is cp1252; this CLI prints many non-ASCII chars
# (Calibración, ¿, █, ░, ✓, ✗, accented product names). Reconfigure stdout to
# utf-8 (same pattern as scraper.scripts.classify_one and bootstrap_rules_v1).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import structlog
from sqlalchemy import select

from scraper.agents.classifier import ClassifierParseError, classify
from scraper.agents.orchestrator import decide_flag
from scraper.agents.prompts.builder import build_few_shot_from_db
from scraper.agents.reviewer import review
from scraper.config import get_settings
from scraper.db.models import Product, RulesVersion, ValidationSet
from scraper.db.session import get_session
from scraper.llm import LLMClient
from scraper.logging_config import configure_logging
from scraper.metrics import aggregate_accuracy, compute_product_accuracy
from scraper.taxonomies.normalizer import (
    normalize_percentage_dict_asset_class,
    normalize_percentage_dict_region,
    normalize_percentage_dict_subyacente,
)

log = structlog.get_logger()


def _product_to_ground_truth(p: Product) -> dict:
    """Build ground truth dict from a Product row.

    Returns a dict with both product-layer and distribution-layer keys.
    If two-layer columns are populated, uses those. Otherwise falls back
    to the original single-layer columns (backwards compatible).
    """
    gt = {
        "foco_geografico": normalize_percentage_dict_region(p.foco_geografico or {}),
        "clase_activo": normalize_percentage_dict_asset_class(p.clase_activo or {}),
        "subyacentes": normalize_percentage_dict_subyacente(p.subyacentes or {}),
        "moneda": p.moneda,
    }
    # Product layer
    gt["administrador_producto"] = p.administrador_producto or p.administrador
    gt["gestor_producto"] = p.gestor_producto or p.gestor
    gt["comision_producto"] = p.comision_producto if p.comision_producto is not None else p.comision
    gt["minimo_inversion_producto"] = p.minimo_inversion_producto or p.minimo_inversion
    gt["liquidez_producto"] = p.liquidez_producto or p.liquidez
    # Distribution layer
    gt["intermediario"] = p.intermediario
    gt["tipo_intermediario"] = p.tipo_intermediario
    gt["comision_distribucion"] = p.comision_distribucion if p.comision_distribucion is not None else p.comision
    gt["minimo_via_intermediario"] = p.minimo_via_intermediario or p.minimo_inversion
    gt["liquidez_via_intermediario"] = p.liquidez_via_intermediario or p.liquidez
    # Legacy keys (for backwards compat with old calibrate.py consumers)
    gt["comision"] = p.comision
    gt["administrador"] = p.administrador
    gt["gestor"] = p.gestor
    gt["liquidez"] = p.liquidez
    gt["minimo_inversion"] = p.minimo_inversion
    return gt


async def _main(rules_path: Path, dry_run: bool = False) -> int:
    configure_logging(level="INFO", json_logs=False)

    rules_md = rules_path.read_text(encoding="utf-8")
    version = rules_path.stem  # e.g., "v1"

    settings = get_settings()
    if not dry_run and not settings.anthropic_api_key:
        print(
            "ERROR: ANTHROPIC_API_KEY no configurada. Use --dry-run para smoke test.",
            file=sys.stderr,
        )
        return 2

    async with get_session() as s:
        # Fetch validation products
        r = await s.execute(
            select(Product).join(ValidationSet, Product.id == ValidationSet.product_id)
        )
        validation = list(r.scalars().all())
        few_shot = await build_few_shot_from_db(s, limit=None)

    print(f"\n=== Calibración {version} — {len(validation)} productos ===\n")

    llm = None if dry_run else LLMClient()
    reports: list[dict[str, bool]] = []
    per_product_details: list[dict] = []

    for i, p in enumerate(validation, 1):
        context = {
            "administrador": p.administrador,
            "gestor": p.gestor,
            "moneda": p.moneda,
            "liquidez": p.liquidez,
        }
        ground_truth = _product_to_ground_truth(p)

        if dry_run:
            # Produce a fake "all correct" result to test the pipeline end-to-end
            from scraper.agents.types import AttributeClassification, ClassificationResult

            fake = ClassificationResult(
                producto=p.nombre,
                attributes={
                    attr: AttributeClassification(
                        value=val, confidence=1.0, reasoning="dry-run", rule_applied="dry-run"
                    )
                    for attr, val in [
                        ("foco_geografico", ground_truth["foco_geografico"]),
                        ("clase_activo", ground_truth["clase_activo"]),
                        ("subyacente", p.subyacentes),
                        ("comision", p.comision),
                        ("moneda", p.moneda),
                        ("administrador", p.administrador),
                        ("gestor", p.gestor),
                        ("liquidez", p.liquidez),
                        ("minimo_inversion", p.minimo_inversion),
                    ]
                },
                global_confidence=1.0,
                unknowns=[],
            )
            report = compute_product_accuracy(ground_truth, fake)
            reports.append(report)
            print(f"[{i:2d}/{len(validation)}] {p.nombre[:50]:50s} DRY-RUN {report}")
            continue

        try:
            cls_result = await classify(
                llm=llm,
                producto_nombre=p.nombre,
                product_context=context,
                rules_md=rules_md,
                few_shot_examples=few_shot,
            )
            rev_result = await review(
                llm=llm,
                producto_nombre=p.nombre,
                product_context=context,
                classifier_output=cls_result,
                rules_md=rules_md,
            )
            flag = decide_flag(cls_result, rev_result)
            report = compute_product_accuracy(ground_truth, cls_result)
            reports.append(report)

            correct_count = sum(1 for v in report.values() if v)
            total_attrs = len(report)
            print(
                f"[{i:2d}/{len(validation)}] {p.nombre[:50]:50s} "
                f"{correct_count}/{total_attrs} atr · flag={flag} · "
                f"conf={cls_result.global_confidence:.2f}"
            )
            # Debug: on any miss, print gt vs predicted for the failing attributes
            gt_key_alias = {"subyacente": "subyacentes"}
            for attr, ok in report.items():
                if ok:
                    continue
                gt = ground_truth.get(gt_key_alias.get(attr, attr))
                predicted_attr = cls_result.attributes.get(attr)
                pred = predicted_attr.value if predicted_attr else None
                print(f"        ✗ {attr:18s} gt={gt!r}  pred={pred!r}")
            per_product_details.append(
                {
                    "nombre": p.nombre,
                    "accuracy": report,
                    "global_confidence": cls_result.global_confidence,
                    "flag": flag,
                    "reviewer_verdict": rev_result.global_verdict,
                }
            )
        except ClassifierParseError as e:
            log.warning("classifier_parse_error", producto=p.nombre, error=str(e))
            reports.append(
                {
                    attr: False
                    for attr in [
                        "foco_geografico",
                        "clase_activo",
                        "subyacente",
                        "comision",
                        "moneda",
                        "administrador",
                        "gestor",
                        "liquidez",
                        "minimo_inversion",
                    ]
                }
            )

    # Aggregate accuracy
    accuracy = aggregate_accuracy(reports)
    print(f"\n=== Resultado ({version}) ===")
    print(f"Productos evaluados: {len(reports)}")
    for attr, acc in sorted(accuracy.items()):
        bar = "█" * int(acc * 20) + "░" * (20 - int(acc * 20))
        flag = "✓" if acc >= 0.85 else "✗"
        print(f"  {flag} {attr:20s} [{bar}] {acc:.1%}")
    if llm:
        print(f"\nCosto total: ${llm.cost.total_usd:.3f}")

    # Save to DB
    async with get_session() as s:
        r = await s.execute(select(RulesVersion).where(RulesVersion.version == version))
        rv = r.scalar_one_or_none()
        if rv is None:
            rv = RulesVersion(
                version=version,
                content_md=rules_md,
                notes=f"Calibración automática {'(dry-run)' if dry_run else ''}",
            )
            s.add(rv)
        rv.validation_accuracy = {
            "per_attribute": accuracy,
            "n_products": len(reports),
            "dry_run": dry_run,
            "details": per_product_details[:5],  # save first 5 for inspection, not all
        }
        await s.commit()
        print(f"\nGuardado en rules_versions.{version}.validation_accuracy")

    min_attr_accuracy = min(accuracy.values()) if accuracy else 0.0
    return 0 if min_attr_accuracy >= 0.85 else 1  # exit 1 if any attr below threshold


def cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules", default="rules/v1.md", help="Path to rules markdown")
    parser.add_argument(
        "--dry-run", action="store_true", help="Skip LLM calls (pipeline smoke test)"
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(Path(args.rules), dry_run=args.dry_run)))


if __name__ == "__main__":
    cli()
