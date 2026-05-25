"""Central structlog configuration. Call configure_logging() at app startup."""
from __future__ import annotations

import logging

import structlog


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    """Configure structlog globally.

    Call once at app startup (CLI entry points, FastAPI startup, tests).
    """
    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]
    if json_logs:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=False))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=level, format="%(message)s")
    # basicConfig is a no-op when handlers already exist (e.g. in pytest);
    # explicitly set the root level so tests and runtime behave consistently.
    logging.getLogger().setLevel(level)
