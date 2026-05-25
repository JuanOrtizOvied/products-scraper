import pytest


def test_cost_sonnet_46_calculation():
    from scraper.llm.cost import Usage, calculate_cost

    usage = Usage(input_tokens=1000, output_tokens=500, cache_read_tokens=0, cache_write_tokens=0)
    cost = calculate_cost("claude-sonnet-4-6", usage)
    # 1000/1e6 * 3 + 500/1e6 * 15 = 0.003 + 0.0075 = 0.0105
    assert cost.total_usd == pytest.approx(0.0105, rel=1e-3)


def test_cost_opus_47_higher_than_sonnet():
    from scraper.llm.cost import Usage, calculate_cost

    usage = Usage(input_tokens=1000, output_tokens=500, cache_read_tokens=0, cache_write_tokens=0)
    sonnet = calculate_cost("claude-sonnet-4-6", usage)
    opus = calculate_cost("claude-opus-4-7", usage)
    assert opus.total_usd > sonnet.total_usd


def test_cost_cache_read_is_90_percent_discount():
    from scraper.llm.cost import Usage, calculate_cost

    usage_normal = Usage(
        input_tokens=1_000_000, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0
    )
    usage_cached = Usage(
        input_tokens=0, output_tokens=0, cache_read_tokens=1_000_000, cache_write_tokens=0
    )

    normal_cost = calculate_cost("claude-sonnet-4-6", usage_normal)
    cached_cost = calculate_cost("claude-sonnet-4-6", usage_cached)

    # cached should be 10% of normal
    assert cached_cost.total_usd == pytest.approx(normal_cost.total_usd * 0.10, rel=0.01)


def test_cost_unknown_model_raises():
    from scraper.llm.cost import Usage, calculate_cost

    with pytest.raises(ValueError, match="Unknown model"):
        calculate_cost("claude-fictional-99", Usage(1, 1, 0, 0))
