async def test_reclassify_with_pdf_creates_new_job(seeded_and_split_session, tmp_path):
    from sqlalchemy import select

    from scraper.db.models import JobQueue
    from scraper.ui.upload_ops import reclassify_with_pdf

    pdf_file = tmp_path / "ficha.pdf"
    pdf_file.write_bytes(b"%PDF-1.5 test")

    job_id = await reclassify_with_pdf(
        seeded_and_split_session,
        nombre="Producto X",
        pdf_bytes=pdf_file.read_bytes(),
        operator="test_op",
    )

    r = await seeded_and_split_session.execute(
        select(JobQueue).where(JobQueue.id == job_id)
    )
    job = r.scalar_one()
    assert job.nombre == "Producto X"
    assert job.pdf_path is not None
    assert job.status == "pending"
