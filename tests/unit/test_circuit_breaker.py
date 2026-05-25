def test_circuit_breaker_initially_closed():
    from scraper.search.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker(fail_threshold=3, cooldown_seconds=60)
    assert cb.is_open("x.com") is False


def test_circuit_breaker_opens_after_threshold():
    from scraper.search.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker(fail_threshold=3, cooldown_seconds=60)
    cb.record_failure("x.com")
    cb.record_failure("x.com")
    assert cb.is_open("x.com") is False
    cb.record_failure("x.com")
    assert cb.is_open("x.com") is True


def test_circuit_breaker_success_resets():
    from scraper.search.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker(fail_threshold=3, cooldown_seconds=60)
    cb.record_failure("x.com")
    cb.record_failure("x.com")
    cb.record_success("x.com")
    cb.record_failure("x.com")
    cb.record_failure("x.com")
    assert cb.is_open("x.com") is False  # reset on success; only 2 recent fails


def test_circuit_breaker_cooldown_closes():
    import time

    from scraper.search.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker(fail_threshold=2, cooldown_seconds=0.05)
    cb.record_failure("x.com")
    cb.record_failure("x.com")
    assert cb.is_open("x.com") is True
    time.sleep(0.08)
    assert cb.is_open("x.com") is False  # cooldown expired
