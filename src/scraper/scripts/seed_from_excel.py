"""Seed products table from BD_Productos Sabbi.xlsx.

Uses sheet 'Base' as source of truth. Handles NaN values gracefully
(incomplete products stored with status='incomplete').
"""
from __future__ import annotations

import asyncio
import math
import sys
from pathlib import Path

import pandas as pd
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.db.models import Product
from scraper.db.session import get_session
from scraper.parsers import parse_percentages

log = structlog.get_logger()

# Expected column names in sheet "Base" after header=2.
# NOTE: spelling must match exactly — including trailing spaces.
EXPECTED_COLUMNS = {
    "nombre": "Nombre de Producto",
    "foco": "Foco Geografico (porcentaje)",
    "clase": "Clase de Activo (porcentaje)",
    "subyacente": "Subyacente (porcentaje)",
    "comision": "Comision (sin IGV)",
    "moneda": "moneda (USD o Soles)",
    "admin": "Nombre Administrador",
    "gestor": "Nombre Gestor",
    "liquidez": "Liquidez ",  # trailing space observed in real Excel
}


def _validate_columns(df: pd.DataFrame) -> None:
    """Raise if any expected column is missing."""
    missing = [
        name for name in EXPECTED_COLUMNS.values() if name not in df.columns
    ]
    if missing:
        raise ValueError(
            f"Excel 'Base' sheet missing expected columns: {missing}. "
            f"Actual columns: {list(df.columns)}"
        )


def _str_or_none(v: object) -> str | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).strip()
    return s if s and s.lower() != "nan" else None


def _parse_comision(raw: str | None) -> tuple[float | None, str | None]:
    """Return (numeric_value_if_parseable, raw_string_always)."""
    if raw is None:
        return None, None
    s = str(raw).strip()
    if not s:
        return None, None
    try:
        return float(s), s
    except ValueError:
        pass
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100.0, s
        except ValueError:
            pass
    return None, s


async def seed_products(session: AsyncSession, excel_path: Path) -> int:
    """Load Base sheet into products table. Returns # of rows inserted.

    Rows where the name column is empty are skipped. Rows where name exists
    but clase_activo/foco/subyacente are NaN are inserted with status='incomplete'.
    Idempotent: re-running skips products that already exist (by nombre).
    """
    df = pd.read_excel(excel_path, sheet_name="Base", header=2)
    df = df.dropna(subset=[EXPECTED_COLUMNS["nombre"]])
    _validate_columns(df)
    col_map = EXPECTED_COLUMNS

    inserted = 0
    for _, row in df.iterrows():
        nombre = _str_or_none(row[col_map["nombre"]])
        if not nombre:
            continue

        # idempotency — skip if exists
        exists = await session.execute(select(Product).where(Product.nombre == nombre))
        if exists.scalar_one_or_none() is not None:
            continue

        foco = parse_percentages(_str_or_none(row[col_map["foco"]]))
        clase = parse_percentages(_str_or_none(row[col_map["clase"]]))
        subyacente = parse_percentages(_str_or_none(row[col_map["subyacente"]]))
        comision_num, comision_raw = _parse_comision(_str_or_none(row[col_map["comision"]]))

        is_complete = bool(foco and clase and subyacente)

        p = Product(
            nombre=nombre,
            foco_geografico=foco,
            clase_activo=clase,
            subyacentes=subyacente,
            comision=comision_num,
            comision_raw=comision_raw,
            moneda=_str_or_none(row[col_map["moneda"]]),
            administrador=_str_or_none(row[col_map["admin"]]),
            gestor=_str_or_none(row[col_map["gestor"]]),
            liquidez=_str_or_none(row[col_map["liquidez"]]),
            source_type="excel_seed",
            status="active" if is_complete else "incomplete",
        )
        session.add(p)
        inserted += 1

    await session.commit()
    log.info("seed_completed", inserted=inserted, source=str(excel_path))
    return inserted


async def _main(excel_path: Path) -> None:
    async with get_session() as s:
        count = await seed_products(s, excel_path)
        print(f"Seeded {count} products from {excel_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m scraper.scripts.seed_from_excel <path-to-xlsx>")
        sys.exit(1)
    asyncio.run(_main(Path(sys.argv[1])))
