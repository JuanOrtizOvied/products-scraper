"""Tests for UI component helper functions (logic only, no Streamlit rendering)."""
from scraper.ui.components.confidence_bar import confidence_color, confidence_label
from scraper.ui.components.dict_editor import normalize_pct_dict


def test_confidence_color_green():
    assert confidence_color(0.95) == "#22c55e"


def test_confidence_color_yellow():
    assert confidence_color(0.80) == "#eab308"


def test_confidence_color_red():
    assert confidence_color(0.50) == "#ef4444"


def test_confidence_label():
    assert confidence_label(0.95) == "0.95"
    assert confidence_label(0.0) == "0.00"
    assert confidence_label(None) == "—"


def test_normalize_pct_dict_sums_to_100():
    d = {"A": 70, "B": 30}
    assert normalize_pct_dict(d) == {"A": 70.0, "B": 30.0}


def test_normalize_pct_dict_empty():
    assert normalize_pct_dict({}) == {}


def test_normalize_pct_dict_strips_zeros():
    d = {"A": 100, "B": 0}
    assert normalize_pct_dict(d) == {"A": 100.0}
