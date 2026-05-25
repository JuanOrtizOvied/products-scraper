"""Tests for distribution agent."""
from unittest.mock import MagicMock

import pytest

from scraper.agents.distributor import (
    _is_peruvian_safi,
    _build_distribution_user_message,
    find_distribution,
)
from scraper.agents.types import DistributionResult


def test_is_peruvian_safi_positive():
    assert _is_peruvian_safi("Core Capital SAFI") is True
    assert _is_peruvian_safi("Credicorp Capital S.A. SAF") is True
    assert _is_peruvian_safi("Credicorp Capital SAF") is True


def test_is_peruvian_safi_negative():
    assert _is_peruvian_safi("BlackRock") is False
    assert _is_peruvian_safi("J.P. Morgan Asset Management") is False
    assert _is_peruvian_safi(None) is False


def test_build_distribution_user_message():
    msg = _build_distribution_user_message(
        nombre="iShares SHY",
        administrador_producto="BlackRock",
        clase_activo={"Mercados Públicos - Fijo": 100.0},
    )
    assert "iShares SHY" in msg
    assert "BlackRock" in msg


@pytest.mark.asyncio
async def test_find_distribution_safi_shortcut():
    llm = MagicMock()
    result = await find_distribution(
        llm=llm,
        nombre="Fondo Habilitador",
        administrador_producto="Core Capital SAFI",
        comision_producto=0.005,
        clase_activo={"Mercados Privados - Deuda": 100.0},
    )
    assert isinstance(result, DistributionResult)
    assert result.intermediario == "Core Capital SAFI"
    assert result.tipo_intermediario == "safi"
    assert result.confidence == 1.0
    llm.call.assert_not_called()
