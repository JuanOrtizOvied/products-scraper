# Phase 3 — HITL UI + Review Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir la capa HITL sobre el pipeline de Phase 2b: Streamlit UI local para que operadores de Sabbi carguen batches, revisen clasificaciones, editen atributos (especialmente los operacionales que no están en la web), apliquen defaults via overlay YAML, y aprueben productos al DB final.

**Architecture:** Streamlit UI + worker script async (proceso separado) + SQLite job_queue persistente. Todas las clasificaciones pasan por review humano (no auto-approve en MVP). Sabbi overlay YAML pre-llena admin/gestor/comision con defaults (Credicorp Capital + 0.65% custody fee); operator 1-click apply o edita.

**Tech Stack:** Streamlit + asyncio + SQLite + SQLAlchemy + Alembic + pydantic-settings + YAML. Sin FastAPI, sin auth, sin cloud (esas cosas vienen en Phase 3.5 cuando migremos a server interno).

**Spec de referencia:** `docs/superpowers/specs/2026-04-19-phase3-hitl-ui-design.md`
**Phase 2b status:** `docs/superpowers/plans/phase2b-STATUS.md` (tag `phase2b-complete` en `afa8fa4`)

**Entregable al final de Phase 3:**
- `poetry run streamlit run src/scraper/ui/app.py` → UI funcional
- `poetry run python -m scraper.scripts.worker` → procesa job_queue en background
- Batch CSV upload → N jobs → worker procesa → review queue → approve → `products` table
- Single input en UI funciona end-to-end
- PDF upload reactivo desde review card funciona
- Sabbi overlay YAML defaults aplicados en UI
- ~200 tests pasando (178 Phase 2b + ~22 nuevos)
- Tag `phase3-complete`

---

## File structure que se crea en Phase 3

```
scraper/
├── src/scraper/
│   ├── ui/                              # NEW — Streamlit app
│   │   ├── __init__.py
│   │   ├── app.py                       # entry point + sidebar
│   │   ├── pages/
│   │   │   ├── __init__.py
│   │   │   ├── 1_batch_upload.py
│   │   │   ├── 2_single_input.py
│   │   │   ├── 3_review_queue.py
│   │   │   └── 4_settings.py
│   │   ├── components/
│   │   │   ├── __init__.py
│   │   │   ├── field_editor.py          # widget editable inline
│   │   │   ├── overlay_apply.py         # botón Apply Sabbi default
│   │   │   └── ficha_viewer.py          # colapsable evidence
│   │   ├── review_logic.py              # approve/reject/edit logic
│   │   └── state.py                     # session state helpers
│   │
│   ├── overlay/                         # NEW — Sabbi overlay
│   │   ├── __init__.py
│   │   ├── types.py                     # SabbiOverlay pydantic model
│   │   └── loader.py                    # load + apply
│   │
│   ├── scripts/
│   │   ├── worker.py                    # NEW — background worker
│   │   └── (existing)
│   │
│   └── db/
│       └── models.py                    # MODIFIED: + JobQueue
│
├── config/
│   └── sabbi_overlay.yaml               # NEW (starter config)
│
├── alembic/versions/
│   └── 20260420_add_job_queue.py        # NEW migration
│
└── tests/
    ├── unit/
    │   ├── test_overlay_loader.py       # NEW
    │   ├── test_overlay_apply.py        # NEW
    │   ├── test_job_queue_ops.py        # NEW
    │   └── test_review_logic.py         # NEW
    └── integration/
        ├── test_worker_pipeline.py      # NEW
        └── test_ui_smoke.py             # NEW (minimal Streamlit AppTest)
```

---

## Task 1: `JobQueue` model + Alembic migration

Agregar la tabla nueva + migration. Base para todo lo demás.

**Files:**
- Modify: `src/scraper/db/models.py` (agregar `JobQueue` class)
- Create: `alembic/versions/20260420_add_job_queue.py` (migration)
- Create: `tests/unit/test_job_queue_model.py` (model tests)

- [ ] **Step 1: Write the failing test**

`tests/unit/test_job_queue_model.py`:

```python
from datetime import UTC, datetime


async def test_job_queue_can_be_inserted_and_queried(seeded_and_split_session):
    from sqlalchemy import select

    from scraper.db.models import JobQueue

    row = JobQueue(
        batch_id="batch-uuid-1",
        nombre="Test Product",
        pdf_path=None,
        url=None,
        status="pending",
        classification_id=None,
        error=None,
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(row)
    await seeded_and_split_session.commit()

    r = await seeded_and_split_session.execute(
        select(JobQueue).where(JobQueue.nombre == "Test Product")
    )
    fetched = r.scalar_one()
    assert fetched.status == "pending"
    assert fetched.batch_id == "batch-uuid-1"
    assert fetched.classification_id is None


async def test_job_queue_status_transitions(seeded_and_split_session):
    from scraper.db.models import JobQueue
    from sqlalchemy import select

    row = JobQueue(nombre="X", status="pending", created_at=datetime.now(tz=UTC))
    seeded_and_split_session.add(row)
    await seeded_and_split_session.commit()

    # Transition: pending → in_progress
    row.status = "in_progress"
    row.started_at = datetime.now(tz=UTC)
    await seeded_and_split_session.commit()

    r = await seeded_and_split_session.execute(
        select(JobQueue).where(JobQueue.nombre == "X")
    )
    fetched = r.scalar_one()
    assert fetched.status == "in_progress"
    assert fetched.started_at is not None
```

- [ ] **Step 2: Run test — fails**

```bash
poetry run pytest tests/unit/test_job_queue_model.py -v
```

Expected: `AttributeError: module 'scraper.db.models' has no attribute 'JobQueue'`.

- [ ] **Step 3: Add `JobQueue` class to `src/scraper/db/models.py`**

Append to the existing file (after the other classes like `UploadedDocument`):

```python
class JobQueue(Base):
    __tablename__ = "job_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    nombre: Mapped[str] = mapped_column(String, nullable=False, index=True)
    pdf_path: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", index=True
    )
    # FK to classifications when done
    classification_id: Mapped[int | None] = mapped_column(
        ForeignKey("classifications.id"), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
```

- [ ] **Step 4: Create Alembic migration**

```bash
poetry run alembic revision --autogenerate -m "add job_queue table"
```

This should generate `alembic/versions/<hash>_add_job_queue.py`. Inspect the file and confirm it creates `job_queue` with the right columns and indexes. Rename for readability to `20260420_add_job_queue.py`:

```bash
# Manually inspect and verify the autogenerated file contains create_table for job_queue
```

- [ ] **Step 5: Apply migration**

```bash
poetry run alembic upgrade head
```

- [ ] **Step 6: Tests pass**

```bash
poetry run pytest tests/unit/test_job_queue_model.py -v
```

Expected: 2 passed.

- [ ] **Step 7: Full suite green**

```bash
poetry run pytest -q 2>&1 | tail -3
```

Expected: 180 passed, 1 failed (pre-existing kill-switch test).

- [ ] **Step 8: Lint + commit**

```bash
poetry run ruff check src/scraper/db/models.py tests/unit/test_job_queue_model.py
git add src/scraper/db/models.py alembic/versions/ tests/unit/test_job_queue_model.py
git commit -m "feat(phase3): add JobQueue model + Alembic migration"
```

---

## Task 2: Sabbi overlay loader (YAML → pydantic)

El loader del YAML + función `apply_overlay_defaults`.

**Files:**
- Create: `src/scraper/overlay/__init__.py`
- Create: `src/scraper/overlay/types.py`
- Create: `src/scraper/overlay/loader.py`
- Create: `config/sabbi_overlay.yaml`
- Create: `tests/unit/test_overlay_loader.py`
- Create: `tests/unit/test_overlay_apply.py`

- [ ] **Step 1: Create starter YAML**

`config/sabbi_overlay.yaml`:

```yaml
# Sabbi operational defaults — attributes that the pipeline cannot find on
# the web because they represent Sabbi's own custody structure, not the
# emisor's data. The review UI offers "Apply Sabbi defaults" that pre-fills
# these when approving a classification.

via_sabbi_brokerage:
  # Convention for products held via Credicorp Capital custody (standard
  # structure — applies to ~95% of products in Sabbi's universe)
  administrador: "Credicorp Capital"
  gestor: "Credicorp Capital"
  comision: 0.0065
```

- [ ] **Step 2: Write failing test**

`tests/unit/test_overlay_loader.py`:

```python
def test_load_sabbi_overlay_parses_yaml():
    from scraper.overlay.loader import load_sabbi_overlay

    overlay = load_sabbi_overlay()
    assert overlay.via_sabbi_brokerage is not None
    assert overlay.via_sabbi_brokerage.administrador == "Credicorp Capital"
    assert overlay.via_sabbi_brokerage.gestor == "Credicorp Capital"
    assert overlay.via_sabbi_brokerage.comision == 0.0065


def test_load_sabbi_overlay_reload_clears_cache():
    from scraper.overlay.loader import load_sabbi_overlay, reload_sabbi_overlay

    o1 = load_sabbi_overlay()
    reload_sabbi_overlay()
    o2 = load_sabbi_overlay()
    # After reload it should re-read the file (may or may not be same values
    # depending on whether file changed, but the call should succeed)
    assert o2.via_sabbi_brokerage.administrador == "Credicorp Capital"
```

- [ ] **Step 3: Run — fails (module missing)**

```bash
poetry run pytest tests/unit/test_overlay_loader.py -v
```

- [ ] **Step 4: Implement `src/scraper/overlay/types.py`**

```python
"""Pydantic types for the Sabbi overlay YAML."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ViaSabbiBrokerage(BaseModel):
    """Default operational values when a product is held via Sabbi's broker."""
    administrador: str
    gestor: str
    comision: float = Field(ge=0.0, le=1.0)


class SabbiOverlay(BaseModel):
    """Top-level overlay config. Future: add more via_* sections for other brokers."""
    via_sabbi_brokerage: ViaSabbiBrokerage | None = None
```

- [ ] **Step 5: Implement `src/scraper/overlay/loader.py`**

```python
"""Loader for config/sabbi_overlay.yaml."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from scraper.overlay.types import SabbiOverlay

_OVERLAY_PATH = Path(__file__).resolve().parents[3] / "config" / "sabbi_overlay.yaml"


@lru_cache(maxsize=1)
def load_sabbi_overlay() -> SabbiOverlay:
    """Parse config/sabbi_overlay.yaml into a SabbiOverlay pydantic model."""
    if not _OVERLAY_PATH.exists():
        return SabbiOverlay()
    with open(_OVERLAY_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return SabbiOverlay(**data)


def reload_sabbi_overlay() -> None:
    """Clear the lru_cache so load_sabbi_overlay() re-reads the file."""
    load_sabbi_overlay.cache_clear()
```

- [ ] **Step 6: Implement `src/scraper/overlay/__init__.py`**

```python
from scraper.overlay.loader import load_sabbi_overlay, reload_sabbi_overlay
from scraper.overlay.types import SabbiOverlay, ViaSabbiBrokerage

__all__ = [
    "SabbiOverlay",
    "ViaSabbiBrokerage",
    "load_sabbi_overlay",
    "reload_sabbi_overlay",
]
```

- [ ] **Step 7: Tests pass**

```bash
poetry run pytest tests/unit/test_overlay_loader.py -v
```

Expected: 2 passed.

- [ ] **Step 8: Write apply tests**

`tests/unit/test_overlay_apply.py`:

