"""Retry helper for Anthropic API calls with exponential backoff."""
from __future__ import annotations

from anthropic import APIConnectionError, APIStatusError, RateLimitError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


def make_retry() -> AsyncRetrying:
    """Standard retry policy: 3 attempts, 2s-4s-8s backoff, transient errors only."""
    return AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=8),
        retry=retry_if_exception_type((APIConnectionError, RateLimitError, APIStatusError)),
        reraise=True,
    )
