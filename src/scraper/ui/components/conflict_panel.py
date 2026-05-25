"""Panel showing field conflicts with alternative value selector."""
from __future__ import annotations

from typing import Any

import streamlit as st


def _format_alt(alt: dict) -> str:
    source_label = alt.get("source_label", alt.get("source_url", "?"))
    doc_date = alt.get("document_date", "")
    date_str = f" ({doc_date})" if doc_date else ""
    val = alt.get("value")
    return f"{source_label}{date_str}: {val!r}"


def render_conflict_panel(
    attribute: str,
    alternatives: list[dict],
    key_prefix: str = "",
) -> Any | None:
    if not alternatives:
        return None

    labels = ["Mantener valor actual"] + [_format_alt(a) for a in alternatives]

    choice = st.selectbox(
        f"Valor alternativo para {attribute.replace('_', ' ')}",
        options=range(len(labels)),
        format_func=lambda i: labels[i],
        key=f"{key_prefix}_conflict_select_{attribute}",
    )

    if choice and choice > 0:
        alt = alternatives[choice - 1]
        raw_quote = alt.get("raw_quote", "")
        if raw_quote:
            st.caption(f'Evidencia: "{raw_quote}"')
        return alt["value"]

    for alt in alternatives:
        source_label = alt.get("source_label", alt.get("source_url", "?"))
        raw_quote = alt.get("raw_quote", "")
        icon = "🌐" if alt.get("source_url", "").startswith("http") else "📄"
        st.caption(f"{icon} {source_label}: `{alt['value']!r}`")
        if raw_quote:
            st.caption(f'  "{raw_quote}"')

    return None