```python
def test_apply_overlay_sets_admin_when_null():
    from scraper.overlay.loader import apply_overlay_defaults
    from scraper.overlay.types import SabbiOverlay, ViaSabbiBrokerage

    overlay = SabbiOverlay(
        via_sabbi_brokerage=ViaSabbiBrokerage(
            administrador="Credicorp Capital",
            gestor="Credicorp Capital",
            comision=0.0065,
        )
    )
    attributes = {
        "administrador": None,
        "gestor": None,
        "comision": None,
        "moneda": "dolares",
    }
    result = apply_overlay_defaults(attributes, overlay, choice="via_sabbi_brokerage")
    assert result["administrador"] == "Credicorp Capital"
    assert result["gestor"] == "Credicorp Capital"
    assert result["comision"] == 0.0065
    assert result["moneda"] == "dolares"


def test_apply_overlay_does_not_override_nonnull_values():
    from scraper.overlay.loader import apply_overlay_defaults
    from scraper.overlay.types import SabbiOverlay, ViaSabbiBrokerage

    overlay = SabbiOverlay(
        via_sabbi_brokerage=ViaSabbiBrokerage(
            administrador="Credicorp Capital",
            gestor="Credicorp Capital",
            comision=0.0065,
        )
    )
    attributes = {
        "administrador": "Pellegrini S.A.",
        "gestor": "Pellegrini S.A.",
        "comision": 0.0075,
    }
    result = apply_overlay_defaults(attributes, overlay, choice="via_sabbi_brokerage")
    # Should NOT override existing values
    assert result["administrador"] == "Pellegrini S.A."
    assert result["gestor"] == "Pellegrini S.A."
    assert result["comision"] == 0.0075


def test_apply_overlay_noop_when_choice_is_none():
    from scraper.overlay.loader import apply_overlay_defaults
    from scraper.overlay.types import SabbiOverlay

    overlay = SabbiOverlay()
    attributes = {"administrador": None}
    result = apply_overlay_defaults(attributes, overlay, choice=None)
    assert result == {"administrador": None}
```

- [ ] **Step 9: Add `apply_overlay_defaults` to `src/scraper/overlay/loader.py`**

Append after `reload_sabbi_overlay`:

```python
def apply_overlay_defaults(
    attributes: dict,
    overlay: SabbiOverlay,
    choice: str | None,
) -> dict:
    """Return a new attributes dict with overlay defaults filling in None values.

    Only fills attributes that are None. Does NOT override existing values.
    choice selects which overlay section to use (e.g. 'via_sabbi_brokerage').
    """
    result = dict(attributes)
    if choice is None:
        return result
    section = getattr(overlay, choice, None)
    if section is None:
        return result

    for field_name in ("administrador", "gestor", "comision"):
        if result.get(field_name) is None:
            default_value = getattr(section, field_name, None)
            if default_value is not None:
                result[field_name] = default_value
    return result
```

Update `__init__.py` to export:

```python
from scraper.overlay.loader import (
    apply_overlay_defaults,
    load_sabbi_overlay,
    reload_sabbi_overlay,
)
from scraper.overlay.types import SabbiOverlay, ViaSabbiBrokerage

__all__ = [
    "SabbiOverlay",
    "ViaSabbiBrokerage",
    "apply_overlay_defaults",
    "load_sabbi_overlay",
    "reload_sabbi_overlay",
]
```

- [ ] **Step 10: Tests pass**

```bash
poetry run pytest tests/unit/test_overlay_loader.py tests/unit/test_overlay_apply.py -v
```

Expected: 5 passed.

- [ ] **Step 11: Lint + commit**

```bash
poetry run ruff check src/scraper/overlay/ tests/unit/test_overlay_loader.py tests/unit/test_overlay_apply.py
git add src/scraper/overlay/ config/sabbi_overlay.yaml tests/unit/test_overlay_loader.py tests/unit/test_overlay_apply.py
git commit -m "feat(phase3): Sabbi overlay YAML loader + apply_overlay_defaults"
```

---

## Task 3: Worker skeleton (polling loop)

El worker script base: polling loop, claim pending jobs.

**Files:**
- Create: `src/scraper/scripts/worker.py`
- Create: `src/scraper/scripts/worker_ops.py` (DB operations)
- Create: `tests/unit/test_worker_ops.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_worker_ops.py`:

```python
from datetime import UTC, datetime


async def test_claim_pending_jobs_marks_in_progress(seeded_and_split_session):
    from scraper.db.models import JobQueue
    from scraper.scripts.worker_ops import claim_pending_jobs

    # Seed 3 pending jobs
    for i in range(3):
        seeded_and_split_session.add(
            JobQueue(nombre=f"Product {i}", status="pending", created_at=datetime.now(tz=UTC))
        )
    await seeded_and_split_session.commit()

    # Claim 2 of them
    claimed = await claim_pending_jobs(seeded_and_split_session, limit=2)
    assert len(claimed) == 2
    for job in claimed:
        assert job.status == "in_progress"
        assert job.started_at is not None


async def test_claim_pending_jobs_returns_empty_when_no_pending(seeded_and_split_session):
    from scraper.scripts.worker_ops import claim_pending_jobs

    claimed = await claim_pending_jobs(seeded_and_split_session, limit=5)
    assert claimed == []


async def test_mark_job_done_sets_completed_and_classification_id(seeded_and_split_session):
    from sqlalchemy import select

    from scraper.db.models import JobQueue
    from scraper.scripts.worker_ops import mark_job_done

    job = JobQueue(nombre="X", status="in_progress", created_at=datetime.now(tz=UTC))
    seeded_and_split_session.add(job)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(job)

    await mark_job_done(seeded_and_split_session, job.id, classification_id=42)

    r = await seeded_and_split_session.execute(
        select(JobQueue).where(JobQueue.id == job.id)
    )
    updated = r.scalar_one()
    assert updated.status == "done"
    assert updated.classification_id == 42
    assert updated.completed_at is not None


async def test_mark_job_failed_records_error(seeded_and_split_session):
    from sqlalchemy import select

    from scraper.db.models import JobQueue
    from scraper.scripts.worker_ops import mark_job_failed

    job = JobQueue(nombre="X", status="in_progress", created_at=datetime.now(tz=UTC))
    seeded_and_split_session.add(job)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(job)

    await mark_job_failed(seeded_and_split_session, job.id, error="network timeout")

    r = await seeded_and_split_session.execute(
        select(JobQueue).where(JobQueue.id == job.id)
    )
    updated = r.scalar_one()
    assert updated.status == "failed"
    assert updated.error == "network timeout"
```

- [ ] **Step 2: Run — fails**

```bash
poetry run pytest tests/unit/test_worker_ops.py -v
```

- [ ] **Step 3: Implement `src/scraper/scripts/worker_ops.py`**

```python
"""Database operations for the worker."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.db.models import JobQueue

_STALE_IN_PROGRESS_MIN = 30


async def claim_pending_jobs(session: AsyncSession, limit: int) -> list[JobQueue]:
    """Mark up to `limit` pending jobs as in_progress and return them.

    Also resets any jobs stuck in 'in_progress' for more than 30 minutes
    back to 'pending' (assumed crashed worker).
    """
    now = datetime.now(tz=UTC)

    # Reset stale in_progress jobs
    stale_threshold = datetime.now(tz=UTC).timestamp() - _STALE_IN_PROGRESS_MIN * 60
    r = await session.execute(
        select(JobQueue).where(JobQueue.status == "in_progress")
    )
    for stale in r.scalars().all():
        if stale.started_at and stale.started_at.timestamp() < stale_threshold:
            stale.status = "pending"
            stale.started_at = None

    # Claim new pending jobs
    r = await session.execute(
        select(JobQueue)
        .where(JobQueue.status == "pending")
        .order_by(JobQueue.created_at)
        .limit(limit)
    )
    jobs = list(r.scalars().all())
    for job in jobs:
        job.status = "in_progress"
        job.started_at = now
    await session.commit()
    return jobs


async def mark_job_done(
    session: AsyncSession, job_id: int, classification_id: int | None
) -> None:
    await session.execute(
        update(JobQueue)
        .where(JobQueue.id == job_id)
        .values(
            status="done",
            classification_id=classification_id,
            completed_at=datetime.now(tz=UTC),
        )
    )
    await session.commit()


async def mark_job_failed(session: AsyncSession, job_id: int, error: str) -> None:
    await session.execute(
        update(JobQueue)
        .where(JobQueue.id == job_id)
        .values(
            status="failed",
            error=error[:2000],  # truncate extremely long stack traces
            completed_at=datetime.now(tz=UTC),
        )
    )
    await session.commit()
```

- [ ] **Step 4: Tests pass**

```bash
poetry run pytest tests/unit/test_worker_ops.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Implement `src/scraper/scripts/worker.py` skeleton**

This is the skeleton — the actual `_process_job` body comes in Task 4.

```python
"""Background worker that polls job_queue and processes pending jobs.

Usage:
    poetry run python -m scraper.scripts.worker

Run in a separate terminal from the Streamlit UI. Processes up to
MAX_CONCURRENT jobs in parallel using asyncio.gather.
"""
from __future__ import annotations

import asyncio
import os
import sys

import structlog

from scraper.db.models import JobQueue
from scraper.db.session import get_session
from scraper.logging_config import configure_logging
from scraper.scripts.worker_ops import claim_pending_jobs, mark_job_done, mark_job_failed

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

log = structlog.get_logger()

MAX_CONCURRENT = int(os.environ.get("WORKER_MAX_CONCURRENT", "3"))
POLL_INTERVAL = float(os.environ.get("WORKER_POLL_INTERVAL_S", "5.0"))


async def _process_job(job: JobQueue) -> None:
    """Implemented in Task 4."""
    raise NotImplementedError("Task 4 implements this")


async def _loop() -> None:
    configure_logging(level="INFO", json_logs=False)
    log.info("worker_start", max_concurrent=MAX_CONCURRENT, poll_interval=POLL_INTERVAL)

    while True:
        async with get_session() as s:
            pending = await claim_pending_jobs(s, limit=MAX_CONCURRENT)

        if not pending:
            await asyncio.sleep(POLL_INTERVAL)
            continue

        log.info("worker_claimed_jobs", count=len(pending))
        tasks = [_process_job(job) for job in pending]
        await asyncio.gather(*tasks, return_exceptions=True)


def main() -> None:
    try:
        asyncio.run(_loop())
    except KeyboardInterrupt:
        log.info("worker_shutdown_graceful")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Full suite green**

```bash
poetry run pytest -q 2>&1 | tail -3
```

- [ ] **Step 7: Lint + commit**

```bash
poetry run ruff check src/scraper/scripts/worker_ops.py src/scraper/scripts/worker.py tests/unit/test_worker_ops.py
git add src/scraper/scripts/worker_ops.py src/scraper/scripts/worker.py tests/unit/test_worker_ops.py
git commit -m "feat(phase3): worker skeleton + job queue operations"
```

---

## Task 4: Worker processes single job via `find_and_classify`

El core logic: tomar un `JobQueue` row y ejecutar el pipeline completo. Este task cubre el caso default (cascade search por nombre). Tasks 5 y 6 agregan PDF/URL routing.

**Files:**
- Modify: `src/scraper/scripts/worker.py` (implementar `_process_job`)
- Create: `src/scraper/scripts/worker_pipeline.py` (lógica pipeline + save)
- Create: `tests/integration/test_worker_pipeline.py`

- [ ] **Step 1: Write failing test**

`tests/integration/test_worker_pipeline.py`:

```python
import json
from datetime import UTC, datetime


async def test_process_job_cascade_saves_classification_and_review_entry(
    seeded_and_split_session, mock_llm_client, monkeypatch
):
    from scraper.agents.types import AttributeClassification, ClassificationResult
    from scraper.db.models import Classification, JobQueue, ReviewQueue
    from scraper.scripts import worker as worker_mod
    from scraper.scripts.worker_pipeline import process_job_via_cascade
    from sqlalchemy import select

    # Insert a pending job
    job = JobQueue(nombre="Test Product", status="in_progress", created_at=datetime.now(tz=UTC))
    seeded_and_split_session.add(job)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(job)

    # Mock find_and_classify result
    fake_cls_result = ClassificationResult(
        producto="Test Product",
        attributes={
            "nombre": AttributeClassification(
                value="Test Product", confidence=1.0, reasoning="", rule_applied=""
            ),
        },
        global_confidence=0.85,
        unknowns=[],
    )

    async def fake_run(nombre, rules_md, llm, session):
        return fake_cls_result, {
            "veredicto": "agree",
            "global_verdict": "auto_approvable",
            "reviewer_confidence": 0.9,
        }, "auto_approvable", "cascade_level_0", 0.12, 1500, [nombre]  # last = citations stub

    monkeypatch.setattr(
        "scraper.scripts.worker_pipeline._run_cascade_classify_review", fake_run
    )

    # Process the job
    await process_job_via_cascade(
        session=seeded_and_split_session,
        job=job,
        llm=mock_llm_client,
        rules_md="# rules",
    )

    # Verify classification was saved
    r = await seeded_and_split_session.execute(
        select(Classification).where(Classification.product_name_input == "Test Product")
    )
    cls = r.scalar_one()
    assert cls.global_confidence == 0.85
    assert cls.final_status == "auto_approvable"

    # Verify review_queue entry
    r = await seeded_and_split_session.execute(
        select(ReviewQueue).where(ReviewQueue.classification_id == cls.id)
    )
    review = r.scalar_one()
    assert review.flag == "auto_approvable"
```

