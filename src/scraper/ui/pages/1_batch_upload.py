"""Batch CSV upload page."""
from __future__ import annotations

from io import StringIO

import pandas as pd
import streamlit as st

from scraper.db.session import get_session
from scraper.ui.batch_ops import create_batch, parse_products_csv
from scraper.ui.state import run_async

st.title("Batch Upload")
st.markdown(
    "Subí un CSV con columnas:\n"
    "- `nombre` (obligatoria)\n"
    "- `pdf_path` (opcional) — ruta local al PDF\n"
    "- `url` (opcional) — URL específica\n\n"
    "Si solo hay `nombre`, se usa la cascade de search."
)

uploaded = st.file_uploader("Seleccioná un CSV", type=["csv"])

if uploaded is not None:
    text = uploaded.read().decode("utf-8")
    try:
        rows = parse_products_csv(StringIO(text))
    except ValueError as e:
        st.error(f"Error en CSV: {e}")
        st.stop()

    st.success(f"CSV válido: {len(rows)} productos.")
    st.dataframe(pd.DataFrame(rows))

    if st.button("Crear batch y encolar jobs", type="primary"):

        async def _create():
            async with get_session() as s:
                return await create_batch(s, rows)

        batch_id = run_async(_create())
        st.success(
            f"Batch creado con id `{batch_id[:8]}...`. "
            f"{len(rows)} jobs en cola. Corré el worker para procesar:\n\n"
            "```bash\npoetry run python -m scraper.scripts.worker\n```"
        )

st.divider()
st.subheader("Últimos batches")


async def _recent_batches():
    from sqlalchemy import case, func, select

    from scraper.db.models import JobQueue

    async with get_session() as s:
        r = await s.execute(
            select(
                JobQueue.batch_id,
                func.count(JobQueue.id).label("total"),
                func.sum(case((JobQueue.status == "done", 1), else_=0)).label("done_count"),
                func.sum(case((JobQueue.status == "in_progress", 1), else_=0)).label("in_progress_count"),
                func.sum(case((JobQueue.status == "failed", 1), else_=0)).label("failed_count"),
                func.min(JobQueue.created_at).label("created_at"),
            )
            .where(JobQueue.batch_id.is_not(None))
            .group_by(JobQueue.batch_id)
            .order_by(func.min(JobQueue.created_at).desc())
            .limit(10)
        )
        return r.all()


batches = run_async(_recent_batches())
if batches:
    for row in batches:
        total = row.total
        done = row.done_count or 0
        in_prog = row.in_progress_count or 0
        failed = row.failed_count or 0
        pending = total - done - in_prog - failed
        pct = done / total if total > 0 else 0

        with st.container(border=True):
            st.markdown(f"**Batch {row.batch_id[:8]}...** — {total} productos")
            st.progress(pct)
            st.caption(
                f"✅ {done} completados · ⏳ {in_prog} en proceso · "
                f"📋 {pending} pendientes · ❌ {failed} fallidos"
            )
else:
    st.info("No hay batches todavía.")
