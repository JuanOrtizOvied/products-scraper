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
from scraper.scripts.worker_ops import claim_pending_jobs

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

log = structlog.get_logger()

MAX_CONCURRENT = int(os.environ.get("WORKER_MAX_CONCURRENT", "3"))
POLL_INTERVAL = float(os.environ.get("WORKER_POLL_INTERVAL_S", "5.0"))


async def _process_job(job: JobQueue) -> None:
    from pathlib import Path

    from scraper.llm import LLMClient
    from scraper.scripts.worker_ops import mark_job_done, mark_job_failed
    from scraper.scripts.worker_pipeline import process_job_via_cascade

    try:
        rules_md = (Path.cwd() / "rules" / "v8.md").read_text(encoding="utf-8")
        llm = LLMClient()

        async with get_session() as s:
            fresh_job = await s.get(JobQueue, job.id)
            if fresh_job is None:
                log.warning("job_disappeared", job_id=job.id)
                return

            if fresh_job.pdf_path is not None:
                from scraper.scripts.worker_pipeline import process_job_via_pdf

                classification_id = await process_job_via_pdf(
                    session=s, job=fresh_job, llm=llm, rules_md=rules_md
                )
            elif fresh_job.url is not None:
                from scraper.scripts.worker_pipeline import process_job_via_url

                classification_id = await process_job_via_url(
                    session=s, job=fresh_job, llm=llm, rules_md=rules_md
                )
            else:
                classification_id = await process_job_via_cascade(
                    session=s, job=fresh_job, llm=llm, rules_md=rules_md
                )

        async with get_session() as s:
            await mark_job_done(s, job.id, classification_id=classification_id)
    except Exception as e:
        import traceback as _tb
        log.warning("worker_job_failed", job_id=job.id, error=str(e))
        async with get_session() as s:
            await mark_job_failed(s, job.id, error=_tb.format_exc())


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
