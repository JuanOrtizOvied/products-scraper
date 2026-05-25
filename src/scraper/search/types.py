"""Shared types for the search cascade."""
from __future__ import annotations

from dataclasses import dataclass, field

from scraper.agents.types import ExtractedFicha


@dataclass(frozen=True)
class CascadeResult:
    """Result of running the search cascade for a product name."""
    level: int  # 0=DB, 1=known targets, 2=web_search, 3=intensive
    fichas: list[ExtractedFicha] = field(default_factory=list)
    low_quality: bool = False  # True if we fell through without a confident hit

    @property
    def best_confidence(self) -> float:
        return max((f.source_confidence for f in self.fichas), default=0.0)
