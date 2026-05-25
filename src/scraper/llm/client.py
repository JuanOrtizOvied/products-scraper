"""AsyncAnthropic wrapper with cost tracking, retry, and prompt caching support."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from anthropic.types import Message, MessageParam

from scraper.config import get_settings
from scraper.llm.cost import ClaudeCost, Usage, calculate_cost
from scraper.llm.retry import make_retry

log = structlog.get_logger()


@dataclass
class CallResult:
    """Outcome of a single Claude API call."""

    model: str
    response_text: str
    raw_message: Message
    cost: ClaudeCost
    duration_ms: int


@dataclass
class CostAccumulator:
    total_usd: float = 0.0
    call_count: int = 0
    by_model: dict[str, float] = field(default_factory=dict)

    def add(self, model: str, cost: ClaudeCost) -> None:
        self.total_usd += cost.total_usd
        self.call_count += 1
        self.by_model[model] = self.by_model.get(model, 0.0) + cost.total_usd


class LLMClient:
    """Wraps AsyncAnthropic with cost tracking + retry."""

    def __init__(self, api_key: str | None = None) -> None:
        settings = get_settings()
        self._client = AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)
        self.cost = CostAccumulator()

    async def call(
        self,
        *,
        model: str,
        system: str | list[dict[str, Any]],
        messages: list[MessageParam],
        max_tokens: int = 4096,
        temperature: float | None = None,
        extra_headers: dict[str, str] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> CallResult:
        """Make a Claude call with retry + cost tracking.

        Note: ``temperature`` defaults to None (omitted) because newer Claude
        models (Opus 4.7, Sonnet 4.6+) rejected the parameter. Pass explicitly
        only when targeting a model that still accepts it.
        """
        start = time.monotonic()
        retryer = make_retry()
        msg: Message | None = None
        create_kwargs: dict[str, Any] = {
            "model": model,
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
            "extra_headers": extra_headers or {},
        }
        if temperature is not None:
            create_kwargs["temperature"] = temperature
        if tools is not None:
            create_kwargs["tools"] = tools
        async for attempt in retryer:
            with attempt:
                msg = await self._client.messages.create(**create_kwargs)
        assert msg is not None  # tenacity reraise=True guarantees success or exception
        duration_ms = int((time.monotonic() - start) * 1000)

        u = msg.usage
        usage = Usage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )
        cost = calculate_cost(model, usage)
        self.cost.add(model, cost)
        log.info(
            "llm_call",
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read=usage.cache_read_tokens,
            cache_write=usage.cache_write_tokens,
            cost_usd=round(cost.total_usd, 4),
            duration_ms=duration_ms,
        )

        text_parts = [b.text for b in msg.content if b.type == "text"]  # type: ignore[attr-defined]
        response_text = "\n".join(text_parts)

        return CallResult(
            model=model,
            response_text=response_text,
            raw_message=msg,
            cost=cost,
            duration_ms=duration_ms,
        )
