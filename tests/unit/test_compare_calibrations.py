# tests/unit/test_compare_calibrations.py
"""Tests for calibration comparison script."""
from scraper.scripts.compare_calibrations import compare, format_report


def _make_results(accuracy: dict, cost: float = 0.05, n: int = 19) -> dict:
    return {
        "version": "test",
        "rules_path": "rules/test.md",
        "fetcher_backend": "legacy",
        "n_products": n,
        "per_attribute_accuracy": accuracy,
        "total_cost_usd": cost,
        "details": [
            {"nombre": f"p{i}", "global_confidence": 0.8, "elapsed_s": 10.0}
            for i in range(n)
        ],
    }


def test_compare_detects_improvement():
    v6 = _make_results({"comision": 0.895, "moneda": 1.0})
    v7 = _make_results({"comision": 0.947, "moneda": 1.0})
    result = compare(v6, v7)
    assert result["comision"]["delta"] > 0
    assert result["comision"]["status"] == "improved"
    assert result["moneda"]["status"] == "unchanged"


def test_compare_detects_regression():
    v6 = _make_results({"comision": 0.947})
    v7 = _make_results({"comision": 0.842})
    result = compare(v6, v7)
    assert result["comision"]["delta"] < 0
    assert result["comision"]["status"] == "regressed"


def test_format_report_produces_table():
    v6 = _make_results({"comision": 0.895, "moneda": 1.0}, cost=0.04)
    v7 = _make_results({"comision": 0.947, "moneda": 1.0}, cost=0.06)
    report = format_report(v6, v7)
    assert "comision" in report
    assert "COMPARISON" in report
