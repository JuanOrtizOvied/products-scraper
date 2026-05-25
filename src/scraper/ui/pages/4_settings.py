"""Settings page: overlay viewer, rules selection, cost tracking."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from scraper.db.session import get_session
from scraper.overlay import load_sabbi_overlay, reload_sabbi_overlay
from scraper.ui.state import run_async

st.title("Settings")

st.subheader("Sabbi Overlay")
overlay_path = Path.cwd() / "config" / "sabbi_overlay.yaml"
st.caption(f"Archivo: `{overlay_path}`")

if overlay_path.exists():
    with open(overlay_path, encoding="utf-8") as f:
        st.code(f.read(), language="yaml")

    if st.button("Reload overlay"):
        reload_sabbi_overlay()
        st.success("Overlay recargado.")
        overlay = load_sabbi_overlay()
        st.json(overlay.model_dump())
else:
    st.warning(f"Archivo no existe: {overlay_path}")

st.divider()

st.subheader("Rules version")
rules_dir = Path.cwd() / "rules"
rules_files = sorted(rules_dir.glob("v*.md")) if rules_dir.exists() else []
if rules_files:
    st.selectbox(
        "Rules version activa",
        options=[f.name for f in rules_files],
        index=len(rules_files) - 1,
    )
    st.caption("El default del worker es `rules/v8.md`. Para cambiar, editar CLI args.")

st.divider()

st.subheader("Fuentes recientes")


async def _recent_sources():
    from sqlalchemy import select
    from scraper.db.models import Classification

    async with get_session() as s:
        r = await s.execute(
            select(Classification)
            .where(Classification.sources_used.is_not(None))
            .order_by(Classification.created_at.desc())
            .limit(20)
        )
        return list(r.scalars().all())


recent_cls = run_async(_recent_sources())
if recent_cls:
    for cls_row in recent_cls:
        sources = cls_row.sources_used or []
        for src in sources:
            icon = "🌐" if src.get("url", "").startswith("http") else "📄"
            label = src.get("label", src.get("url", "?"))
            doc_date = src.get("document_date", "")
            st.caption(f"{icon} {label} — {src.get('source_type', '')} — {doc_date or 'sin fecha'}")
else:
    st.info("No hay fuentes procesadas todavía.")

st.divider()

st.subheader("Cost tracking")


async def _cost_this_month():
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select

    from scraper.db.models import Classification

    thirty_days_ago = datetime.now(tz=UTC) - timedelta(days=30)
    async with get_session() as s:
        r = await s.execute(
            select(
                func.sum(Classification.cost_usd).label("total_cost"),
                func.count(Classification.id).label("count"),
            ).where(Classification.created_at >= thirty_days_ago)
        )
        row = r.one()
        return row.total_cost or 0.0, row.count or 0


cost, n_products = run_async(_cost_this_month())
st.metric("Total últimos 30 días (USD)", f"${cost:.2f}")
st.metric("Productos procesados (últimos 30 días)", str(n_products))