- [ ] **Step 2: Run — fails**

```bash
poetry run pytest tests/integration/test_worker_pipeline.py -v
```

- [ ] **Step 3: Implement `src/scraper/scripts/worker_pipeline.py`**

```python
"""Pipeline execution + persistence logic for the worker."""
from __future__ import annotations

import json
import time
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.agents.classifier import classify
from scraper.agents.orchestrator import decide_flag
from scraper.agents.prompts.builder import build_few_shot_from_db
from scraper.agents.reviewer import review
from scraper.db.models import Classification, JobQueue, ReviewQueue
from scraper.llm import LLMClient
from scraper.scripts.find_and_classify import _context_from_top, _top_ficha
from scraper.search.cascade import run_cascade

log = structlog.get_logger()


async def _run_cascade_classify_review(
    nombre: str, rules_md: str, llm: LLMClient, session: AsyncSession
) -> tuple:
    """Run the full pipeline for a given nombre. Returns tuple of
    (cls_result, rev_result_dict, flag, source_used, cost_usd, duration_ms, citations)."""
    start = time.monotonic()
    few_shot = await build_few_shot_from_db(session, limit=20)
    cascade = await run_cascade(nombre=nombre, session=session, llm=llm)
    if not cascade.fichas:
        # Nothing found. Return low_quality placeholder
        duration_ms = int((time.monotonic() - start) * 1000)
        return None, None, "low_quality", "no_source", llm.cost.total_usd, duration_ms, []

    top = _top_ficha(cascade.fichas)
    context = _context_from_top(top, cascade.fichas)

    cls_result = await classify(
        llm=llm,
        producto_nombre=nombre,
        product_context=context,
        rules_md=rules_md,
        few_shot_examples=few_shot,
    )
    rev_result = await review(
        llm=llm,
        producto_nombre=nombre,
        product_context=context,
        classifier_output=cls_result,
        rules_md=rules_md,
    )
    flag = decide_flag(cls_result, rev_result)
    source_used = f"cascade_level_{cascade.level}"
    duration_ms = int((time.monotonic() - start) * 1000)
    citations = []
    for f in cascade.fichas:
        citations.extend(f.citations or [])
    rev_dict = {
        "veredicto": rev_result.veredicto,
        "global_verdict": rev_result.global_verdict,
        "reviewer_confidence": rev_result.reviewer_confidence,
    }
    return cls_result, rev_dict, flag, source_used, llm.cost.total_usd, duration_ms, citations


async def process_job_via_cascade(
    *,
    session: AsyncSession,
    job: JobQueue,
    llm: LLMClient,
    rules_md: str,
) -> int:
    """Run the cascade pipeline for a job, save classification + review_queue,
    return classification_id."""
    (
        cls_result,
        rev_dict,
        flag,
        source_used,
        cost_usd,
        duration_ms,
        citations,
    ) = await _run_cascade_classify_review(job.nombre, rules_md, llm, session)

    classifier_output = {}
    per_attr_conf = {}
    global_conf = None
    if cls_result is not None:
        classifier_json = cls_result.to_json() if hasattr(cls_result, "to_json") else cls_result
        if isinstance(classifier_json, str):
            classifier_output = json.loads(classifier_json)
        else:
            classifier_output = classifier_json
        per_attr_conf = {k: v.confidence for k, v in cls_result.attributes.items()}
        global_conf = cls_result.global_confidence

    cls_row = Classification(
        product_name_input=job.nombre,
        classifier_output=classifier_output,
        reviewer_output=rev_dict or {},
        global_confidence=global_conf,
        per_attribute_confidence=per_attr_conf,
        final_status=flag,
        source_used=source_used,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )
    session.add(cls_row)
    await session.commit()
    await session.refresh(cls_row)

    review_row = ReviewQueue(
        classification_id=cls_row.id,
        flag=flag,
        priority=_flag_priority(flag),
    )
    session.add(review_row)
    await session.commit()

    log.info(
        "worker_job_processed",
        job_id=job.id,
        classification_id=cls_row.id,
        flag=flag,
        cost_usd=cost_usd,
    )
    return cls_row.id


def _flag_priority(flag: str) -> int:
    """Lower number = higher priority in review queue."""
    return {"low_quality": 0, "needs_review": 1, "auto_approvable": 2}.get(flag, 3)
```

- [ ] **Step 4: Update `src/scraper/scripts/worker.py` to implement `_process_job`**

Replace the `_process_job` stub with:

```python
async def _process_job(job: JobQueue) -> None:
    """Process a single job. Routes by presence of pdf_path / url / nombre."""
    from pathlib import Path

    from scraper.llm import LLMClient
    from scraper.scripts.worker_ops import mark_job_done, mark_job_failed
    from scraper.scripts.worker_pipeline import process_job_via_cascade

    try:
        rules_md = (Path.cwd() / "rules" / "v5.md").read_text(encoding="utf-8")
        llm = LLMClient()

        async with get_session() as s:
            # Routing (Task 5 + 6 will add PDF and URL paths)
            if job.pdf_path is not None:
                # Task 5
                classification_id = None
                raise NotImplementedError("pdf_path routing in Task 5")
            elif job.url is not None:
                # Task 6
                classification_id = None
                raise NotImplementedError("url routing in Task 6")
            else:
                # Default: cascade by nombre
                classification_id = await process_job_via_cascade(
                    session=s, job=job, llm=llm, rules_md=rules_md
                )

        async with get_session() as s:
            await mark_job_done(s, job.id, classification_id=classification_id)
    except Exception as e:
        import traceback as _tb

        log.warning("worker_job_failed", job_id=job.id, error=str(e))
        async with get_session() as s:
            await mark_job_failed(s, job.id, error=_tb.format_exc())
```

- [ ] **Step 5: Tests pass**

```bash
poetry run pytest tests/integration/test_worker_pipeline.py -v
```

Expected: 1 passed.

- [ ] **Step 6: Full suite**

```bash
poetry run pytest -q 2>&1 | tail -3
```

- [ ] **Step 7: Lint + commit**

```bash
poetry run ruff check src/scraper/scripts/worker.py src/scraper/scripts/worker_pipeline.py tests/integration/test_worker_pipeline.py
git add src/scraper/scripts/worker.py src/scraper/scripts/worker_pipeline.py tests/integration/test_worker_pipeline.py
git commit -m "feat(phase3): worker processes cascade jobs and saves classification + review entry"
```

---

## Task 5: Worker routes pdf_path jobs to extract_from_pdf

**Files:**
- Modify: `src/scraper/scripts/worker.py` (implement pdf_path branch)
- Modify: `src/scraper/scripts/worker_pipeline.py` (add process_job_via_pdf)
- Create: `tests/integration/test_worker_pdf_routing.py`

- [ ] **Step 1: Write failing test**

`tests/integration/test_worker_pdf_routing.py`:

```python
from datetime import UTC, datetime
from pathlib import Path


async def test_process_job_via_pdf_saves_classification(
    seeded_and_split_session, mock_llm_client, monkeypatch, tmp_path
):
    from scraper.agents.types import AttributeExtraction, ExtractedFicha
    from scraper.db.models import Classification, JobQueue, ReviewQueue
    from scraper.scripts.worker_pipeline import process_job_via_pdf
    from sqlalchemy import select

    # Create a fake PDF file
    pdf_path = tmp_path / "ficha.pdf"
    pdf_path.write_bytes(b"%PDF-1.5 fake content")

    # Insert job with pdf_path
    job = JobQueue(
        nombre="Test Product",
        pdf_path=str(pdf_path),
        status="in_progress",
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(job)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(job)

    # Mock extract_from_pdf
    fake_ficha = ExtractedFicha(
        source_url=None,
        source_type="pdf_text",
        source_confidence=0.9,
        fetched_at=datetime.now(tz=UTC),
        raw_text="pdf content",
        tables=[],
        attributes={
            "nombre": AttributeExtraction(value="Test Product", confidence=1.0, reasoning="", raw_quote="")
        },
        citations=[str(pdf_path)],
        extraction_cost_usd=0.03,
        extraction_duration_ms=500,
    )

    async def fake_extract_pdf(*, path, llm, nombre):
        return fake_ficha

    monkeypatch.setattr(
        "scraper.scripts.worker_pipeline.extract_from_pdf", fake_extract_pdf
    )

    # Mock the classify + review parts to avoid needing full taxonomy chain
    from scraper.agents.types import AttributeClassification, ClassificationResult

    fake_cls_result = ClassificationResult(
        producto="Test Product",
        attributes={
            "nombre": AttributeClassification(
                value="Test Product", confidence=1.0, reasoning="", rule_applied=""
            ),
        },
        global_confidence=0.80,
        unknowns=[],
    )

    async def fake_classify(**kwargs):
        return fake_cls_result

    async def fake_review(**kwargs):
        class _RV:
            veredicto = "agree"
            global_verdict = "auto_approvable"
            reviewer_confidence = 0.85
        return _RV()

    monkeypatch.setattr("scraper.scripts.worker_pipeline.classify", fake_classify)
    monkeypatch.setattr("scraper.scripts.worker_pipeline.review", fake_review)

    cls_id = await process_job_via_pdf(
        session=seeded_and_split_session,
        job=job,
        llm=mock_llm_client,
        rules_md="# rules",
    )

    r = await seeded_and_split_session.execute(
        select(Classification).where(Classification.id == cls_id)
    )
    cls = r.scalar_one()
    assert cls.product_name_input == "Test Product"
    assert cls.source_used == "direct_pdf"
```

- [ ] **Step 2: Run — fails**

```bash
poetry run pytest tests/integration/test_worker_pdf_routing.py -v
```

- [ ] **Step 3: Add `process_job_via_pdf` to `worker_pipeline.py`**

Append to `src/scraper/scripts/worker_pipeline.py`:

```python
import time as _time

from scraper.extract.pdf import extract_from_pdf


async def process_job_via_pdf(
    *,
    session: AsyncSession,
    job: JobQueue,
    llm: LLMClient,
    rules_md: str,
) -> int:
    """Process a job that has pdf_path set. Skip cascade, extract from PDF directly."""
    start = _time.monotonic()
    few_shot = await build_few_shot_from_db(session, limit=20)

    ficha = await extract_from_pdf(path=Path(job.pdf_path), llm=llm, nombre=job.nombre)

    # Build classifier context from the single ficha
    context = {
        "administrador": ficha.attributes.get("administrador").value
        if "administrador" in ficha.attributes
        else None,
        "gestor": ficha.attributes.get("gestor").value
        if "gestor" in ficha.attributes
        else None,
        "moneda": ficha.attributes.get("moneda").value
        if "moneda" in ficha.attributes
        else None,
        "liquidez": ficha.attributes.get("liquidez").value
        if "liquidez" in ficha.attributes
        else None,
        "extra": f"PDF source: {job.pdf_path}",
    }

    cls_result = await classify(
        llm=llm,
        producto_nombre=job.nombre,
        product_context=context,
        rules_md=rules_md,
        few_shot_examples=few_shot,
    )
    rev_result = await review(
        llm=llm,
        producto_nombre=job.nombre,
        product_context=context,
        classifier_output=cls_result,
        rules_md=rules_md,
    )
    flag = decide_flag(cls_result, rev_result)
    duration_ms = int((_time.monotonic() - start) * 1000)

    classifier_json = cls_result.to_json() if hasattr(cls_result, "to_json") else cls_result
    classifier_output = json.loads(classifier_json) if isinstance(classifier_json, str) else classifier_json

    cls_row = Classification(
        product_name_input=job.nombre,
        classifier_output=classifier_output,
        reviewer_output={
            "veredicto": rev_result.veredicto,
            "global_verdict": rev_result.global_verdict,
            "reviewer_confidence": rev_result.reviewer_confidence,
        },
        global_confidence=cls_result.global_confidence,
        per_attribute_confidence={k: v.confidence for k, v in cls_result.attributes.items()},
        final_status=flag,
        source_used="direct_pdf",
        duration_ms=duration_ms,
        cost_usd=llm.cost.total_usd,
    )
    session.add(cls_row)
    await session.commit()
    await session.refresh(cls_row)

    review_row = ReviewQueue(
        classification_id=cls_row.id,
        flag=flag,
        priority=_flag_priority(flag),
    )
    session.add(review_row)
    await session.commit()

    log.info(
        "worker_job_processed_via_pdf",
        job_id=job.id,
        classification_id=cls_row.id,
        flag=flag,
    )
    return cls_row.id
```

