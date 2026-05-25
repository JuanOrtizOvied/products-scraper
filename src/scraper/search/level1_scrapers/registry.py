"""Registry of known-site parsers.

Currently empty. Phase 2b.1 removed the 7 Peruvian parsers that were
heuristic URL patterns without real content validation. Claude web_search
(cascade level N2) now handles the search layer universally.

Add new parsers here when a specific site is proven to have faster/cheaper
access than web_search AND reliable URL patterns. Each parser must implement
the `SiteParser` Protocol from `base.py`.
"""
from __future__ import annotations

from scraper.search.level1_scrapers.base import SiteParser

TARGETS: list[SiteParser] = []
