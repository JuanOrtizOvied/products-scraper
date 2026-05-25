"""Analyze training_set and print patterns to inform rules v1 drafting.

This does NOT auto-generate rules — it surfaces patterns for human drafting.

Usage:
    poetry run python -m scraper.scripts.bootstrap_rules_v1
"""
from __future__ import annotations

import asyncio
import sys
from collections import Counter, defaultdict

from sqlalchemy import select

from scraper.db.models import Product, TrainingSet
from scraper.db.session import get_session
from scraper.taxonomies.normalizer import normalize_asset_class

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


async def _main() -> None:
    async with get_session() as s:
        r = await s.execute(
            select(Product).join(TrainingSet, Product.id == TrainingSet.product_id)
        )
        products = list(r.scalars().all())

    print(f"\n=== Training set: {len(products)} productos ===\n")

    # 1. Distribución por dominant macro class
    dominant: Counter = Counter()
    for p in products:
        if not p.clase_activo:
            continue
        dom = max(p.clase_activo.items(), key=lambda kv: kv[1])[0]
        dominant[normalize_asset_class(dom) or dom] += 1
    print("Distribución por clase macro dominante:")
    for k, v in dominant.most_common():
        print(f"  {k}: {v}")

    # 2. Subyacentes canónicos más usados
    subyacente_counts: Counter = Counter()
    for p in products:
        for k in p.subyacentes.keys():
            subyacente_counts[k] += 1
    print("\nTop 15 subyacentes más frecuentes:")
    for k, v in subyacente_counts.most_common(15):
        print(f"  {k}: {v}")

    # 3. Patrones administrador → clase macro
    admin_to_classes: dict[str, Counter] = defaultdict(Counter)
    for p in products:
        if not p.administrador or not p.clase_activo:
            continue
        dom = max(p.clase_activo.items(), key=lambda kv: kv[1])[0]
        admin_to_classes[p.administrador][normalize_asset_class(dom) or dom] += 1
    print("\nAdministradores y clases típicas:")
    for admin, classes in sorted(admin_to_classes.items()):
        top = ", ".join(f"{c}:{n}" for c, n in classes.most_common(3))
        print(f"  {admin}: {top}")

    # 4. Liquidez × clase macro
    liq_to_class: dict[str, Counter] = defaultdict(Counter)
    for p in products:
        if not p.liquidez or not p.clase_activo:
            continue
        dom = max(p.clase_activo.items(), key=lambda kv: kv[1])[0]
        liq_to_class[p.liquidez.lower()][normalize_asset_class(dom) or dom] += 1
    print("\nLiquidez → clase típica:")
    for liq, cs in sorted(liq_to_class.items()):
        top = ", ".join(f"{c}:{n}" for c, n in cs.most_common(2))
        print(f"  {liq}: {top}")


if __name__ == "__main__":
    asyncio.run(_main())
