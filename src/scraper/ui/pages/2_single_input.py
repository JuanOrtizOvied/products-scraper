"""Single product classification input."""
from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

from scraper.db.models import JobQueue
from scraper.db.session import get_session
from scraper.ui.state import run_async

st.title("Clasificar un producto")

nombre = st.text_input("Nombre del producto", placeholder="ej. Credicorp Crecimiento")

with st.expander("Opciones avanzadas (skip cascade)"):
    url = st.text_input(
        "URL específica",
        placeholder="https://...",
        help="Si tenés la URL de la ficha, pipeline la usa directo sin buscar.",
    )
    pdf_upload = st.file_uploader("Subí un PDF de ficha técnica", type=["pdf"])

if st.button("Clasificar", type="primary", disabled=not nombre):
    pdf_path = None
    if pdf_upload is not None:
        uploads_dir = Path.cwd() / "data" / "uploaded_pdfs"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        data = pdf_upload.read()
        h = hashlib.sha256(data).hexdigest()[:16]
        pdf_path = str(uploads_dir / f"{h}.pdf")
        if not os.path.exists(pdf_path):
            Path(pdf_path).write_bytes(data)

    async def _enqueue():
        async with get_session() as s:
            job = JobQueue(
                nombre=nombre.strip(),
                pdf_path=pdf_path,
                url=url.strip() or None if url else None,
                status="pending",
                created_at=datetime.now(tz=UTC),
            )
            s.add(job)
            await s.commit()
            await s.refresh(job)
            return job.id

    job_id = run_async(_enqueue())
    st.success(
        f"Job #{job_id} encolado. Va a aparecer en la Review Queue cuando el worker lo procese.\n\n"
        "```bash\npoetry run python -m scraper.scripts.worker\n```"
    )
