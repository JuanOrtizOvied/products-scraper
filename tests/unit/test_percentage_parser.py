import pytest


def test_parses_simple_two_regions():
    from scraper.parsers.percentage_parser import parse_percentages
    result = parse_percentages("Perú 65%, USA 35%")
    assert result == {"Perú": 65.0, "USA": 35.0}


def test_parses_three_with_latam():
    from scraper.parsers.percentage_parser import parse_percentages
    result = parse_percentages("Perú 75%, Emergentes ex-Perú 15%, Latam ex-Perú 10%")
    assert result == {"Perú": 75.0, "Emergentes ex-Perú": 15.0, "Latam ex-Perú": 10.0}


def test_parses_100_percent():
    from scraper.parsers.percentage_parser import parse_percentages
    result = parse_percentages("Peru 100%")
    assert result == {"Peru": 100.0}


def test_parses_parentheses_format():
    from scraper.parsers.percentage_parser import parse_percentages
    result = parse_percentages("EEUU (100%)")
    assert result == {"EEUU": 100.0}


def test_parses_decimal_percentages():
    from scraper.parsers.percentage_parser import parse_percentages
    result = parse_percentages("Mercados publicos variable 62.44%, Mercados publicos fijo 21.78%")
    assert result == pytest.approx(
        {"Mercados publicos variable": 62.44, "Mercados publicos fijo": 21.78}
    )


def test_parses_newline_separated():
    from scraper.parsers.percentage_parser import parse_percentages
    result = parse_percentages("Mercados publicos fijo 62.31%\nEfectivo 31.51%")
    assert result == pytest.approx({"Mercados publicos fijo": 62.31, "Efectivo": 31.51})


def test_empty_string_returns_empty_dict():
    from scraper.parsers.percentage_parser import parse_percentages
    assert parse_percentages("") == {}


def test_nan_returns_empty_dict():
    from scraper.parsers.percentage_parser import parse_percentages
    assert parse_percentages(None) == {}


def test_raises_when_percents_dont_sum_to_100_strict_mode():
    from scraper.parsers.percentage_parser import PercentageSumError, parse_percentages
    with pytest.raises(PercentageSumError):
        parse_percentages("Perú 50%, USA 30%", strict_sum=True)


def test_sum_tolerance_5_allows_minor_rounding():
    from scraper.parsers.percentage_parser import parse_percentages
    result = parse_percentages("A 33.31%, B 33.31%, C 33.31%", strict_sum=True)
    assert sum(result.values()) == pytest.approx(99.93)


def test_parses_label_starting_with_digit():
    from scraper.parsers.percentage_parser import parse_percentages
    result = parse_percentages("3M Corp 40%, USA 60%")
    assert result == {"3M Corp": 40.0, "USA": 60.0}
