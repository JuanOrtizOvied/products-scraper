from io import StringIO


async def test_parse_csv_returns_list_of_products():
    from scraper.ui.batch_ops import parse_products_csv

    csv_text = "nombre,pdf_path,url\nProducto A,,\nProducto B,/path/to.pdf,\nProducto C,,https://x.com\n"
    rows = parse_products_csv(StringIO(csv_text))
    assert len(rows) == 3
    assert rows[0]["nombre"] == "Producto A"
    assert rows[0]["pdf_path"] is None
    assert rows[1]["pdf_path"] == "/path/to.pdf"
    assert rows[2]["url"] == "https://x.com"


async def test_parse_csv_requires_nombre_column():
    import pytest as _pt

    from scraper.ui.batch_ops import parse_products_csv

    csv_text = "title,foo\nA,B\n"
    with _pt.raises(ValueError, match="nombre"):
        parse_products_csv(StringIO(csv_text))


async def test_parse_csv_rejects_empty_nombre():
    import pytest as _pt

    from scraper.ui.batch_ops import parse_products_csv

    csv_text = "nombre\nProducto A\n \nProducto B\n"
    with _pt.raises(ValueError, match="empty"):
        parse_products_csv(StringIO(csv_text))


async def test_create_batch_inserts_jobs(seeded_and_split_session):
    from sqlalchemy import select

    from scraper.db.models import JobQueue
    from scraper.ui.batch_ops import create_batch

    rows = [
        {"nombre": "A", "pdf_path": None, "url": None},
        {"nombre": "B", "pdf_path": "/tmp/b.pdf", "url": None},
    ]
    batch_id = await create_batch(seeded_and_split_session, rows)
    assert batch_id is not None

    r = await seeded_and_split_session.execute(
        select(JobQueue).where(JobQueue.batch_id == batch_id)
    )
    jobs = list(r.scalars().all())
    assert len(jobs) == 2
    assert all(j.status == "pending" for j in jobs)
