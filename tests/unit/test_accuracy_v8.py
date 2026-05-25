"""Tests for v8 accuracy metric fixes."""
from scraper.agents.types import AttributeClassification, ClassificationResult, DistributionResult
from scraper.metrics.accuracy import compute_product_accuracy, compute_product_accuracy_v8, compute_distribution_accuracy, percentage_dict_match


def test_pct_dict_ignores_small_keys_in_predicted():
    """Predicted {'Variable': 98, 'Cash': 2} should match gt {'Variable': 100}."""
    gt = {"Mercados Públicos - Variable": 100.0}
    pred = {"Mercados Públicos - Variable": 98.0, "Cash y Otros": 2.0}
    assert percentage_dict_match(gt, pred) is True


def test_pct_dict_does_not_ignore_large_keys():
    """Predicted {'Variable': 80, 'Fijo': 20} should NOT match gt {'Variable': 100}."""
    gt = {"Mercados Públicos - Variable": 100.0}
    pred = {"Mercados Públicos - Variable": 80.0, "Mercados Públicos - Fijo": 20.0}
    assert percentage_dict_match(gt, pred) is False


def test_pct_dict_exact_match_still_works():
    gt = {"Perú": 65.0, "EEUU": 35.0}
    pred = {"Perú": 63.0, "EEUU": 37.0}
    assert percentage_dict_match(gt, pred) is True


def test_pct_dict_both_empty():
    assert percentage_dict_match({}, {}) is True


def test_pct_dict_both_none():
    assert percentage_dict_match(None, None) is True


def test_pct_dict_ignores_small_keys_in_gt_too():
    """GT has a small key that predicted omits — should still match."""
    gt = {"Emergentes ex-Perú": 98.0, "Cash": 2.0}
    pred = {"Emergentes ex-Perú": 100.0}
    assert percentage_dict_match(gt, pred) is True


def test_should_skip_none_gt_minimo():
    from scraper.metrics.accuracy import _should_skip_none_gt
    assert _should_skip_none_gt("minimo_inversion", None) is True
    assert _should_skip_none_gt("minimo_inversion", "5000 USD") is False
    assert _should_skip_none_gt("moneda", None) is False


def test_compute_accuracy_skips_none_gt_minimo():
    gt = {
        "foco_geografico": {"EEUU": 100.0},
        "clase_activo": {"Mercados Públicos - Variable": 100.0},
        "subyacentes": {"US Large Cap": 100.0},
        "comision": 0.0065,
        "moneda": "dolares",
        "administrador": "BlackRock",
        "gestor": "BlackRock",
        "liquidez": "Inmediata",
        "minimo_inversion": None,
    }
    pred = ClassificationResult(
        producto="test",
        global_confidence=0.9,
        attributes={
            "foco_geografico": AttributeClassification(value={"EEUU": 100.0}, confidence=0.9, reasoning="", rule_applied=""),
            "clase_activo": AttributeClassification(value={"Mercados Públicos - Variable": 100.0}, confidence=0.9, reasoning="", rule_applied=""),
            "subyacente": AttributeClassification(value={"US Large Cap": 100.0}, confidence=0.9, reasoning="", rule_applied=""),
            "comision": AttributeClassification(value=0.0065, confidence=0.9, reasoning="", rule_applied=""),
            "moneda": AttributeClassification(value="dolares", confidence=0.9, reasoning="", rule_applied=""),
            "administrador": AttributeClassification(value="BlackRock", confidence=0.9, reasoning="", rule_applied=""),
            "gestor": AttributeClassification(value="BlackRock", confidence=0.9, reasoning="", rule_applied=""),
            "liquidez": AttributeClassification(value="Inmediata", confidence=0.9, reasoning="", rule_applied=""),
            "minimo_inversion": AttributeClassification(value="1 acción (~$82 USD)", confidence=0.9, reasoning="", rule_applied=""),
        },
    )
    report = compute_product_accuracy(gt, pred)
    assert report["minimo_inversion"] is True


def test_product_accuracy_v8_uses_product_layer_keys():
    """v8 accuracy uses administrador_producto, comision_producto, etc."""
    gt = {
        "foco_geografico": {"EEUU": 100.0},
        "clase_activo": {"Mercados Públicos - Fijo": 100.0},
        "subyacentes": {"US Treasuries Corto Plazo": 100.0},
        "comision_producto": 0.0015,
        "moneda": "dolares",
        "administrador_producto": "BlackRock",
        "gestor_producto": "BlackRock Fund Advisors",
        "liquidez_producto": "Inmediata",
        "minimo_inversion_producto": None,
    }
    pred = ClassificationResult(
        producto="SHY",
        global_confidence=0.95,
        attributes={
            "foco_geografico": AttributeClassification(value={"EEUU": 100.0}, confidence=0.9, reasoning="", rule_applied=""),
            "clase_activo": AttributeClassification(value={"Mercados Públicos - Fijo": 100.0}, confidence=0.9, reasoning="", rule_applied=""),
            "subyacente": AttributeClassification(value={"US Treasuries Corto Plazo": 100.0}, confidence=0.9, reasoning="", rule_applied=""),
            "comision": AttributeClassification(value=0.0015, confidence=0.9, reasoning="", rule_applied=""),
            "moneda": AttributeClassification(value="dolares", confidence=0.9, reasoning="", rule_applied=""),
            "administrador": AttributeClassification(value="BlackRock", confidence=0.9, reasoning="", rule_applied=""),
            "gestor": AttributeClassification(value="BlackRock Fund Advisors", confidence=0.9, reasoning="", rule_applied=""),
            "liquidez": AttributeClassification(value="Inmediata", confidence=0.9, reasoning="", rule_applied=""),
            "minimo_inversion": AttributeClassification(value="1 acción", confidence=0.9, reasoning="", rule_applied=""),
        },
    )
    report = compute_product_accuracy_v8(gt, pred)
    assert all(v is True for v in report.values()), f"Failures: {[k for k, v in report.items() if not v]}"


def test_distribution_accuracy_full_match():
    gt = {
        "intermediario": "UBS",
        "tipo_intermediario": "custodio",
        "comision_distribucion": 0.0065,
    }
    pred = DistributionResult(
        producto="SHY",
        intermediario="UBS",
        tipo_intermediario="custodio",
        comision_distribucion=0.0065,
        confidence=0.9,
        reasoning="test",
    )
    report = compute_distribution_accuracy(gt, pred)
    assert report["intermediario"] is True
    assert report["tipo_intermediario"] is True
    assert report["comision_distribucion"] is True


def test_distribution_accuracy_partial():
    gt = {
        "intermediario": "Credicorp Capital",
        "tipo_intermediario": "broker",
        "comision_distribucion": 0.0065,
    }
    pred = DistributionResult(
        producto="BACKUSI1",
        intermediario="Credicorp Capital SAF",
        tipo_intermediario="broker",
        comision_distribucion=None,
        confidence=0.7,
        reasoning="test",
    )
    report = compute_distribution_accuracy(gt, pred)
    assert report["intermediario"] is True  # corporate suffix stripped
    assert report["tipo_intermediario"] is True
    assert report["comision_distribucion"] is False
