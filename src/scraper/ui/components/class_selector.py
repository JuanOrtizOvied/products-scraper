"""Selector widget for products with multiple share classes (A, B, etc.)."""
from __future__ import annotations

from typing import Any

import streamlit as st


def render_class_selector(
    class_options: list[dict[str, Any]],
    key_prefix: str = "",
) -> dict[str, Any] | None:
    """Render radio buttons for each share class. Returns the selected class dict or None."""
    if not class_options:
        return None

    st.markdown("### Seleccionar clase del producto")
    st.caption("Este producto tiene múltiples clases con diferentes comisiones y mínimos.")

    labels = []
    for opt in class_options:
        clase = opt.get("clase", "?")
        comision_raw = opt.get("comision_raw", "")
        comision = opt.get("comision")
        minimo = opt.get("minimo_inversion", "?")
        fee_display = comision_raw or (f"{comision * 100:.2f}%" if comision else "?")
        labels.append(f"{clase} — Comisión: {fee_display} — Mínimo: {minimo}")

    selected_idx = st.radio(
        "Clase",
        options=range(len(labels)),
        format_func=lambda i: labels[i],
        key=f"{key_prefix}class_selector",
        label_visibility="collapsed",
    )

    if selected_idx is not None:
        return class_options[selected_idx]
    return None
