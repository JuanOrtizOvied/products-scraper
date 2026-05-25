"""CLI: extract ficha from a URL or PDF path.

Usage:
    poetry run python -m scraper.scripts.extract_one --url https://example.com/fondo
    poetry run python -m scraper.scripts.extract_one --pdf path/to/ficha.pdf
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import structlog

from scraper.config import get_settings
from scraper.extract.html import extract_from_url
from scraper.extract.pdf import extract_from_pdf
from scraper.llm import LLMClient
from scraper.logging_config import configure_logging

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

log = structlog.get_logger()


async def _main(url: str | None, pdf: str | None) -> int:
    configure_logging(level="INFO", json_logs=False)

    if (url is None) == (pdf is None):
        print("ERROR: provide exactly one of --url or --pdf", file=sys.stderr)
        return 2

    settings = get_settings()
    if not settings.anthropic_api_key:
        print("ERROR: ANTHROPIC_API_KEY no configurada en .env", file=sys.stderr)
        return 2

    llm = LLMClient()
    if url is not None:
        fichas = await extract_from_url(url=url, llm=llm)
    else:
        ficha = await extract_from_pdf(path=Path(pdf), llm=llm)
        fichas = [ficha]

    output = [f.to_json() for f in fichas]
    print(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\nExtracted {len(fichas)} ficha(s)", file=sys.stderr)
    print(f"Cost: ${llm.cost.total_usd:.4f}", file=sys.stderr)
    return 0


def cli() -> None:
    parser = argparse.ArgumentParser(description="Extract ficha from URL or PDF.")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--url", help="URL of HTML page to extract")
    g.add_argument("--pdf", help="Path to PDF file to extract")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.url, args.pdf)))


if __name__ == "__main__":
    cli()
