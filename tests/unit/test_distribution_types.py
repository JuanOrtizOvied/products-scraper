"""Tests for DistributionResult dataclass."""
from scraper.agents.types import DistributionResult


def test_distribution_result_creation():
    dr = DistributionResult(
        producto="iShares SHY",
        intermediario="UBS",
        tipo_intermediario="custodio",
        comision_distribucion=0.0065,
        minimo_via_intermediario="USD 70,000",
        liquidez_via_intermediario="Mediano plazo",
        confidence=0.85,
        reasoning="Found on UBS Peru catalog",
        source_url="https://ubs.com/pe/funds",
    )
    assert dr.intermediario == "UBS"
    assert dr.tipo_intermediario == "custodio"
    assert dr.comision_distribucion == 0.0065


def test_distribution_result_from_json():
    data = {
        "producto": "SHY",
        "intermediario": "UBS",
        "tipo_intermediario": "custodio",
        "comision_distribucion": 0.0065,
        "minimo_via_intermediario": None,
        "liquidez_via_intermediario": None,
        "confidence": 0.8,
        "reasoning": "test",
        "source_url": None,
    }
    dr = DistributionResult.from_json(data)
    assert dr.intermediario == "UBS"
    assert dr.confidence == 0.8


def test_distribution_result_to_json():
    dr = DistributionResult(
        producto="SHY",
        intermediario="UBS",
        tipo_intermediario="custodio",
        comision_distribucion=0.0065,
        confidence=0.8,
        reasoning="test",
    )
    payload = dr.to_json()
    assert isinstance(payload, dict)
    assert payload["intermediario"] == "UBS"
    assert payload["tipo_intermediario"] == "custodio"


def test_distribution_result_safi_shortcut():
    dr = DistributionResult.from_product_layer(
        producto="Fondo Habilitador",
        administrador_producto="Core Capital SAFI",
        comision_producto=0.005,
        liquidez_producto="Mediano plazo",
        minimo_producto=None,
    )
    assert dr.intermediario == "Core Capital SAFI"
    assert dr.tipo_intermediario == "safi"
    assert dr.comision_distribucion == 0.005
    assert dr.confidence == 1.0
