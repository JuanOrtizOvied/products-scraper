"""Simple per-key circuit breaker for cascade parsers."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class _State:
    failures: list[float] = field(default_factory=list)  # timestamps
    opened_at: float | None = None


class CircuitBreaker:
    """Open the circuit after `fail_threshold` failures within the sliding window.

    While open, `is_open(key)` returns True until `cooldown_seconds` elapse since
    opening. Success resets the failure count immediately.
    """

    def __init__(
        self,
        fail_threshold: int = 5,
        window_seconds: float = 600.0,  # 10 min
        cooldown_seconds: float = 900.0,  # 15 min
    ) -> None:
        self.fail_threshold = fail_threshold
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        self._states: dict[str, _State] = {}
        self._lock = threading.Lock()

    def _state(self, key: str) -> _State:
        return self._states.setdefault(key, _State())

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            s = self._state(key)
            s.failures = [t for t in s.failures if now - t <= self.window_seconds]
            s.failures.append(now)
            if len(s.failures) >= self.fail_threshold and s.opened_at is None:
                s.opened_at = now

    def record_success(self, key: str) -> None:
        with self._lock:
            s = self._state(key)
            s.failures.clear()
            s.opened_at = None

    def is_open(self, key: str) -> bool:
        with self._lock:
            s = self._state(key)
            if s.opened_at is None:
                return False
            if time.monotonic() - s.opened_at > self.cooldown_seconds:
                s.opened_at = None
                s.failures.clear()
                return False
            return True


# Process-wide singleton (parsers share it)
BREAKER = CircuitBreaker()
