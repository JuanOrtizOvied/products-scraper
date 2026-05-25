"""Expandable source citation widget."""
from __future__ import annotations

import streamlit as st


def render_source_citation(
    source_url: str | None,
    source_label: str | None,
    raw_quote: str | None,
    key_suffix: str = "",
) -> None:
    if not source_url and not source_label:
        return
    icon = "🌐" if source_url and source_url.startswith("http") else "📄"
    display = source_label or source_url or ""
    if source_url and source_url.startswith("http"):
        st.caption(f"{icon} [{display}]({source_url})")
    else:
        st.caption(f"{icon} {display}")
    if raw_quote:
        with st.expander("Ver evidencia", expanded=False):
            st.markdown(f'> "{raw_quote}"')
