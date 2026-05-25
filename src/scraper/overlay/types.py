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
