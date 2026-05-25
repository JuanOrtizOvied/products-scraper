"""Visual table editor for percentage dictionaries + unified edit_attribute."""
from __future__ import annotations

import json
from typing import Any

import streamlit as st


def normalize_pct_dict(d: dict[str, float]) -> dict[str, float]:
    return {k: float(v) for k, v in d.items() if float(v) > 0}


def render_dict_editor(
    label: str,
    current_value: dict[str, float],
    key_prefix: str = "",
) -> dict[str, float]:
    if not isinstance(current_value, dict):
        current_value = {}

    if f"{key_prefix}_rows" not in st.session_state:
        st.session_state[f"{key_prefix}_rows"] = list(current_value.items())

    rows = st.session_state[f"{key_prefix}_rows"]
    edited: dict[str, float] = {}

    for i, (name, pct) in enumerate(rows):
        col_name, col_pct, col_del = st.columns([3, 1, 0.5])
        with col_name:
            new_name = st.text_input(
                "Nombre", value=name, key=f"{key_prefix}_name_{i}", label_visibility="collapsed"
            )
        with col_pct:
            new_pct = st.number_input(
                "%", value=float(pct), min_value=0.0, max_value=100.0,
                step=1.0, key=f"{key_prefix}_pct_{i}", label_visibility="collapsed"
            )
        with col_del:
            if st.button("✕", key=f"{key_prefix}_del_{i}"):
                rows.pop(i)
                st.session_state[f"{key_prefix}_rows"] = rows
                st.rerun()
        if new_name and new_pct > 0:
            edited[new_name] = new_pct
        rows[i] = (new_name, new_pct)

    if st.button("+ Agregar fila", key=f"{key_prefix}_add"):
        rows.append(("", 0.0))
        st.session_state[f"{key_prefix}_rows"] = rows
        st.rerun()

    total = sum(edited.values())
    if abs(total - 100) > 2 and edited:
        st.warning(f"Total: {total:.0f}% (debe sumar 100%)")

    return normalize_pct_dict(edited)


_DICT_ATTRS = {"foco_geografico", "clase_activo", "subyacente"}


def edit_attribute(
    key: str, current_value: Any, confidence: float | None = None, reasoning: str = "",
    source_url: str | None = None, source_label: str | None = None,
    raw_quote: str | None = None, conflict: dict | None = None,
    attr_name: str | None = None,
) -> Any:
    from scraper.ui.components.confidence_bar import render_confidence_bar
    from scraper.ui.components.source_citation import render_source_citation
    from scraper.ui.components.conflict_panel import render_conflict_panel

    name = attr_name or key
    label = name.replace("_", " ").title()

    render_confidence_bar(confidence, label)

    if isinstance(current_value, dict) and name in _DICT_ATTRS:
        result = render_dict_editor(label, current_value, key_prefix=f"edit_{key}")
    elif isinstance(current_value, dict):
        new_text = st.text_area(
            label, value=json.dumps(current_value, ensure_ascii=False, indent=2),
            height=100, key=f"edit_{key}",
        )
        try:
            result = json.loads(new_text)
        except json.JSONDecodeError:
            st.warning(f"{label}: JSON inválido, usando valor original")
            result = current_value
    elif current_value is None:
        new_val = st.text_input(f"{label} (vacío)", value="", key=f"edit_{key}")
        result = new_val or None
    else:
        new_val = st.text_input(label, value=str(current_value), key=f"edit_{key}")
        result = new_val

    render_source_citation(source_url, source_label, raw_quote, key_suffix=key)

    if conflict:
        alt_chosen = render_conflict_panel(name, conflict.get("alternatives", []), key_prefix=f"edit_{key}")
        if alt_chosen is not None:
            result = alt_chosen

    if reasoning:
        st.caption(f"Razón: {reasoning[:200]}")

    return result
