def test_apply_overlay_sets_admin_when_null():
    from scraper.overlay.loader import apply_overlay_defaults
    from scraper.overlay.types import SabbiOverlay, ViaSabbiBrokerage

    overlay = SabbiOverlay(
        via_sabbi_brokerage=ViaSabbiBrokerage(
            administrador="Credicorp Capital",
            gestor="Credicorp Capital",
            comision=0.0065,
        )
    )
    attributes = {
        "administrador": None,
        "gestor": None,
        "comision": None,
        "moneda": "dolares",
    }
    result = apply_overlay_defaults(attributes, overlay, choice="via_sabbi_brokerage")
    assert result["administrador"] == "Credicorp Capital"
    assert result["gestor"] == "Credicorp Capital"
    assert result["comision"] == 0.0065
    assert result["moneda"] == "dolares"


def test_apply_overlay_does_not_override_nonnull_values():
    from scraper.overlay.loader import apply_overlay_defaults
    from scraper.overlay.types import SabbiOverlay, ViaSabbiBrokerage

    overlay = SabbiOverlay(
        via_sabbi_brokerage=ViaSabbiBrokerage(
            administrador="Credicorp Capital",
            gestor="Credicorp Capital",
            comision=0.0065,
        )
    )
    attributes = {
        "administrador": "Pellegrini S.A.",
        "gestor": "Pellegrini S.A.",
        "comision": 0.0075,
    }
    result = apply_overlay_defaults(attributes, overlay, choice="via_sabbi_brokerage")
    assert result["administrador"] == "Pellegrini S.A."
    assert result["gestor"] == "Pellegrini S.A."
    assert result["comision"] == 0.0075


def test_apply_overlay_noop_when_choice_is_none():
    from scraper.overlay.loader import apply_overlay_defaults
    from scraper.overlay.types import SabbiOverlay

    overlay = SabbiOverlay()
    attributes = {"administrador": None}
    result = apply_overlay_defaults(attributes, overlay, choice=None)
    assert result == {"administrador": None}
