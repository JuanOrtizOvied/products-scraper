def test_accuracy_categorical_exact_match():
    from scraper.metrics.accuracy import categorical_match

    assert categorical_match("soles", "soles") is True
    assert categorical_match("SOLES", "soles") is True  # case insensitive
    assert categorical_match("soles ", "soles") is True  # strip
    assert categorical_match("dolares", "soles") is False
    assert categorical_match(None, None) is True
    assert categorical_match(None, "soles") is False


def test_accuracy_percentage_dict_exact():
    from scraper.metrics.accuracy import percentage_dict_match

    # Exact match passes
    assert percentage_dict_match({"Perú": 100.0}, {"Perú": 100.0}, tolerance_pp=5.0) is True


def test_accuracy_percentage_dict_within_tolerance():
    from scraper.metrics.accuracy import percentage_dict_match

    expected = {"Perú": 65.0, "USA": 35.0}
    actual = {"Perú": 63.0, "USA": 37.0}  # ±2pp each — within tolerance
    assert percentage_dict_match(expected, actual, tolerance_pp=5.0) is True


def test_accuracy_percentage_dict_outside_tolerance():
    from scraper.metrics.accuracy import percentage_dict_match

    expected = {"Perú": 65.0, "USA": 35.0}
    actual = {"Perú": 50.0, "USA": 50.0}  # 15pp off — out of tolerance
    assert percentage_dict_match(expected, actual, tolerance_pp=5.0) is False


def test_accuracy_percentage_dict_missing_key():
    from scraper.metrics.accuracy import percentage_dict_match

    expected = {"Perú": 50.0, "USA": 50.0}
    actual = {"Perú": 50.0}  # missing USA entirely
    assert percentage_dict_match(expected, actual, tolerance_pp=5.0) is False


def test_accuracy_numeric_relative_within_5pct():
    from scraper.metrics.accuracy import numeric_match

    assert numeric_match(0.0325, 0.033, rel_tolerance=0.05) is True
    assert numeric_match(0.0325, 0.04, rel_tolerance=0.05) is False
    assert numeric_match(None, None, rel_tolerance=0.05) is True
    assert numeric_match(0.0325, None, rel_tolerance=0.05) is False


def test_compute_product_accuracy_all_correct():
    from scraper.agents.types import AttributeClassification, ClassificationResult
    from scraper.metrics.accuracy import compute_product_accuracy

    ground_truth = {
        "foco_geografico": {"Perú": 100.0},
        "clase_activo": {"Mercados Públicos - Variable": 100.0},
        "subyacentes": {"Acciones Peru": 100.0},
        "comision": 0.0325,
        "moneda": "soles",
    }
    predicted = ClassificationResult(
        producto="X",
        attributes={
            "foco_geografico": AttributeClassification(
                value={"Perú": 100.0},
                confidence=1.0,
                reasoning="",
                rule_applied="",
            ),
            "clase_activo": AttributeClassification(
                value={"Mercados Públicos - Variable": 100.0},
                confidence=1.0,
                reasoning="",
                rule_applied="",
            ),
            "subyacente": AttributeClassification(
                value={"Acciones Peru": 100.0},
                confidence=1.0,
                reasoning="",
                rule_applied="",
            ),
            "comision": AttributeClassification(
                value=0.0325,
                confidence=1.0,
                reasoning="",
                rule_applied="",
            ),
            "moneda": AttributeClassification(
                value="soles",
                confidence=1.0,
                reasoning="",
                rule_applied="",
            ),
        },
        global_confidence=1.0,
        unknowns=[],
    )
    report = compute_product_accuracy(ground_truth, predicted)
    assert report["foco_geografico"] is True
    assert report["clase_activo"] is True
    assert report["subyacente"] is True
    assert report["comision"] is True
    assert report["moneda"] is True


def test_categorical_match_corporate_suffix_credicorp():
    from scraper.metrics.accuracy import categorical_match

    assert categorical_match("Credicorp Capital", "Credicorp Capital S.A. SAF") is True
    assert categorical_match("Credicorp Capital SAF", "Credicorp Capital S.A.") is True
    assert categorical_match("Core Capital", "Core Capital SAFI") is True


def test_categorical_match_corporate_suffix_pellegrini():
    from scraper.metrics.accuracy import categorical_match

    assert categorical_match("Pellegrini S.A.", "Pellegrini") is True
    assert categorical_match("Pellegrini S.A.S.G.F.C.I.", "Pellegrini") is True


def test_categorical_match_corporate_suffix_sociedad_gerente():
    from scraper.metrics.accuracy import categorical_match

    assert categorical_match(
        "Banchile",
        "Banchile Administradora General de Fondos S.A.",
    ) is True


def test_categorical_match_different_entities_still_fail():
    """Different actual entities must NOT be matched."""
    from scraper.metrics.accuracy import categorical_match

    assert categorical_match("Credicorp Capital", "BCP Capital") is False
    assert categorical_match("Santander", "Credicorp") is False


def test_strip_corporate_suffix_variants():
    from scraper.metrics.accuracy import _strip_corporate_suffix

    assert _strip_corporate_suffix("Credicorp Capital S.A. SAF") == "credicorp capital"
    assert _strip_corporate_suffix("Pellegrini S.A.") == "pellegrini"
    assert _strip_corporate_suffix("Core Capital SAFI") == "core capital"
    assert _strip_corporate_suffix("Just A Name") == "just a name"
    assert _strip_corporate_suffix("") == ""


def test_categorical_match_sociedad_administradora_de_fondos():
    """Real-world case: Credicorp admin name with full 'Sociedad Administradora de Fondos'."""
    from scraper.metrics.accuracy import categorical_match

    assert categorical_match(
        "Credicorp Capital",
        "Credicorp Capital S.A. Sociedad Administradora de Fondos",
    ) is True


def test_categorical_match_sociedad_administradora_de_fondos_de_inversion():
    """Real-world case: Core Capital admin full legal name with 'de Inversión'."""
    from scraper.metrics.accuracy import categorical_match

    assert categorical_match(
        "Core Capital",
        "Core Capital Sociedad Administradora de Fondos de Inversión S.A.",
    ) is True


def test_strip_corporate_suffix_multiword_administradora():
    from scraper.metrics.accuracy import _strip_corporate_suffix

    assert (
        _strip_corporate_suffix("Credicorp Capital S.A. Sociedad Administradora de Fondos")
        == "credicorp capital"
    )
    assert (
        _strip_corporate_suffix(
            "Core Capital Sociedad Administradora de Fondos de Inversión S.A."
        )
        == "core capital"
    )
    # Accent stripping also handles 'Inversión' → 'inversion'
    assert (
        _strip_corporate_suffix("X Administradora de Fondos de Inversión")
        == "x"
    )