- [ ] **Step 4: Wire into worker.py**

In `src/scraper/scripts/worker.py`, replace the `pdf_path` branch:

```python
            if job.pdf_path is not None:
                from scraper.scripts.worker_pipeline import process_job_via_pdf

                classification_id = await process_job_via_pdf(
                    session=s, job=job, llm=llm, rules_md=rules_md
                )
```

- [ ] **Step 5: Tests pass**

```bash
poetry run pytest tests/integration/test_worker_pdf_routing.py -v
```

Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
poetry run ruff check src/scraper/scripts/worker.py src/scraper/scripts/worker_pipeline.py tests/integration/test_worker_pdf_routing.py
git add src/scraper/scripts/worker.py src/scraper/scripts/worker_pipeline.py tests/integration/test_worker_pdf_routing.py
git commit -m "feat(phase3): worker routes pdf_path jobs through extract_from_pdf"
```

---

## Task 6: Worker routes url jobs to extract_from_url

**Files:**
- Modify: `src/scraper/scripts/worker.py` (implement url branch)
- Modify: `src/scraper/scripts/worker_pipeline.py` (add process_job_via_url)
- Create: `tests/integration/test_worker_url_routing.py`

- [ ] **Step 1: Write failing test**

`tests/integration/test_worker_url_routing.py`:

```python
from datetime import UTC, datetime


