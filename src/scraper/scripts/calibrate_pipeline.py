"""CLI: run the full cascade+classifier pipeline over validation_set, measure accuracy.

Unlike Phase 2a's `calibrate.py` (which fed the classifier from DB ground truth
directly), this runs the end-to-end pipeline for each validation product:
nombre → cascade search → extract → classify → compare to ground truth.

IMPORTANT: uses skip_n0=True so the cascade does NOT consult the local DB
first. Without this, lookup_db would find the validation products themselves
(they live in the same `products` table) and return 100% trivially. Skipping
N0 forces the cascade to start at N1/N2 (web_search → extract → classify),
which is the real user experience for unknown products.

Usage:
    poetry run python -m scraper.scripts.calibrate_pipeline
    poetry run python -m scraper.scripts.calibrate_pipeline --rules rules/v4.md
    poetry run python -m scraper.scripts.calibrate_pipeline --dry-run
    poetry run python -m scraper.scripts.calibrate_pipeline --limit 3   # smoke test subset
    poetry run python -m scraper.scripts.calibrate_pipeline \
        --exclude-clase "Club deals,Inmobiliario Directo"
    poetry run python -m scraper.scripts.calibrate_pipeline \
        --only-nombres "Credicorp Crecimiento,FBA Bonos Globales"

Cost: ~$0.80-1.50 per product × 19 products = ~$15-30 per full run.
Duration: ~3-5 min per product × 19 = ~1-1.5 hours (serial).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import structlog
from sqlalchemy import select

from scraper.agents.classifier import ClassifierParseError, classify
from scraper.agents.distributor import find_distribution
from scraper.agents.prompts.builder import build_few_shot_from_db
from scraper.config import get_settings
from scraper.db.models import Product, RulesVersion, ValidationSet
from scraper.db.session import get_session
from scraper.llm import LLMClient
from scraper.logging_config import configure_logging
from scraper.metrics import aggregate_accuracy
from scraper.metrics.accuracy import compute_distribution_accuracy, compute_product_accuracy_v8
from scraper.scripts.calibrate import _product_to_ground_truth
from scraper.scripts.find_and_classify import _context_from_top, _top_ficha
from scraper.search.cascade import run_cascade
from scraper.taxonomies.normalizer import normalize_asset_class

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

log = structlog.get_logger()


def _dominant_clase_activo(p) -> str | None:
    """Return the canonical dominant macro class from a product's ground-truth
    clase_activo dict, or None if unable to determine.

    Normalizes the dict keys through the Sabbi taxonomy normalizer so a raw
    'Mercado publico variable' entry maps to 'Mercados Públicos - Variable'.
    """
    raw = p.clase_activo or {}
    if not raw:
        return None
    # Pick the key with the largest value
    dominant_raw = max(raw.items(), key=lambda kv: kv[1])[0]
    return normalize_asset_class(dominant_raw)


async def _main(
    rules_path: Path,
    dry_run: bool,
    limit: int | None,
    exclude_clase: str = "",
    only_nombres: str = "",
    output_path: str | None = None,
) -> int:
    configure_logging(level="INFO", json_logs=False)

    if dry_run:
        print(
            f"Calibración pipeline (dry-run): would run rules={rules_path} "
            "against validation_set."
        )
        return 0

    settings = get_settings()
    if not settings.anthropic_api_key:
        print("ERROR: ANTHROPIC_API_KEY no configurada.", file=sys.stderr)
        return 2

    rules_md = rules_path.read_text(encoding="utf-8")
    version = f"pipeline_{rules_path.stem}"

    async with get_session() as s:
        r = await s.execute(
            select(Product).join(ValidationSet, Product.id == ValidationSet.product_id)
        )
        validation = list(r.scalars().all())
        few_shot = await build_few_shot_from_db(s, limit=20)

    # Filter: only specific nombres requested
    if only_nombres:
        wanted = {n.strip() for n in only_nombres.split(",") if n.strip()}
        validation = [p for p in validation if p.nombre in wanted]
        if not validation:
            print(
                f"No products matched --only-nombres filter: {sorted(wanted)}",
                file=sys.stderr,
            )
            return 2

    # Filter: exclude products by dominant clase_activo (e.g. private Club Deals)
    elif exclude_clase:
        excluded_classes = {
            c.strip() for c in exclude_clase.split(",") if c.strip()
        }
        before = len(validation)
        validation = [
            p
            for p in validation
            if _dominant_clase_activo(p) not in excluded_classes
        ]
        skipped = before - len(validation)
        if skipped:
            print(
                f"Filter: --exclude-clase excluded {skipped} products "
                f"(dominant class in {sorted(excluded_classes)})."
            )

    if limit is not None:
        validation = validation[:limit]

    print(f"\n=== Calibración pipeline {version} — {len(validation)} productos ===\n")

    llm = LLMClient()
    reports: list[dict[str, bool]] = []
    dist_reports: list[dict[str, bool]] = []
    per_product_details: list[dict] = []

    for i, p in enumerate(validation, 1):
        ground_truth = _product_to_ground_truth(p)
        p_start = time.monotonic()
        try:
            async with get_session() as s2:
                cascade = await run_cascade(
                    nombre=p.nombre, session=s2, llm=llm, skip_n0=True
                )
            top = _top_ficha(cascade.fichas)
            context = _context_from_top(top, cascade.fichas)

            cls_result = await classify(
                llm=llm,
                producto_nombre=p.nombre,
                product_context=context,
                rules_md=rules_md,
                few_shot_examples=few_shot,
            )

            # Pass 2: Distribution
            admin_attr = cls_result.attributes.get("administrador")
            admin_prod = admin_attr.value if admin_attr else None
            comision_attr = cls_result.attributes.get("comision")
            comision_prod = comision_attr.value if comision_attr and isinstance(comision_attr.value, (int, float)) else None
            clase_attr = cls_result.attributes.get("clase_activo")
            clase_val = clase_attr.value if clase_attr and isinstance(clase_attr.value, dict) else None

            dist_result = await find_distribution(
                llm=llm,
                nombre=p.nombre,
                administrador_producto=admin_prod,
                comision_producto=comision_prod,
                clase_activo=clase_val,
            )

            report = compute_product_accuracy_v8(ground_truth, cls_result)
            dist_report = compute_distribution_accuracy(ground_truth, dist_result)
            reports.append(report)
            dist_reports.append(dist_report)

            correct = sum(1 for v in report.values() if v)
            total = len(report)
            elapsed = time.monotonic() - p_start
            print(
                f"[{i:2d}/{len(validation)}] {p.nombre[:50]:50s} "
                f"{correct}/{total} atr · L{cascade.level} · "
                f"fichas={len(cascade.fichas)} · conf={cls_result.global_confidence:.2f} · "
                f"{elapsed:.0f}s"
            )

            # Debug output for attribute misses
            for attr, ok in report.items():
                if ok:
                    continue
                gt_key_alias = {"subyacente": "subyacentes"}
                gt = ground_truth.get(gt_key_alias.get(attr, attr))
                pred_attr = cls_result.attributes.get(attr)
                pred = pred_attr.value if pred_attr else None
                print(f"        ✗ {attr:18s} gt={gt!r}  pred={pred!r}")

            for attr, ok in dist_report.items():
                if ok:
                    continue
                gt = ground_truth.get(attr)
                pred = getattr(dist_result, attr, None)
                print(f"        ✗ dist.{attr:14s} gt={gt!r}  pred={pred!r}")

            per_product_details.append(
                {
                    "nombre": p.nombre,
                    "cascade_level": cascade.level,
                    "fichas": len(cascade.fichas),
                    "accuracy": report,
                    "distribution_accuracy": dist_report,
                    "global_confidence": cls_result.global_confidence,
                    "distribution_confidence": dist_result.confidence,
                    "elapsed_s": round(elapsed, 1),
                }
            )
        except ClassifierParseError as e:
            log.warning("pipeline_classifier_parse_error", producto=p.nombre, error=str(e))
            reports.append(
                {
                    attr: False
                    for attr in [
                        "foco_geografico", "clase_activo", "subyacente", "comision",
                        "moneda", "administrador", "gestor", "liquidez", "minimo_inversion",
                    ]
                }
            )
            dist_reports.append({"intermediario": False, "tipo_intermediario": False, "comision_distribucion": False})
        except Exception as e:
            log.warning("pipeline_unexpected_error", producto=p.nombre, error=str(e))
            reports.append(
                {
                    attr: False
                    for attr in [
                        "foco_geografico", "clase_activo", "subyacente", "comision",
                        "moneda", "administrador", "gestor", "liquidez", "minimo_inversion",
                    ]
                }
            )
            dist_reports.append({"intermediario": False, "tipo_intermediario": False, "comision_distribucion": False})

    accuracy = aggregate_accuracy(reports)
    dist_accuracy = aggregate_accuracy(dist_reports)

    # Separate searchable vs non-searchable
    searchable_reports = []
    searchable_dist = []
    nonsearchable = []
    for i, detail in enumerate(per_product_details):
        if detail.get("fichas", 0) == 0 and detail.get("global_confidence", 0) < 0.01:
            nonsearchable.append(detail["nombre"])
        else:
            searchable_reports.append(reports[i])
            if i < len(dist_reports):
                searchable_dist.append(dist_reports[i])

    searchable_acc = aggregate_accuracy(searchable_reports)
    searchable_dist_acc = aggregate_accuracy(searchable_dist)

    print(f"\n=== Resultado ({version}) ===")
    print(f"Productos evaluados: {len(reports)} ({len(searchable_reports)} buscables, {len(nonsearchable)} no buscables)")

    print(f"\n--- Capa Producto (buscables: {len(searchable_reports)}) ---")
    for attr, acc in sorted(searchable_acc.items()):
        bar = "█" * int(acc * 20) + "░" * (20 - int(acc * 20))
        flag = "✓" if acc >= 0.80 else "✗"
        print(f"  {flag} {attr:20s} [{bar}] {acc:.1%}")

    print(f"\n--- Capa Distribución (buscables: {len(searchable_dist)}) ---")
    for attr, acc in sorted(searchable_dist_acc.items()):
        bar = "█" * int(acc * 20) + "░" * (20 - int(acc * 20))
        flag = "✓" if acc >= 0.50 else "✗"
        print(f"  {flag} {attr:20s} [{bar}] {acc:.1%}")

    if nonsearchable:
        print(f"\n--- No buscables ({len(nonsearchable)}) ---")
        for name in nonsearchable:
            print(f"  ⊘ {name}")

    print(f"\nCosto total: ${llm.cost.total_usd:.3f}")

    async with get_session() as s3:
        r = await s3.execute(select(RulesVersion).where(RulesVersion.version == version))
        rv = r.scalar_one_or_none()
        if rv is None:
            rv = RulesVersion(
                version=version,
                content_md=rules_md,
                notes=f"Calibración end-to-end pipeline — rules {rules_path.stem}",
            )
            s3.add(rv)
        rv.validation_accuracy = {
            "per_attribute": accuracy,
            "per_attribute_distribution": dist_accuracy,
            "n_products": len(reports),
            "total_cost_usd": llm.cost.total_usd,
            "details": per_product_details,
        }
        await s3.commit()

    if output_path:
        import json as _json
        output_data = {
            "version": version,
            "rules_path": str(rules_path),
            "fetcher_backend": get_settings().fetcher_backend,
            "n_products": len(reports),
            "per_attribute_accuracy": accuracy,
            "per_attribute_distribution_accuracy": dist_accuracy,
            "total_cost_usd": llm.cost.total_usd,
            "details": per_product_details,
        }
        Path(output_path).write_text(
            _json.dumps(output_data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"Results written to {output_path}")

    print(f"\nGuardado en rules_versions.{version}.validation_accuracy")
    min_acc = min(accuracy.values()) if accuracy else 0.0
    return 0 if min_acc >= 0.85 else 1


def cli() -> None:
    parser = argparse.ArgumentParser(description="End-to-end pipeline calibration.")
    parser.add_argument("--rules", default="rules/v8.md")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only first N validation products (smoke test; default: all 19)",
    )
    parser.add_argument(
        "--exclude-clase",
        default="",
        help=(
            "Comma-separated canonical clase_activo names to exclude. "
            "Products whose dominant ground-truth clase_activo is in this list "
            "are skipped. Typical for private funds not searchable via web: "
            "'Club deals,Inmobiliario Directo'."
        ),
    )
    parser.add_argument(
        "--only-nombres",
        default="",
        help=(
            "Comma-separated exact product nombres to include. If set, only "
            "these products are calibrated (overrides --exclude-clase)."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path to write JSON results (for compare_calibrations.py)",
    )
    args = parser.parse_args()
    sys.exit(
        asyncio.run(
            _main(
                Path(args.rules),
                dry_run=args.dry_run,
                limit=args.limit,
                exclude_clase=args.exclude_clase,
                only_nombres=args.only_nombres,
                output_path=args.output,
            )
        )
    )


if __name__ == "__main__":
    cli()
