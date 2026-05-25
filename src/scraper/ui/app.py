"""Streamlit entry point for Sabbi Classifier HITL review UI.

Run with: poetry run streamlit run src/scraper/ui/app.py
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="Sabbi Classifier",
    layout="wide",
)

st.title("Sabbi Classifier")
st.markdown(
    "Navegá desde el sidebar:\n\n"
    "- **Batch Upload**: subí un CSV de productos para procesar en background\n"
    "- **Single Input**: clasificá un producto individual\n"
    "- **Review Queue**: revisá y aprobá clasificaciones pendientes\n"
    "- **Settings**: config del Sabbi overlay, rules version, cost tracking\n\n"
    "Para procesar jobs del batch upload, corré el worker en otra terminal:\n\n"
    "```bash\npoetry run python -m scraper.scripts.worker\n```"
)
