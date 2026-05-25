"""N0 - lookup by product name in local DB using fuzzy matching."""
from __future__ import annotations

from datetime import UTC, datetime

import structlog
from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.agents.types import AttributeExtraction, ExtractedFicha
from scraper.db.models import Product

log = structlog.get_logger()

_FUZZY_THRESHOLD = 85.0


def _product_to_ficha(p: Product) -> ExtractedFicha:
    def ae(value, conf: float = 1.0, note: str = "from DB") -> AttributeExtraction:
        return AttributeExtraction(value=value, confidence=conf, reasoning=note, raw_quote=None)

    return ExtractedFicha(
        source_url=p.source_url,
        source_type="db",
        source_confidence=1.0,
        fetched_at=datetime.now(tz=UTC),
        raw_text=f"Producto: {p.nombre}",
        tables=[],
        attributes={
            "nombre": ae(p.nombre),
            "foco_geografico": ae(p.foco_geografico or {}),
            "clase_activo": ae(p.clase_activo or {}),
            "subyacente": ae(p.subyacentes or {}),
            "comision": ae(p.comision if p.comision is not None else p.comision_raw),
            "moneda": ae(p.moneda),
            "administrador": ae(p.administrador),
            "gestor": ae(p.gestor),
            "liquidez": ae(p.liquidez),
            "minimo_inversion": ae(p.minimo_inversion),
        },
        citations=[f"db://products/{p.id}"],
        extraction_cost_usd=0.0,
        extraction_duration_ms=0,
    )


async def lookup_db(nombre: str, session: AsyncSession | None) -> ExtractedFicha | None:
    """Fuzzy lookup of product name in DB. Returns the top match >= threshold, else None."""
    if session is None:
        return None

    r = await session.execute(select(Product))
    products = list(r.scalars().all())
    if not products:
        return None

    name_to_product = {p.nombre: p for p in products}
    match = process.extractOne(nombre, list(name_to_product.keys()), scorer=fuzz.ratio)
    if match is None:
        return None
    matched_name, score, _ = match
    if score < _FUZZY_THRESHOLD:
        log.info("level0_no_match", nombre=nombre, best=matched_name, score=score)
        return None

    p = name_to_product[matched_name]
    log.info("level0_match", nombre=nombre, matched=matched_name, score=score)
    return _product_to_ficha(p)
