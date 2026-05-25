"""Colored confidence bar widget for Streamlit."""
from __future__ import annotations

import streamlit as st


def confidence_color(value: float) -> str:
    if value >= 0.85:
        return "#22c55e"
    if value >= 0.70:
        return "#eab308"
    return "#ef4444"


def confidence_label(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}"


def render_confidence_bar(value: float | None, label: str = "") -> None:
    if value is None:
        st.caption(f"{label} Confianza: —")
        return
    color = confidence_color(value)
    pct = int(value * 100)
    st.markdown(
        f"{label} Confianza: **{value:.2f}**"
        f'<div style="background:#e5e7eb;border-radius:4px;height:8px;margin-top:2px">'
        f'<div style="background:{color};width:{pct}%;height:8px;border-radius:4px"></div>'
        f"</div>",
        unsafe_allow_html=True,
    )