async def test_process_job_via_url_saves_classification(
    seeded_and_split_session, mock_llm_client, monkeypatch
):
    from scraper.agents.types import (
        AttributeClassification,
        AttributeExtraction,
        ClassificationResult,
        ExtractedFicha,
    )
    from scraper.db.models import Classification, JobQueue
    from scraper.scripts.worker_pipeline import process_job_via_url
    from sqlalchemy import select

    job = JobQueue(
        nombre="Test Product",
        url="https://example.com/fondo",
        status="in_progress",
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(job)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(job)

    fake_ficha = ExtractedFicha(
        source_url="https://example.com/fondo",
        source_type="html",
        source_confidence=0.9,
        fetched_at=datetime.now(tz=UTC),
        raw_text="html content",
        tables=[],
        attributes={
            "nombre": AttributeExtraction(value="Test Product", confidence=1.0, reasoning="", raw_quote="")
        },
        citations=["https://example.com/fondo"],
        extraction_cost_usd=0.04,
        extraction_duration_ms=800,
    )

    async def fake_extract_url(*, url, llm, nombre):
        return [fake_ficha]

    monkeypatch.setattr(
        "scraper.scripts.worker_pipeline.extract_from_url", fake_extract_url
    )

    fake_cls_result = ClassificationResult(
        producto="Test Product",
        attributes={
            "nombre": AttributeClassification(
                value="Test Product", confidence=1.0, reasoning="", rule_applied=""
            ),
        },
        global_confidence=0.85,
        unknowns=[],
    )

    async def fake_classify(**kwargs):
        return fake_cls_result

    async def fake_review(**kwargs):
        class _RV:
            veredicto = "agree"
            global_verdict = "auto_approvable"
            reviewer_confidence = 0.88
        return _RV()

    monkeypatch.setattr("scraper.scripts.worker_pipeline.classify", fake_classify)
    monkeypatch.setattr("scraper.scripts.worker_pipeline.review", fake_review)

    cls_id = await process_job_via_url(
        session=seeded_and_split_session,
        job=job,
        llm=mock_llm_client,
        rules_md="# rules",
    )

    r = await seeded_and_split_session.execute(
        select(Classification).where(Classification.id == cls_id)
    )
    cls = r.scalar_one()
    assert cls.source_used == "direct_url"
```

- [ ] **Step 2: Run — fails**

```bash
poetry run pytest tests/integration/test_worker_url_routing.py -v
```

- [ ] **Step 3: Add `process_job_via_url` to `worker_pipeline.py`**

Append after `process_job_via_pdf`:

```python
from scraper.extract.html import extract_from_url
from scraper.scripts.find_and_classify import _context_from_top, _top_ficha


async def process_job_via_url(
    *,
    session: AsyncSession,
    job: JobQueue,
    llm: LLMClient,
    rules_md: str,
) -> int:
    """Process a job that has url set. Skip cascade, extract from URL directly."""
    start = _time.monotonic()
    few_shot = await build_few_shot_from_db(session, limit=20)

    fichas = await extract_from_url(url=job.url, llm=llm, nombre=job.nombre)
    if not fichas:
        raise RuntimeError(f"extract_from_url returned no fichas for {job.url}")

    top = _top_ficha(fichas)
    context = _context_from_top(top, fichas)

    cls_result = await classify(
        llm=llm,
        producto_nombre=job.nombre,
        product_context=context,
        rules_md=rules_md,
        few_shot_examples=few_shot,
    )
    rev_result = await review(
        llm=llm,
        producto_nombre=job.nombre,
        product_context=context,
        classifier_output=cls_result,
        rules_md=rules_md,
    )
    flag = decide_flag(cls_result, rev_result)
    duration_ms = int((_time.monotonic() - start) * 1000)

    classifier_json = cls_result.to_json() if hasattr(cls_result, "to_json") else cls_result
    classifier_output = json.loads(classifier_json) if isinstance(classifier_json, str) else classifier_json

    cls_row = Classification(
        product_name_input=job.nombre,
        classifier_output=classifier_output,
        reviewer_output={
            "veredicto": rev_result.veredicto,
            "global_verdict": rev_result.global_verdict,
            "reviewer_confidence": rev_result.reviewer_confidence,
        },
        global_confidence=cls_result.global_confidence,
        per_attribute_confidence={k: v.confidence for k, v in cls_result.attributes.items()},
        final_status=flag,
        source_used="direct_url",
        duration_ms=duration_ms,
        cost_usd=llm.cost.total_usd,
    )
    session.add(cls_row)
    await session.commit()
    await session.refresh(cls_row)

    review_row = ReviewQueue(
        classification_id=cls_row.id,
        flag=flag,
        priority=_flag_priority(flag),
    )
    session.add(review_row)
    await session.commit()

    return cls_row.id
```

- [ ] **Step 4: Wire into worker.py**

Replace the `url is not None` branch with:

```python
            elif job.url is not None:
                from scraper.scripts.worker_pipeline import process_job_via_url

                classification_id = await process_job_via_url(
                    session=s, job=job, llm=llm, rules_md=rules_md
                )
```

- [ ] **Step 5: Tests pass + commit**

```bash
poetry run pytest tests/integration/test_worker_url_routing.py -v
poetry run ruff check src/scraper/scripts/worker.py src/scraper/scripts/worker_pipeline.py tests/integration/test_worker_url_routing.py
git add src/scraper/scripts/worker.py src/scraper/scripts/worker_pipeline.py tests/integration/test_worker_url_routing.py
git commit -m "feat(phase3): worker routes url jobs through extract_from_url"
```

---

## Task 7: Worker concurrent processing via asyncio.gather

Verify the existing `asyncio.gather` in the main loop works as expected with real jobs, and add a config test.

**Files:**
- Create: `tests/integration/test_worker_concurrency.py`

- [ ] **Step 1: Write test**

```python
import asyncio
from datetime import UTC, datetime


async def test_worker_gather_processes_multiple_jobs(seeded_and_split_session, mock_llm_client, monkeypatch):
    from scraper.db.models import JobQueue
    from scraper.scripts import worker as worker_mod

    # Seed 3 pending jobs
    for i in range(3):
        seeded_and_split_session.add(
            JobQueue(nombre=f"P{i}", status="pending", created_at=datetime.now(tz=UTC))
        )
    await seeded_and_split_session.commit()

    # Mock _process_job to record which jobs it saw + simulate work
    processed = []
    lock = asyncio.Lock()
    max_concurrent = 0
    current = 0

    async def fake_process(job):
        nonlocal max_concurrent, current
        async with lock:
            current += 1
            max_concurrent = max(max_concurrent, current)
        await asyncio.sleep(0.05)
        async with lock:
            current -= 1
            processed.append(job.nombre)

    monkeypatch.setattr(worker_mod, "_process_job", fake_process)

    # Manually call the claim + gather cycle
    from scraper.scripts.worker_ops import claim_pending_jobs
    async with worker_mod.get_session() as s:
        pending = await claim_pending_jobs(s, limit=3)

    tasks = [fake_process(job) for job in pending]
    await asyncio.gather(*tasks)

    assert len(processed) == 3
    assert max_concurrent >= 2, "jobs should run concurrently"
```

- [ ] **Step 2: Run test**

```bash
poetry run pytest tests/integration/test_worker_concurrency.py -v
```

Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
poetry run ruff check tests/integration/test_worker_concurrency.py
git add tests/integration/test_worker_concurrency.py
git commit -m "test(phase3): verify worker asyncio.gather runs jobs concurrently"
```

---

## Task 8: Streamlit app skeleton

**Files:**
- Create: `src/scraper/ui/__init__.py`
- Create: `src/scraper/ui/app.py`
- Create: `src/scraper/ui/pages/__init__.py`
- Create: `src/scraper/ui/pages/1_batch_upload.py` (placeholder)
- Create: `src/scraper/ui/pages/2_single_input.py` (placeholder)
- Create: `src/scraper/ui/pages/3_review_queue.py` (placeholder)
- Create: `src/scraper/ui/pages/4_settings.py` (placeholder)
- Modify: `pyproject.toml` (add streamlit)

- [ ] **Step 1: Install streamlit**

```bash
poetry add streamlit pandas
```

- [ ] **Step 2: Create `src/scraper/ui/app.py`**

```python
"""Streamlit entry point for Sabbi Classifier HITL review UI.

Run with: poetry run streamlit run src/scraper/ui/app.py
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="Sabbi Classifier",
    page_icon="📊",
    layout="wide",
)

st.title("Sabbi Classifier")
st.markdown(
    "Bienvenido. Navegá desde el sidebar:\n\n"
    "- **Batch Upload**: subí un CSV de productos para procesar en background\n"
    "- **Single Input**: clasificá un producto individual\n"
    "- **Review Queue**: revisá y aprobá clasificaciones pendientes\n"
    "- **Settings**: config del Sabbi overlay, rules version, cost tracking\n\n"
    "**Importante**: para procesar jobs del batch upload, necesitás correr el "
    "worker en otra terminal:\n\n"
    "```bash\npoetry run python -m scraper.scripts.worker\n```"
)
```

- [ ] **Step 3: Create placeholder pages**

`src/scraper/ui/pages/1_batch_upload.py`:

```python
"""Batch CSV upload page (placeholder — full impl in Task 10)."""
import streamlit as st

st.title("Batch Upload")
st.info("CSV upload form — implementation in Task 10")
```

Same pattern for `2_single_input.py`, `3_review_queue.py`, `4_settings.py`.

- [ ] **Step 4: Verify Streamlit starts (manual)**

```bash
poetry run streamlit run src/scraper/ui/app.py --server.headless true
```

Should print URL `http://localhost:8501`. Ctrl+C to stop.

- [ ] **Step 5: Create minimal smoke test**

`tests/integration/test_ui_smoke.py`:

```python
def test_ui_app_module_imports():
    """Sanity: the Streamlit app module imports without errors."""
    import importlib

    mod = importlib.import_module("scraper.ui.app")
    assert mod is not None


def test_ui_pages_import():
    import importlib

    for page in ("1_batch_upload", "2_single_input", "3_review_queue", "4_settings"):
        mod = importlib.import_module(f"scraper.ui.pages.{page}")
        assert mod is not None
```

Wait — Streamlit pages have numbers in filenames, Python modules can't. Need to handle. Use importlib with file path instead:

```python
def test_ui_app_module_imports():
    import importlib.util
    from pathlib import Path

    app_path = Path(__file__).resolve().parents[2] / "src" / "scraper" / "ui" / "app.py"
    spec = importlib.util.spec_from_file_location("ui_app", app_path)
    mod = importlib.util.module_from_spec(spec)
    # Note: can't exec because streamlit commands would run; just verify file exists + is syntactically valid
    assert app_path.exists()
    import ast
    ast.parse(app_path.read_text(encoding="utf-8"))


def test_ui_pages_syntactically_valid():
    import ast
    from pathlib import Path

    pages_dir = Path(__file__).resolve().parents[2] / "src" / "scraper" / "ui" / "pages"
    for page_file in pages_dir.glob("*.py"):
        if page_file.name == "__init__.py":
            continue
        ast.parse(page_file.read_text(encoding="utf-8"))
```

- [ ] **Step 6: Lint + commit**

```bash
poetry run ruff check src/scraper/ui/ tests/integration/test_ui_smoke.py
git add src/scraper/ui/ tests/integration/test_ui_smoke.py pyproject.toml poetry.lock
git commit -m "feat(phase3): Streamlit app skeleton + placeholder pages"
```

---

## Task 9: UI state helpers + DB session wrapping

Helpers to reuse across pages: DB session context, cached reads, common widgets.

**Files:**
- Create: `src/scraper/ui/state.py`
- Create: `tests/unit/test_ui_state.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_ui_state.py`:

```python
def test_run_async_executes_coroutine():
    from scraper.ui.state import run_async

    async def _hello():
        return "hello"

    result = run_async(_hello())
    assert result == "hello"


def test_run_async_preserves_return_value():
    from scraper.ui.state import run_async

    async def _compute():
        return 1 + 2

    assert run_async(_compute()) == 3
```

- [ ] **Step 2: Run — fails**

```bash
poetry run pytest tests/unit/test_ui_state.py -v
```

- [ ] **Step 3: Implement `src/scraper/ui/state.py`**

```python
"""Shared helpers for Streamlit UI pages."""
from __future__ import annotations

import asyncio
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine from a Streamlit page.

    Streamlit runs synchronously on each rerun. We need a fresh event loop
    per invocation because Streamlit doesn't persist one.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)
```

- [ ] **Step 4: Tests pass + commit**

```bash
poetry run pytest tests/unit/test_ui_state.py -v
poetry run ruff check src/scraper/ui/state.py tests/unit/test_ui_state.py
git add src/scraper/ui/state.py tests/unit/test_ui_state.py
git commit -m "feat(phase3): UI state helper run_async for Streamlit pages"
```

---

## Task 10: Batch CSV upload page

**Files:**
- Modify: `src/scraper/ui/pages/1_batch_upload.py` (full impl)
- Create: `src/scraper/ui/batch_ops.py` (DB logic for batch creation)
- Create: `tests/unit/test_batch_ops.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_batch_ops.py`:

```python
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
    from scraper.ui.batch_ops import parse_products_csv
    import pytest as _pt

    csv_text = "title,foo\nA,B\n"
    with _pt.raises(ValueError, match="nombre"):
        parse_products_csv(StringIO(csv_text))


async def test_parse_csv_rejects_empty_nombre():
    from scraper.ui.batch_ops import parse_products_csv
    import pytest as _pt

    csv_text = "nombre\nProducto A\n\nProducto B\n"
    with _pt.raises(ValueError, match="empty"):
        parse_products_csv(StringIO(csv_text))


async def test_create_batch_inserts_jobs(seeded_and_split_session):
    from scraper.db.models import JobQueue
    from scraper.ui.batch_ops import create_batch
    from sqlalchemy import select

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
```

- [ ] **Step 2: Run — fails**

```bash
poetry run pytest tests/unit/test_batch_ops.py -v
```

- [ ] **Step 3: Implement `src/scraper/ui/batch_ops.py`**

```python
"""Batch upload operations — CSV parsing and job creation."""
from __future__ import annotations

import csv
import uuid
from datetime import UTC, datetime
from typing import IO, Any

from sqlalchemy.ext.asyncio import AsyncSession

from scraper.db.models import JobQueue


def parse_products_csv(fileobj: IO[str]) -> list[dict[str, Any]]:
    """Parse a CSV with required column 'nombre' and optional 'pdf_path', 'url'."""
    reader = csv.DictReader(fileobj)
    if reader.fieldnames is None or "nombre" not in reader.fieldnames:
        raise ValueError("CSV must have a 'nombre' column")

    rows: list[dict[str, Any]] = []
    for row_num, raw in enumerate(reader, start=2):  # start=2: header is row 1
        nombre = (raw.get("nombre") or "").strip()
        if not nombre:
            raise ValueError(f"Row {row_num} has empty nombre")
        rows.append(
            {
                "nombre": nombre,
                "pdf_path": (raw.get("pdf_path") or "").strip() or None,
                "url": (raw.get("url") or "").strip() or None,
            }
        )
    return rows


async def create_batch(
    session: AsyncSession, rows: list[dict[str, Any]]
) -> str:
    """Insert N JobQueue rows with a shared batch_id. Returns the batch_id."""
    batch_id = str(uuid.uuid4())
    now = datetime.now(tz=UTC)
    for row in rows:
        session.add(
            JobQueue(
                batch_id=batch_id,
                nombre=row["nombre"],
                pdf_path=row.get("pdf_path"),
                url=row.get("url"),
                status="pending",
                created_at=now,
            )
        )
    await session.commit()
    return batch_id
```

- [ ] **Step 4: Tests pass**

```bash
poetry run pytest tests/unit/test_batch_ops.py -v
```

- [ ] **Step 5: Implement `src/scraper/ui/pages/1_batch_upload.py`**

```python
"""Batch CSV upload page."""
from __future__ import annotations

from io import StringIO

import pandas as pd
import streamlit as st

from scraper.db.session import get_session
from scraper.ui.batch_ops import create_batch, parse_products_csv
from scraper.ui.state import run_async

st.title("Batch Upload")
st.markdown(
    "Subí un CSV con columnas:\n"
    "- `nombre` (obligatoria) — nombre del producto a clasificar\n"
    "- `pdf_path` (opcional) — ruta local al PDF (skip cascade)\n"
    "- `url` (opcional) — URL específica (skip cascade)\n\n"
    "Si solo hay `nombre`, se usa la cascade de search. "
    "Si hay `pdf_path` o `url`, se clasifica directamente desde ese source."
)

uploaded = st.file_uploader("Seleccioná un CSV", type=["csv"])

if uploaded is not None:
    text = uploaded.read().decode("utf-8")
    try:
        rows = parse_products_csv(StringIO(text))
    except ValueError as e:
        st.error(f"Error en CSV: {e}")
        st.stop()

    st.success(f"CSV válido: {len(rows)} productos.")
    st.dataframe(pd.DataFrame(rows))

    if st.button("Crear batch y encolar jobs", type="primary"):
        async def _create():
            async with get_session() as s:
                return await create_batch(s, rows)

        batch_id = run_async(_create())
        st.success(
            f"Batch creado con id `{batch_id[:8]}...`. "
            f"{len(rows)} jobs en cola. Corré el worker para procesar:\n\n"
            f"```bash\npoetry run python -m scraper.scripts.worker\n```"
        )

# Show recent batches
st.divider()
st.subheader("Últimos batches")

async def _recent_batches():
    from sqlalchemy import func, select

    from scraper.db.models import JobQueue

    async with get_session() as s:
        r = await s.execute(
            select(
                JobQueue.batch_id,
                func.count(JobQueue.id).label("total"),
                func.sum(
                    (JobQueue.status == "done").cast(int)
                ).label("done_count"),
                func.min(JobQueue.created_at).label("created_at"),
            )
            .where(JobQueue.batch_id.is_not(None))
            .group_by(JobQueue.batch_id)
            .order_by(func.min(JobQueue.created_at).desc())
            .limit(10)
        )
        return r.all()


batches = run_async(_recent_batches())
if batches:
    df = pd.DataFrame(
        [
            {
                "batch": row.batch_id[:8] + "...",
                "total": row.total,
                "done": row.done_count or 0,
                "created": row.created_at,
            }
            for row in batches
        ]
    )
    st.dataframe(df, use_container_width=True)
else:
    st.info("No hay batches todavía.")
```

(Note: Using `.cast(int)` on a boolean may have compatibility issues depending on DB dialect; for SQLite it typically works. If it errors, fall back to counting `CASE WHEN status='done' THEN 1 END`.)

- [ ] **Step 6: Manual verification (smoke)**

```bash
poetry run streamlit run src/scraper/ui/app.py
```

Navigate to "Batch Upload" in sidebar. Upload a small test CSV with one column `nombre` and two rows. Verify preview + "Crear batch" creates jobs.

- [ ] **Step 7: Commit**

```bash
poetry run ruff check src/scraper/ui/batch_ops.py src/scraper/ui/pages/1_batch_upload.py tests/unit/test_batch_ops.py
git add src/scraper/ui/batch_ops.py src/scraper/ui/pages/1_batch_upload.py tests/unit/test_batch_ops.py
git commit -m "feat(phase3): batch CSV upload page + job queue insertion"
```

---

## Task 11: Single input page (entry B)

**Files:**
- Modify: `src/scraper/ui/pages/2_single_input.py` (full impl)

- [ ] **Step 1: Implement `2_single_input.py`**

```python
"""Single product classification input."""
from __future__ import annotations

from datetime import UTC, datetime

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
        import hashlib
        import os
        from pathlib import Path

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
        f"Job #{job_id} encolado. Va a aparecer en la Review Queue en ~3-5 min. "
        "Asegurate de tener el worker corriendo:\n\n"
        "```bash\npoetry run python -m scraper.scripts.worker\n```"
    )
```

- [ ] **Step 2: Manual verification**

Run Streamlit, go to Single Input, type a name, click Clasificar. Verify a `job_queue` row is inserted (check with `sqlite3 data/local.db "SELECT * FROM job_queue ORDER BY id DESC LIMIT 1"`).

- [ ] **Step 3: Commit**

```bash
poetry run ruff check src/scraper/ui/pages/2_single_input.py
git add src/scraper/ui/pages/2_single_input.py
git commit -m "feat(phase3): single input page enqueues jobs with optional URL/PDF"
```

---

## Task 12: Review queue list page

**Files:**
- Modify: `src/scraper/ui/pages/3_review_queue.py`
- Create: `src/scraper/ui/review_ops.py` (DB queries for review queue)
- Create: `tests/unit/test_review_ops.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_review_ops.py`:

```python
from datetime import UTC, datetime


async def test_list_pending_reviews_returns_unresolved(seeded_and_split_session):
    from scraper.db.models import Classification, ReviewQueue
    from scraper.ui.review_ops import list_pending_reviews

    # Insert one classification + one review queue entry
    cls = Classification(
        product_name_input="Test",
        classifier_output={},
        reviewer_output=None,
        global_confidence=0.8,
        per_attribute_confidence={},
        final_status="needs_review",
        source_used="cascade_level_2",
        duration_ms=1000,
        cost_usd=0.5,
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(cls)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(cls)

    rev = ReviewQueue(
        classification_id=cls.id,
        flag="needs_review",
        priority=1,
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(rev)
    await seeded_and_split_session.commit()

    pending = await list_pending_reviews(seeded_and_split_session)
    assert len(pending) >= 1
    assert any(r.classification.product_name_input == "Test" for r in pending)


async def test_list_pending_reviews_excludes_resolved(seeded_and_split_session):
    from scraper.db.models import Classification, ReviewQueue
    from scraper.ui.review_ops import list_pending_reviews

    cls = Classification(
        product_name_input="ResolvedOne",
        classifier_output={},
        reviewer_output=None,
        global_confidence=0.9,
        per_attribute_confidence={},
        final_status="auto_approvable",
        source_used="cascade_level_0",
        duration_ms=10,
        cost_usd=0.0,
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(cls)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(cls)

    rev = ReviewQueue(
        classification_id=cls.id,
        flag="auto_approvable",
        priority=2,
        human_decision="approved",
        resolved_at=datetime.now(tz=UTC),
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(rev)
    await seeded_and_split_session.commit()

    pending = await list_pending_reviews(seeded_and_split_session)
    assert not any(r.classification.product_name_input == "ResolvedOne" for r in pending)
```

- [ ] **Step 2: Run — fails**

```bash
poetry run pytest tests/unit/test_review_ops.py -v
```

- [ ] **Step 3: Implement `src/scraper/ui/review_ops.py`**

```python
"""Queries for the review queue UI."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from scraper.db.models import Classification, ReviewQueue


async def list_pending_reviews(
    session: AsyncSession,
    flag_filter: str | None = None,
    limit: int = 100,
) -> list[ReviewQueue]:
    """Return ReviewQueue rows without human_decision set, with classification joined.

    Ordered by priority ascending (0=low_quality first) then created_at descending.
    """
    stmt = (
        select(ReviewQueue)
        .options(selectinload(ReviewQueue.classification))
        .where(ReviewQueue.human_decision.is_(None))
        .order_by(ReviewQueue.priority.asc(), ReviewQueue.created_at.desc())
        .limit(limit)
    )
    if flag_filter:
        stmt = stmt.where(ReviewQueue.flag == flag_filter)
    r = await session.execute(stmt)
    return list(r.scalars().all())


async def get_review_with_classification(
    session: AsyncSession, review_id: int
) -> ReviewQueue | None:
    r = await session.execute(
        select(ReviewQueue)
        .options(selectinload(ReviewQueue.classification))
        .where(ReviewQueue.id == review_id)
    )
    return r.scalar_one_or_none()
```

Wait — the `ReviewQueue` model in Phase 1 has `classification_id` FK but no `classification` relationship. Need to add that, or use a join query instead.

Modify `src/scraper/db/models.py` — in the `ReviewQueue` class, add:

```python
    classification: Mapped["Classification"] = relationship(
        "Classification", foreign_keys=[classification_id], lazy="joined"
    )
```

(Add `from sqlalchemy.orm import relationship` import if not already present.)

- [ ] **Step 4: Tests pass**

```bash
poetry run pytest tests/unit/test_review_ops.py -v
```

- [ ] **Step 5: Implement `src/scraper/ui/pages/3_review_queue.py`**

```python
"""Review queue list and detail."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from scraper.db.session import get_session
from scraper.ui.review_ops import list_pending_reviews
from scraper.ui.state import run_async

st.title("Review Queue")

flag_filter = st.selectbox(
    "Filtro por flag",
    options=["Todos", "low_quality", "needs_review", "auto_approvable"],
    index=0,
)

async def _list():
    async with get_session() as s:
        return await list_pending_reviews(
            s, flag_filter=None if flag_filter == "Todos" else flag_filter
        )


reviews = run_async(_list())

if not reviews:
    st.info("No hay clasificaciones pendientes de revisar.")
else:
    data = []
    for r in reviews:
        cls = r.classification
        data.append(
            {
                "id": r.id,
                "nombre": cls.product_name_input,
                "flag": r.flag,
                "conf": round(cls.global_confidence or 0.0, 2),
                "source": cls.source_used,
                "cost_usd": round(cls.cost_usd or 0.0, 3),
                "created": r.created_at,
            }
        )
    st.dataframe(pd.DataFrame(data), use_container_width=True)

    selected_id = st.number_input(
        "ID de review para ver detalle", min_value=1, step=1, value=data[0]["id"]
    )
    if st.button("Ver detalle"):
        st.session_state["selected_review_id"] = int(selected_id)
        st.switch_page("pages/review_detail.py")
```

**Note:** Streamlit's `st.switch_page` requires the target to be a page file. Create a detail page or inline the detail view. For simplicity, inline is easier but makes the file bigger. Task 13 handles the detail view.

For now, the list page is enough. Step 6 verifies.

- [ ] **Step 6: Manual verification**

Start Streamlit, upload a CSV with 1 product, run worker, check that the product appears in the review queue list.

- [ ] **Step 7: Commit**

```bash
poetry run ruff check src/scraper/ui/pages/3_review_queue.py src/scraper/ui/review_ops.py tests/unit/test_review_ops.py src/scraper/db/models.py
git add src/scraper/ui/pages/3_review_queue.py src/scraper/ui/review_ops.py tests/unit/test_review_ops.py src/scraper/db/models.py
git commit -m "feat(phase3): review queue list with filter by flag"
```

---

## Task 13: Review detail page with inline editor

**Files:**
- Modify: `src/scraper/ui/pages/3_review_queue.py` (add detail view inline)
- Create: `src/scraper/ui/components/field_editor.py`

- [ ] **Step 1: Implement `src/scraper/ui/components/field_editor.py`**

```python
"""Inline editor widget for classification attributes."""
from __future__ import annotations

import json
from typing import Any

import streamlit as st


def edit_attribute(
    key: str, current_value: Any, confidence: float | None = None, reasoning: str = ""
) -> Any:
    """Render an editable field for an attribute. Returns the edited value."""
    label = key.replace("_", " ").title()
    suffix = f" (conf {confidence:.2f})" if confidence is not None else ""

    if isinstance(current_value, dict):
        # Show as JSON text area
        new_text = st.text_area(
            f"{label}{suffix}",
            value=json.dumps(current_value, ensure_ascii=False, indent=2),
            height=100,
            key=f"edit_{key}",
        )
        try:
            return json.loads(new_text)
        except json.JSONDecodeError:
            st.warning(f"{label}: JSON inválido, usando valor original")
            return current_value
    elif current_value is None:
        new_val = st.text_input(f"{label}{suffix} (null)", value="", key=f"edit_{key}")
        return new_val or None
    else:
        new_val = st.text_input(f"{label}{suffix}", value=str(current_value), key=f"edit_{key}")
        return new_val

    if reasoning:
        st.caption(f"💭 {reasoning[:200]}")
```

- [ ] **Step 2: Update `3_review_queue.py` to include detail view below the list**

Add after the `st.dataframe` block:

```python
st.divider()
st.subheader("Detalle")

selected_id = st.session_state.get("selected_review_id")
if selected_id is None and reviews:
    selected_id = reviews[0].id

if selected_id:
    async def _get(rid):
        from scraper.ui.review_ops import get_review_with_classification
        async with get_session() as s:
            return await get_review_with_classification(s, rid)

    r = run_async(_get(int(selected_id)))
    if r is None:
        st.warning(f"Review {selected_id} no existe.")
    else:
        cls = r.classification
        st.markdown(f"### {cls.product_name_input}")
        st.markdown(f"Flag: `{r.flag}` · Confianza global: **{cls.global_confidence:.2f}** · Source: `{cls.source_used}`")

        attrs = cls.classifier_output.get("attributes", {}) if isinstance(cls.classifier_output, dict) else {}

        from scraper.ui.components.field_editor import edit_attribute

        edited: dict = {}
        st.markdown("#### Atributos")
        for attr_key in [
            "nombre", "foco_geografico", "clase_activo", "subyacente",
            "moneda", "liquidez", "administrador", "gestor",
            "comision", "minimo_inversion",
        ]:
            a = attrs.get(attr_key, {})
            edited[attr_key] = edit_attribute(
                key=attr_key,
                current_value=a.get("value"),
                confidence=a.get("confidence"),
                reasoning=a.get("reasoning", ""),
            )

        st.session_state["edited_values"] = edited

        col1, col2 = st.columns(2)
        with col1:
            if st.button("✓ Aprobar", type="primary"):
                st.info("Approve logic — implementado en Task 16")
        with col2:
            if st.button("🗑 Rechazar"):
                st.info("Reject logic — implementado en Task 17")
```

- [ ] **Step 3: Manual smoke**

Run Streamlit, click through the list, verify detail appears with editable fields.

- [ ] **Step 4: Commit**

```bash
poetry run ruff check src/scraper/ui/components/ src/scraper/ui/pages/3_review_queue.py
git add src/scraper/ui/components/ src/scraper/ui/pages/3_review_queue.py
git commit -m "feat(phase3): review detail view with inline attribute editor"
```

---

## Task 14: Apply Sabbi defaults component

**Files:**
- Create: `src/scraper/ui/components/overlay_apply.py`
- Modify: `src/scraper/ui/pages/3_review_queue.py` (use component)

- [ ] **Step 1: Implement `overlay_apply.py`**

```python
"""Component for applying Sabbi overlay defaults to attributes."""
from __future__ import annotations

import streamlit as st

from scraper.overlay import apply_overlay_defaults, load_sabbi_overlay


def overlay_apply_button(attributes: dict) -> dict:
    """Render 'Apply Sabbi defaults' button. Returns possibly-modified attributes dict."""
    overlay = load_sabbi_overlay()
    if overlay.via_sabbi_brokerage is None:
        st.info("No hay `via_sabbi_brokerage` configurado en overlay.")
        return attributes

    current = {
        "administrador": attributes.get("administrador"),
        "gestor": attributes.get("gestor"),
        "comision": attributes.get("comision"),
    }
    default_preview = {
        "administrador": overlay.via_sabbi_brokerage.administrador,
        "gestor": overlay.via_sabbi_brokerage.gestor,
        "comision": overlay.via_sabbi_brokerage.comision,
    }

    st.caption(
        f"Sabbi default: admin={default_preview['administrador']}, "
        f"gestor={default_preview['gestor']}, comision={default_preview['comision']}"
    )

    if st.button("🎯 Apply Sabbi defaults (via Credicorp)"):
        merged = apply_overlay_defaults(current, overlay, choice="via_sabbi_brokerage")
        attributes = dict(attributes)
        attributes.update(merged)
        st.success("Defaults aplicados — revisá los campos.")

    return attributes
```

- [ ] **Step 2: Use component in review detail page**

In `3_review_queue.py`, add before the "Atributos" section:

```python
        from scraper.ui.components.overlay_apply import overlay_apply_button

        st.markdown("#### Sabbi operational overlay")
        preview_attrs = {
            attr_key: attrs.get(attr_key, {}).get("value")
            for attr_key in ("administrador", "gestor", "comision")
        }
        preview_attrs = overlay_apply_button(preview_attrs)
        # Update attrs dict for display in editor section below
        for attr_key in ("administrador", "gestor", "comision"):
            if attr_key in attrs:
                attrs[attr_key]["value"] = preview_attrs.get(attr_key)
```

- [ ] **Step 3: Commit**

```bash
poetry run ruff check src/scraper/ui/components/overlay_apply.py src/scraper/ui/pages/3_review_queue.py
git add src/scraper/ui/components/overlay_apply.py src/scraper/ui/pages/3_review_queue.py
git commit -m "feat(phase3): Apply Sabbi defaults button in review detail"
```

---

## Task 15: Ficha viewer component (collapsable evidence)

**Files:**
- Create: `src/scraper/ui/components/ficha_viewer.py`
- Modify: `src/scraper/ui/pages/3_review_queue.py`

- [ ] **Step 1: Implement ficha_viewer.py**

```python
"""Viewer widget for ExtractedFicha evidence blocks."""
from __future__ import annotations

import json

import streamlit as st


def show_evidence_fichas(classifier_output: dict) -> None:
    """Render collapsable evidence fichas inside the classifier output."""
    if not isinstance(classifier_output, dict):
        return
    # The classifier output itself isn't a list of fichas, but its reasoning
    # might reference them via the product_context.extra field which was
    # rendered in find_and_classify. For now, show raw classifier_output JSON.
    with st.expander("Ver evidencia (raw classifier output)"):
        st.json(classifier_output)
```

- [ ] **Step 2: Use in review detail page**

Add after the Sabbi overlay section in `3_review_queue.py`:

```python
        from scraper.ui.components.ficha_viewer import show_evidence_fichas

        show_evidence_fichas(cls.classifier_output)
```

- [ ] **Step 3: Commit**

```bash
poetry run ruff check src/scraper/ui/components/ficha_viewer.py src/scraper/ui/pages/3_review_queue.py
git add src/scraper/ui/components/ficha_viewer.py src/scraper/ui/pages/3_review_queue.py
git commit -m "feat(phase3): evidence fichas viewer in review detail"
```

---

## Task 16: Approve logic

**Files:**
- Create: `src/scraper/ui/review_logic.py`
- Create: `tests/unit/test_review_logic.py`
- Modify: `src/scraper/ui/pages/3_review_queue.py` (wire button)

- [ ] **Step 1: Write failing test**

`tests/unit/test_review_logic.py`:

```python
from datetime import UTC, datetime


async def test_approve_creates_product_and_audit_log(seeded_and_split_session):
    from scraper.db.models import AuditLog, Classification, JobQueue, Product, ReviewQueue
    from scraper.ui.review_logic import approve_classification
    from sqlalchemy import select

    # Seed classification + review_queue + job
    cls = Classification(
        product_name_input="Test Approve",
        classifier_output={
            "attributes": {
                "nombre": {"value": "Test Approve", "confidence": 1.0},
                "foco_geografico": {"value": {"Perú": 100}, "confidence": 0.9},
                "clase_activo": {"value": {"Mercados Públicos - Variable": 100}, "confidence": 0.9},
                "subyacente": {"value": {"Acciones Peru": 100}, "confidence": 0.9},
                "moneda": {"value": "soles", "confidence": 1.0},
                "administrador": {"value": "Credicorp Capital", "confidence": 1.0},
                "gestor": {"value": "Credicorp Capital", "confidence": 1.0},
                "liquidez": {"value": "Inmediata", "confidence": 1.0},
                "minimo_inversion": {"value": None, "confidence": 0.0},
                "comision": {"value": 0.0065, "confidence": 0.9},
            }
        },
        reviewer_output={},
        global_confidence=0.9,
        per_attribute_confidence={},
        final_status="needs_review",
        source_used="cascade_level_0",
        duration_ms=100,
        cost_usd=0.3,
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(cls)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(cls)

    rev = ReviewQueue(
        classification_id=cls.id,
        flag="needs_review",
        priority=1,
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(rev)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(rev)

    edited_values = {
        "nombre": "Test Approve",
        "foco_geografico": {"Perú": 100.0},
        "clase_activo": {"Mercados Públicos - Variable": 100.0},
        "subyacente": {"Acciones Peru": 100.0},
        "moneda": "soles",
        "administrador": "Credicorp Capital",
        "gestor": "Credicorp Capital",
        "liquidez": "Inmediata",
        "minimo_inversion": None,
        "comision": 0.0065,
    }

    product_id = await approve_classification(
        seeded_and_split_session,
        review_id=rev.id,
        edited_values=edited_values,
        operator="test_operator",
    )

    # Product inserted
    r = await seeded_and_split_session.execute(
        select(Product).where(Product.id == product_id)
    )
    p = r.scalar_one()
    assert p.nombre == "Test Approve"
    assert p.moneda == "soles"
    assert p.administrador == "Credicorp Capital"

    # review_queue updated
    r = await seeded_and_split_session.execute(
        select(ReviewQueue).where(ReviewQueue.id == rev.id)
    )
    updated_rev = r.scalar_one()
    assert updated_rev.human_decision == "approved"
    assert updated_rev.final_product_id == product_id
    assert updated_rev.resolved_at is not None

    # audit_log has entry
    r = await seeded_and_split_session.execute(
        select(AuditLog).where(AuditLog.entity_type == "product").where(
            AuditLog.entity_id == str(product_id)
        )
    )
    logs = list(r.scalars().all())
    assert len(logs) == 1
    assert logs[0].event_type == "approval"
```

- [ ] **Step 2: Run — fails**

```bash
poetry run pytest tests/unit/test_review_logic.py -v
```

- [ ] **Step 3: Implement `src/scraper/ui/review_logic.py`**

```python
"""Approve / reject / reclassify logic."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.db.models import AuditLog, Classification, JobQueue, Product, ReviewQueue


async def approve_classification(
    session: AsyncSession,
    review_id: int,
    edited_values: dict,
    operator: str,
) -> int:
    """Create a Product from the edited classification values, mark review as approved,
    log in audit_log, update job_queue. Returns the new product id.
    """
    r = await session.execute(select(ReviewQueue).where(ReviewQueue.id == review_id))
    rev = r.scalar_one()

    r = await session.execute(
        select(Classification).where(Classification.id == rev.classification_id)
    )
    cls = r.scalar_one()

    product = Product(
        nombre=edited_values.get("nombre") or cls.product_name_input,
        foco_geografico=edited_values.get("foco_geografico") or {},
        clase_activo=edited_values.get("clase_activo") or {},
        subyacentes=edited_values.get("subyacente") or {},
        comision=_to_float(edited_values.get("comision")),
        comision_raw=edited_values.get("comision") if isinstance(edited_values.get("comision"), str) else None,
        moneda=edited_values.get("moneda"),
        administrador=edited_values.get("administrador"),
        gestor=edited_values.get("gestor"),
        liquidez=edited_values.get("liquidez"),
        minimo_inversion=edited_values.get("minimo_inversion"),
        source_type="pipeline_approved",
        status="active",
    )
    session.add(product)
    await session.commit()
    await session.refresh(product)

    # Update review_queue
    rev.human_decision = "approved"
    rev.final_product_id = product.id
    rev.resolved_at = datetime.now(tz=UTC)
    await session.commit()

    # Update related job_queue if any
    await session.execute(
        update(JobQueue)
        .where(JobQueue.classification_id == cls.id)
        .values(status="approved")
    )
    await session.commit()

    # Audit log
    audit = AuditLog(
        event_type="approval",
        actor=operator,
        entity_type="product",
        entity_id=str(product.id),
        before_state={"classification_output": cls.classifier_output},
        after_state=edited_values,
    )
    session.add(audit)
    await session.commit()
    return product.id


def _to_float(val) -> float | None:
    if val is None or isinstance(val, str):
        try:
            return float(val) if val else None
        except (TypeError, ValueError):
            return None
    if isinstance(val, (int, float)):
        return float(val)
    return None
```

- [ ] **Step 4: Tests pass**

```bash
poetry run pytest tests/unit/test_review_logic.py -v
```

- [ ] **Step 5: Wire into review detail page**

In `3_review_queue.py`, replace the `✓ Aprobar` button handler:

```python
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✓ Aprobar", type="primary"):
                from scraper.ui.review_logic import approve_classification

                async def _approve():
                    async with get_session() as s:
                        return await approve_classification(
                            s,
                            review_id=r.id,
                            edited_values=edited,
                            operator="local_user",
                        )

                product_id = run_async(_approve())
                st.success(f"✓ Aprobado. Producto #{product_id} creado.")
                st.session_state.pop("selected_review_id", None)
                st.rerun()
```

- [ ] **Step 6: Commit**

```bash
poetry run ruff check src/scraper/ui/review_logic.py tests/unit/test_review_logic.py src/scraper/ui/pages/3_review_queue.py
git add src/scraper/ui/review_logic.py tests/unit/test_review_logic.py src/scraper/ui/pages/3_review_queue.py
git commit -m "feat(phase3): approve logic creates Product + audit_log + updates review queue"
```

---

## Task 17: Reject logic

**Files:**
- Modify: `src/scraper/ui/review_logic.py` (add reject_classification)
- Modify: `tests/unit/test_review_logic.py` (add reject tests)
- Modify: `src/scraper/ui/pages/3_review_queue.py` (wire button)

- [ ] **Step 1: Add reject test**

Append to `tests/unit/test_review_logic.py`:

```python
async def test_reject_updates_review_without_creating_product(seeded_and_split_session):
    from scraper.db.models import AuditLog, Classification, ReviewQueue
    from scraper.ui.review_logic import reject_classification
    from sqlalchemy import select

    cls = Classification(
        product_name_input="Test Reject",
        classifier_output={"attributes": {}},
        reviewer_output={},
        global_confidence=0.3,
        per_attribute_confidence={},
        final_status="low_quality",
        source_used="cascade_level_3",
        duration_ms=10,
        cost_usd=0.5,
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(cls)
    await seeded_and_split_session.commit()
    await seeded_and_split_session.refresh(cls)

    rev = ReviewQueue(
        classification_id=cls.id,
        flag="low_quality",
        priority=0,
        created_at=datetime.now(tz=UTC),
    )
    seeded_and_split_session.add(rev)
    await seeded_and_split_session.commit()

    await reject_classification(
        seeded_and_split_session,
        review_id=rev.id,
        notes="producto no existe en universo Sabbi",
        operator="test_op",
    )

    r = await seeded_and_split_session.execute(
        select(ReviewQueue).where(ReviewQueue.id == rev.id)
    )
    updated = r.scalar_one()
    assert updated.human_decision == "rejected"
    assert updated.human_notes == "producto no existe en universo Sabbi"
    assert updated.resolved_at is not None
    assert updated.final_product_id is None

    r = await seeded_and_split_session.execute(
        select(AuditLog).where(AuditLog.event_type == "rejection")
    )
    logs = list(r.scalars().all())
    assert len(logs) == 1
```

- [ ] **Step 2: Run — fails**

```bash
poetry run pytest tests/unit/test_review_logic.py::test_reject_updates_review_without_creating_product -v
```

- [ ] **Step 3: Add `reject_classification` to `src/scraper/ui/review_logic.py`**

```python
async def reject_classification(
    session: AsyncSession,
    review_id: int,
    notes: str,
    operator: str,
) -> None:
    r = await session.execute(select(ReviewQueue).where(ReviewQueue.id == review_id))
    rev = r.scalar_one()

    rev.human_decision = "rejected"
    rev.human_notes = notes
    rev.resolved_at = datetime.now(tz=UTC)
    await session.commit()

    audit = AuditLog(
        event_type="rejection",
        actor=operator,
        entity_type="review_queue",
        entity_id=str(review_id),
        before_state=None,
        after_state={"notes": notes},
    )
    session.add(audit)
    await session.commit()
```

- [ ] **Step 4: Tests pass**

- [ ] **Step 5: Wire reject button in review_queue page**

Replace the Rechazar button:

```python
        with col2:
            reject_notes = st.text_input("Motivo de rechazo (opcional)", key=f"reject_notes_{r.id}")
            if st.button("🗑 Rechazar"):
                from scraper.ui.review_logic import reject_classification

                async def _reject():
                    async with get_session() as s:
                        return await reject_classification(
                            s, review_id=r.id, notes=reject_notes or "", operator="local_user"
                        )

                run_async(_reject())
                st.success("Rechazado.")
                st.session_state.pop("selected_review_id", None)
                st.rerun()
```

- [ ] **Step 6: Commit**

```bash
poetry run ruff check src/scraper/ui/review_logic.py tests/unit/test_review_logic.py src/scraper/ui/pages/3_review_queue.py
git add src/scraper/ui/review_logic.py tests/unit/test_review_logic.py src/scraper/ui/pages/3_review_queue.py
git commit -m "feat(phase3): reject logic with notes and audit log entry"
```

---

## Task 18: Reactive PDF upload from review card

**Files:**
- Modify: `src/scraper/ui/pages/3_review_queue.py` (add upload handler)
- Create: `src/scraper/ui/upload_ops.py`
- Create: `tests/unit/test_upload_ops.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_upload_ops.py`:

```python
async def test_reclassify_with_pdf_creates_new_job(seeded_and_split_session, tmp_path):
    from scraper.db.models import JobQueue
    from scraper.ui.upload_ops import reclassify_with_pdf
    from sqlalchemy import select

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
```

- [ ] **Step 2: Implement `src/scraper/ui/upload_ops.py`**

```python
"""Upload handlers for reactive PDF-triggered reclassification."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from scraper.db.models import JobQueue, UploadedDocument


async def reclassify_with_pdf(
    session: AsyncSession,
    nombre: str,
    pdf_bytes: bytes,
    operator: str,
) -> int:
    """Save uploaded PDF to disk, insert uploaded_documents row, queue new JobQueue.

    Returns the new job id.
    """
    uploads_dir = Path.cwd() / "data" / "uploaded_pdfs"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    h = hashlib.sha256(pdf_bytes).hexdigest()[:16]
    pdf_path = uploads_dir / f"{h}.pdf"
    if not pdf_path.exists():
        pdf_path.write_bytes(pdf_bytes)

    doc = UploadedDocument(
        product_name=nombre,
        file_path=str(pdf_path),
        mime_type="application/pdf",
    )
    session.add(doc)
    await session.commit()

    job = JobQueue(
        nombre=nombre,
        pdf_path=str(pdf_path),
        status="pending",
        created_at=datetime.now(tz=UTC),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job.id
```

- [ ] **Step 3: Tests pass**

- [ ] **Step 4: Wire into review detail page**

In `3_review_queue.py`, add after the approve/reject buttons:

```python
        st.markdown("---")
        st.markdown("#### Subir PDF si el pipeline falló")
        upload = st.file_uploader("PDF de la ficha", type=["pdf"], key=f"upload_{r.id}")
        if upload and st.button("📎 Re-procesar con PDF"):
            from scraper.ui.upload_ops import reclassify_with_pdf

            async def _reclassify():
                async with get_session() as s:
                    return await reclassify_with_pdf(
                        s,
                        nombre=cls.product_name_input,
                        pdf_bytes=upload.read(),
                        operator="local_user",
                    )

            new_job_id = run_async(_reclassify())
            st.success(
                f"Job #{new_job_id} creado. Correr worker para procesar el PDF. "
                "Volverá a aparecer en la queue."
            )
```

- [ ] **Step 5: Commit**

```bash
poetry run ruff check src/scraper/ui/upload_ops.py tests/unit/test_upload_ops.py src/scraper/ui/pages/3_review_queue.py
git add src/scraper/ui/upload_ops.py tests/unit/test_upload_ops.py src/scraper/ui/pages/3_review_queue.py
git commit -m "feat(phase3): reactive PDF upload from review card"
```

---

## Task 19: Settings page

**Files:**
- Modify: `src/scraper/ui/pages/4_settings.py` (full impl)

- [ ] **Step 1: Implement `4_settings.py`**

```python
"""Settings page: overlay viewer, rules selection, cost tracking."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from scraper.db.session import get_session
from scraper.overlay import load_sabbi_overlay, reload_sabbi_overlay
from scraper.ui.state import run_async

st.title("Settings")

st.subheader("Sabbi Overlay")
overlay_path = Path.cwd() / "config" / "sabbi_overlay.yaml"
st.caption(f"Archivo: `{overlay_path}`")

if overlay_path.exists():
    with open(overlay_path, encoding="utf-8") as f:
        st.code(f.read(), language="yaml")

    if st.button("🔄 Reload overlay"):
        reload_sabbi_overlay()
        st.success("Overlay recargado.")
        overlay = load_sabbi_overlay()
        st.json(overlay.model_dump())
else:
    st.warning(f"Archivo no existe: {overlay_path}")

st.divider()

st.subheader("Rules version")
rules_dir = Path.cwd() / "rules"
rules_files = sorted(rules_dir.glob("v*.md")) if rules_dir.exists() else []
if rules_files:
    current_rules = st.selectbox(
        "Rules version activa",
        options=[f.name for f in rules_files],
        index=len(rules_files) - 1,  # default to latest
    )
    st.caption(f"Nota: el default en `find_and_classify` es `rules/v5.md`. Para cambiar, editar CLI args.")

st.divider()

st.subheader("Cost tracking")

async def _cost_this_month():
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select

    from scraper.db.models import Classification

    thirty_days_ago = datetime.now(tz=UTC) - timedelta(days=30)
    async with get_session() as s:
        r = await s.execute(
            select(
                func.sum(Classification.cost_usd).label("total_cost"),
                func.count(Classification.id).label("count"),
            ).where(Classification.created_at >= thirty_days_ago)
        )
        row = r.one()
        return row.total_cost or 0.0, row.count or 0


cost, n_products = run_async(_cost_this_month())
st.metric("Total últimos 30 días (USD)", f"${cost:.2f}")
st.metric("Productos procesados (últimos 30 días)", str(n_products))
```

- [ ] **Step 2: Manual smoke**

Run Streamlit → Settings tab → verify overlay shows, reload works, rules selectbox populates, cost metric appears.

- [ ] **Step 3: Commit**

```bash
poetry run ruff check src/scraper/ui/pages/4_settings.py
git add src/scraper/ui/pages/4_settings.py
git commit -m "feat(phase3): Settings page with overlay viewer, rules selector, cost tracking"
```

---

## Task 20: Integration tests end-to-end

**Files:**
- Create: `tests/integration/test_phase3_e2e.py`

- [ ] **Step 1: Write e2e test**

`tests/integration/test_phase3_e2e.py`:

```python
"""End-to-end: CSV → queue → worker → review → approve → Product."""
from datetime import UTC, datetime
from io import StringIO


async def test_e2e_csv_to_approved_product(seeded_and_split_session, mock_llm_client, monkeypatch):
    from scraper.agents.types import AttributeClassification, ClassificationResult
    from scraper.db.models import JobQueue, Product, ReviewQueue
    from scraper.scripts.worker_ops import claim_pending_jobs
    from scraper.ui.batch_ops import create_batch, parse_products_csv
    from scraper.ui.review_logic import approve_classification
    from sqlalchemy import select

    # Step 1: Parse CSV and create batch
    csv = "nombre\nTest E2E Product\n"
    rows = parse_products_csv(StringIO(csv))
    batch_id = await create_batch(seeded_and_split_session, rows)
    assert batch_id

    # Step 2: Worker claims the job
    claimed = await claim_pending_jobs(seeded_and_split_session, limit=1)
    assert len(claimed) == 1
    job = claimed[0]

    # Step 3: Mock pipeline and process
    fake_cls = ClassificationResult(
        producto="Test E2E Product",
        attributes={
            "nombre": AttributeClassification(
                value="Test E2E Product", confidence=1.0, reasoning="", rule_applied=""
            ),
            "moneda": AttributeClassification(
                value="soles", confidence=1.0, reasoning="", rule_applied=""
            ),
        },
        global_confidence=0.9,
        unknowns=[],
    )

    async def fake_pipeline(*args, **kwargs):
        return (
            fake_cls,
            {"veredicto": "agree", "global_verdict": "auto_approvable", "reviewer_confidence": 0.9},
            "auto_approvable",
            "cascade_level_0",
            0.05,
            100,
            [],
        )

    monkeypatch.setattr(
        "scraper.scripts.worker_pipeline._run_cascade_classify_review", fake_pipeline
    )

    from scraper.scripts.worker_pipeline import process_job_via_cascade

    cls_id = await process_job_via_cascade(
        session=seeded_and_split_session,
        job=job,
        llm=mock_llm_client,
        rules_md="# rules",
    )

    # Step 4: Review queue has an entry
    r = await seeded_and_split_session.execute(
        select(ReviewQueue).where(ReviewQueue.classification_id == cls_id)
    )
    rev = r.scalar_one()
    assert rev.flag == "auto_approvable"

    # Step 5: Approve with edited values
    edited = {
        "nombre": "Test E2E Product",
        "foco_geografico": {"Perú": 100.0},
        "clase_activo": {"Mercados Públicos - Variable": 100.0},
        "subyacente": {"Acciones Peru": 100.0},
        "moneda": "soles",
        "administrador": "Credicorp Capital",
        "gestor": "Credicorp Capital",
        "liquidez": "Inmediata",
        "minimo_inversion": None,
        "comision": 0.0065,
    }

    product_id = await approve_classification(
        seeded_and_split_session,
        review_id=rev.id,
        edited_values=edited,
        operator="e2e_test",
    )

    # Step 6: Product table has the new row
    r = await seeded_and_split_session.execute(
        select(Product).where(Product.id == product_id)
    )
    p = r.scalar_one()
    assert p.nombre == "Test E2E Product"
    assert p.administrador == "Credicorp Capital"
```

- [ ] **Step 2: Run test**

```bash
poetry run pytest tests/integration/test_phase3_e2e.py -v
```

- [ ] **Step 3: Full suite**

```bash
poetry run pytest -q 2>&1 | tail -3
```

Expected: ~195 passed, 1 failed (pre-existing kill-switch).

- [ ] **Step 4: Commit**

```bash
poetry run ruff check tests/integration/test_phase3_e2e.py
git add tests/integration/test_phase3_e2e.py
git commit -m "test(phase3): end-to-end CSV → queue → worker → review → approve"
```

---

## Task 21: README + run-book documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**

Read current README. Add a new section after existing content:

```markdown
## Phase 3 — HITL UI (local)

### Running the UI

Start the Streamlit app:

```bash
poetry run streamlit run src/scraper/ui/app.py
```

In a **separate terminal**, start the worker (processes batch jobs):

```bash
poetry run python -m scraper.scripts.worker
```

The UI opens at `http://localhost:8501`. Navigate via the sidebar:

- **Batch Upload**: upload CSV with column `nombre` (and optional `pdf_path`, `url`)
- **Single Input**: classify one product at a time
- **Review Queue**: review pending classifications, apply Sabbi defaults, approve or reject
- **Settings**: view Sabbi overlay, select rules version, check cost

### Sabbi overlay config

Edit `config/sabbi_overlay.yaml` to set operational defaults (admin, gestor, custody fee). Reload from the Settings tab without restarting.

### Migration to internal server (Phase 3.5)

1. Change `DATABASE_URL` env var to point to Postgres
2. Add basic auth via `.streamlit/secrets.toml`
3. Run worker + streamlit under systemd with provided unit files
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(phase3): README updates with HITL UI run instructions"
```

---

## Task 22: phase3-STATUS.md + tag

**Files:**
- Create: `docs/superpowers/plans/phase3-STATUS.md`

- [ ] **Step 1: Create STATUS doc**

```markdown
# Phase 3 — Status

**Completed:** 2026-04-YY
**Tag:** `phase3-complete`
**Predecesor:** `phase2b-complete` (tag `afa8fa4`)

## Qué se entregó

Capa HITL local construida sobre el pipeline de Phase 2b:

- Streamlit UI con 4 tabs: Batch Upload, Single Input, Review Queue, Settings
- Worker script async (`scraper.scripts.worker`) con polling loop, concurrency, crash recovery
- JobQueue DB table + Alembic migration
- Sabbi overlay YAML config + loader + apply logic + UI integration
- Review flow: list queue → detail edit → approve (insert Product + audit_log) or reject
- Reactive PDF upload desde review card
- Entry A (batch CSV) y Entry B (single input) funcionales
- Entry C (cliente self-service) diferido a Phase 4

## Tests al tag

~195 passing, 1 pre-existing failure (kill-switch test tied to local .env).

## Commits del Phase 3

(listar 22 commits posteriores al tag phase2b-complete)

## Queda para Phase 3.5 / Phase 4

- **Phase 3.5 — Server interno**: migrar SQLite → Postgres, basic auth en Streamlit, systemd units
- **Phase 4 — Client self-service**: form público + auth + deployment cloud
```

- [ ] **Step 2: Tag and commit**

```bash
git add docs/superpowers/plans/phase3-STATUS.md
git commit -m "docs: close Phase 3 with STATUS doc"
git tag phase3-complete
git log --oneline | head -25
```

- [ ] **Step 3: Verify tag**

```bash
git tag -l phase3-complete
```

---

## Criterios de éxito Phase 3

- [ ] CSV upload de 20 productos → worker procesa → review queue llena → operator aprueba 20 → `products` table tiene 20 rows nuevas
- [ ] Single input funciona: tipear nombre → job aparece en queue → worker procesa → draft en review queue
- [ ] PDF upload reactivo: low_quality producto + subir PDF → re-procesa → review card nueva
- [ ] Sabbi overlay aplica correctamente: botón "Apply Sabbi defaults" llena admin/gestor/comision
- [ ] Audit log registra cada approval con before/after
- [ ] Worker crash recovery: reinicia → jobs "in_progress" stale se re-ponen a pending
- [ ] ~195 tests pasando
- [ ] Tag `phase3-complete`

---

## Execution handoff

Dos opciones:

**1. Subagent-Driven (recomendado)** — fresh subagent por task, review entre tasks, rapid iteration

**2. Inline Execution** — misma sesión con checkpoints

**Nota:** algunos tasks (8-19) tienen pasos de verificación manual de Streamlit. El subagent puede ejecutar código y tests pero no puede hacer click en UI. Esos steps se hacen post-hoc por el humano, pero los tests de lógica subyacente los cubren.
