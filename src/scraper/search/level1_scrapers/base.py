"""Protocol for per-site parsers (N1 — targets conocidos)."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from scraper.agents.types import ExtractedFicha
from scraper.llm import LLMClient


@runtime_checkable
class SiteParser(Protocol):
    """One parser per known site. Each declares its domain and owns its URL
    patterns / CSS selectors.

    Implementations must be async-safe and stateless (no per-instance caches
    that leak between requests).
    """

    domain: str = ""  # e.g. "credicorpcapital.com"

    async def search_by_name(self, nombre: str) -> list[str]:
        """Given a product name, return candidate URLs on this site."""
        ...

    async def parse_ficha(self, url: str, llm: LLMClient) -> ExtractedFicha:
        """Fetch url, extract structured ficha (by going through Claude extractor)."""
        ...
