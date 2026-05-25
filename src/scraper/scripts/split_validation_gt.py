"""Split validation-set ground truth into product + distribution layers.

For each of the 19 validation products, populate the two-layer columns:
  - Product layer: administrador_producto, gestor_producto, comision_producto,
    minimo_inversion_producto, liquidez_producto
  - Distribution layer: intermediario, tipo_intermediario, comision_distribucion,
    minimo_via_intermediario, liquidez_via_intermediario

Products in the override map get real product-level data separated from the
distribution/intermediary data.  Products NOT in the map get their existing
values copied to both layers (product == distribution).
"""
from __future__ import annotations

import argparse
import asyncio
import sys

import structlog
from sqlalchemy import select

from scraper.db.models import Product, ValidationSet
from scraper.db.session import get_session

log = structlog.get_logger()

# ── Override map ────────────────────────────────────────────────────────
# Keys = product nombre (exact match).
# Values = dict of overrides for the PRODUCT layer + tipo_intermediario.
# The DISTRIBUTION layer is always populated from existing columns.
OVERRIDES: dict[str, dict] = {
    # ── BVL stocks (Credicorp Capital as broker) ──
    "INVCENC1 - Credicorp Capital": {
        "administrador_producto": "Cementos Pacasmayo S.A.A.",
        "gestor_producto": "Cementos Pacasmayo S.A.A.",
        "comision_producto": 0.0,
        "tipo_intermediario": "broker",
    },
    "IPCHBC1 - Credicorp Capital": {
        "administrador_producto": "Inversiones Portuarias Chancay S.A.A.",
        "gestor_producto": "Inversiones Portuarias Chancay S.A.A.",
        "comision_producto": 0.0,
        "tipo_intermediario": "broker",
    },
    "LUSURC1 - Credicorp Capital": {
        "administrador_producto": "Luz del Sur S.A.A.",
        "gestor_producto": "Luz del Sur S.A.A.",
        "comision_producto": 0.0,
        "tipo_intermediario": "broker",
    },
    "MINSURI1 - Credicorp Capital": {
        "administrador_producto": "Compañía Minera Minsur S.A.",
        "gestor_producto": "Compañía Minera Minsur S.A.",
        "comision_producto": 0.0,
        "tipo_intermediario": "broker",
    },
    "BACKUSI1 - Credicorp Capital": {
        "administrador_producto": "Unión de Cervecerías Peruanas Backus y Johnston S.A.A.",
        "gestor_producto": "Unión de Cervecerías Peruanas Backus y Johnston S.A.A.",
        "comision_producto": 0.0,
        "tipo_intermediario": "broker",
    },
    # ── International stocks via Credicorp (broker) ──
    "AMERICAN EXPRESS CO - AXP": {
        "administrador_producto": "American Express Company",
        "gestor_producto": "American Express Company",
        "comision_producto": 0.0,
        "tipo_intermediario": "broker",
    },
    "CITIGROUP INC - C": {
        "administrador_producto": "Citigroup Inc.",
        "gestor_producto": "Citigroup Inc.",
        "comision_producto": 0.0,
        "tipo_intermediario": "broker",
    },
    "JPM NASDAQ EQUITY PREMIUM": {
        "administrador_producto": "J.P. Morgan Asset Management",
        "gestor_producto": "J.P. Morgan Asset Management",
        "comision_producto": 0.0035,
        "tipo_intermediario": "broker",
    },
    "PROCTER & GAMBLE CO/THE - PG": {
        "administrador_producto": "The Procter & Gamble Company",
        "gestor_producto": "The Procter & Gamble Company",
        "comision_producto": 0.0,
        "tipo_intermediario": "broker",
    },
    # ── International funds via UBS (custodian) ──
    "JPM Emerging Markets Equity Fund – MFLJEA": {
        "administrador_producto": "JPMorgan Funds (Asia) Limited",
        "gestor_producto": "J.P. Morgan Asset Management",
        "comision_producto": 0.015,
        "tipo_intermediario": "custodio",
    },
    "Lord Abbett Innovation Fund – MFXJCE": {
        "administrador_producto": "Lord Abbett Global Funds I plc",
        "gestor_producto": "Lord Abbett",
        "comision_producto": 0.018,
        "tipo_intermediario": "custodio",
    },
    "Alibaba Group Holding ADR – BABA": {
        "administrador_producto": "Alibaba Group Holding Limited",
        "gestor_producto": "Alibaba Group Holding Limited",
        "comision_producto": 0.0,
        "tipo_intermediario": "custodio",
    },
    "Petrobras ADR – PBR": {
        "administrador_producto": "Petrobras",
        "gestor_producto": "Petrobras",
        "comision_producto": 0.0,
        "tipo_intermediario": "custodio",
    },
    "iShares 1–3 Year Treasury Bond ETF – SHY": {
        "administrador_producto": "BlackRock",
        "gestor_producto": "BlackRock Fund Advisors",
        "comision_producto": 0.0015,
        "tipo_intermediario": "custodio",
    },
    "JPM US Aggregate Bond Fund – MFLJEH": {
        "administrador_producto": "JPMorgan Asset Management (Europe) S.à r.l.",
        "gestor_producto": "J.P. Morgan Asset Management",
        "comision_producto": 0.009,
        "tipo_intermediario": "custodio",
    },
    # ── Peruvian funds / club deals (product == distribution) ──
    "Tyba - CC Liquidez Dolares": {
        "tipo_intermediario": "safi",
    },
    "Core Capital SAFI - Fondo Habilitador - Blackstone Private Credit Fund": {
        "tipo_intermediario": "safi",
    },
    "Promociones Turisticas del Sur": {
        "tipo_intermediario": "directo",
    },
    "S&T COMUNICACIÓN INTEGRAL SAC": {
        "tipo_intermediario": "directo",
    },
}


