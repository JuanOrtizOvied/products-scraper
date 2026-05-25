"""Distribution agent — finds the Peruvian intermediary for a product."""
from __future__ import annotations

import json
import re
from typing import Any

import structlog

from scraper.agents.classifier import _strip_fences
from scraper.agents.types import DistributionResult
from scraper.llm import LLMClient

log = structlog.get_logger()

DISTRIBUTOR_MODEL = "claude-sonnet-4-6"
_WEBSEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}
_PROMPT_PATH = __import__("pathlib").Path(__file__).parent / "prompts" / "distributor_system.md"

_SAFI_PATTERNS = re.compile(
    r"\b(safi|saf|sgfci|s\.a\.f\.i\.|s\.a\.f\.|sociedad administradora de fondos)\b",
    re.IGNORECASE,
)


def _is_peruvian_safi(name: str | None) -> bool:
    if not name:
        return False
    return bool(_SAFI_PATTERNS.search(name))


def _build_distribution_user_message(
    nombre: str,
    administrador_producto: str | None,
    clase_activo: dict[str, float] | None = None,
) -> str:
    parts = [f'Producto: "{nombre}"']
    if administrador_producto:
        parts.append(f"Administrador real del producto: {administrador_producto}")
    if clase_activo:
        dominant = max(clase_activo.items(), key=lambda kv: kv[1])[0] if clase_activo else None
        if dominant:
            parts.append(f"Clase de activo: {dominant}")
    parts.append("Encontrá quién distribuye este producto en Perú.")
    return "\n".join(parts)


async def find_distribution(
    *,
    llm: LLMClient,
    nombre: str,
    administrador_producto: str | None,
    comision_producto: float | None = None,
    clase_activo: dict[str, float] | None = None,
    liquidez_producto: str | None = None,
    minimo_producto: str | None = None,
) -> DistributionResult:
    if _is_peruvian_safi(administrador_producto):
        return DistributionResult.from_product_layer(
            producto=nombre,
            administrador_producto=administrador_producto,
            comision_producto=comision_producto,
            liquidez_producto=liquidez_producto,
            minimo_producto=minimo_producto,
        )

    system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    user_msg = _build_distribution_user_message(nombre, administrador_producto, clase_activo)

    try:
        result = await llm.call(
            model=DISTRIBUTOR_MODEL,
            system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=4096,
            tools=[_WEBSEARCH_TOOL],
        )
    except Exception as e:
        log.warning("distribution_agent_failed", error=str(e), nombre=nombre)
        return DistributionResult(producto=nombre, confidence=0.0, reasoning=f"Agent error: {e}")

    clean = _strip_fences(result.response_text)
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError:
        log.warning("distribution_parse_failed", output=clean[:200], nombre=nombre)
        return DistributionResult(producto=nombre, confidence=0.0, reasoning="Parse error")

    return DistributionResult.from_json(payload)
