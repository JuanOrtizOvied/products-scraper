"""Review card widget for the review queue list."""
from __future__ import annotations

import streamlit as st

from scraper.ui.components.confidence_bar import confidence_color

_FLAG_ICONS = {
    "low_quality": ("🔴", "low_quality"),
    "needs_review": ("🟡", "needs_review"),
    "auto_approvable": ("🟢", "auto_approvable"),
}


def render_review_card(
    review_id: int,
    nombre: str,
    flag: str,
    confidence: float | None,
    source_count: int,
    conflict_count: int,
    cost_usd: float,
    key_prefix: str = "",
) -> bool:
    icon, flag_label = _FLAG_ICONS.get(flag, ("⚪", flag))
    conf = confidence or 0.0
    color = confidence_color(conf)
    pct = int(conf * 100)

    with st.container(border=True):
        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown(f"{icon} **{flag_label}**")
            st.markdown(f"**{nombre}**")

            meta_parts = [f"📄 {source_count} fuente{'s' if source_count != 1 else ''}"]
            if conflict_count > 0:
                meta_parts.append(f"⚠ {conflict_count} conflicto{'s' if conflict_count != 1 else ''}")
            meta_parts.append(f"${cost_usd:.3f}")
            st.caption(" · ".join(meta_parts))

        with col2:
            st.markdown(
                f'<div style="text-align:right">'
                f'<span style="font-size:1.5em;color:{color}">{conf:.2f}</span>'
                f'<div style="background:#e5e7eb;border-radius:4px;height:6px;margin-top:4px">'
                f'<div style="background:{color};width:{pct}%;height:6px;border-radius:4px"></div>'
                f"</div></div>",
                unsafe_allow_html=True,
            )

        clicked = st.button("Ver detalle", key=f"{key_prefix}_card_{review_id}")
    return clicked