async def run_split(*, dry_run: bool = False) -> int:
    """Populate two-layer columns for all validation products.

    Returns count of products updated.
    """
    updated = 0
    async with get_session() as session:
        # Fetch all validation product ids
        val_rows = await session.execute(select(ValidationSet))
        val_ids = [row.product_id for row in val_rows.scalars().all()]
        log.info("validation_products_found", count=len(val_ids))

        # Fetch the actual product rows
        result = await session.execute(
            select(Product).where(Product.id.in_(val_ids))
        )
        products = list(result.scalars().all())

        for p in products:
            override = OVERRIDES.get(p.nombre)

            if override and "administrador_producto" in override:
                # Product has real overrides — split layers
                p.administrador_producto = override.get("administrador_producto")
                p.gestor_producto = override.get("gestor_producto")
                p.comision_producto = override.get("comision_producto")
                p.minimo_inversion_producto = None
                p.liquidez_producto = None
                # Distribution layer = existing intermediary values
                p.intermediario = p.administrador
                p.tipo_intermediario = override["tipo_intermediario"]
                p.comision_distribucion = p.comision
                p.minimo_via_intermediario = p.minimo_inversion
                p.liquidez_via_intermediario = p.liquidez
            else:
                # No override (or only tipo) — product == distribution
                tipo = override["tipo_intermediario"] if override else "safi"
                p.administrador_producto = p.administrador
                p.gestor_producto = p.gestor
                p.comision_producto = p.comision
                p.minimo_inversion_producto = p.minimo_inversion
                p.liquidez_producto = p.liquidez
                # Distribution layer mirrors product layer
                p.intermediario = p.administrador
                p.tipo_intermediario = tipo
                p.comision_distribucion = p.comision
                p.minimo_via_intermediario = p.minimo_inversion
                p.liquidez_via_intermediario = p.liquidez

            updated += 1
            log.info(
                "product_split",
                nombre=p.nombre,
                admin_prod=p.administrador_producto,
                gestor_prod=p.gestor_producto,
                comision_prod=p.comision_producto,
                intermediario=p.intermediario,
                tipo=p.tipo_intermediario,
                dry_run=dry_run,
            )

        if dry_run:
            await session.rollback()
            log.info("dry_run_rollback", count=updated)
        else:
            await session.commit()
            log.info("split_committed", count=updated)

    return updated


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(
        description="Split validation ground truth into product + distribution layers",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing to the database",
    )
    args = parser.parse_args()
    count = asyncio.run(run_split(dry_run=args.dry_run))
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Updated {count} validation products.")


if __name__ == "__main__":
    main()
