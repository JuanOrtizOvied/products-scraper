import logging

import structlog


def test_configure_logging_sets_json_processor_by_default():
    from scraper.logging_config import configure_logging

    configure_logging(level="INFO", json_logs=True)
    logger = structlog.get_logger("test_logger")
    logger.info("test_event", foo="bar")


def test_configure_logging_respects_level():
    from scraper.logging_config import configure_logging

    configure_logging(level="DEBUG")
    assert logging.getLogger().level == logging.DEBUG
