def test_load_sabbi_overlay_parses_yaml():
    from scraper.overlay.loader import load_sabbi_overlay

    overlay = load_sabbi_overlay()
    assert overlay.via_sabbi_brokerage is not None
    assert overlay.via_sabbi_brokerage.administrador == "Credicorp Capital"
    assert overlay.via_sabbi_brokerage.gestor == "Credicorp Capital"
    assert overlay.via_sabbi_brokerage.comision == 0.0065


def test_load_sabbi_overlay_reload_clears_cache():
    from scraper.overlay.loader import load_sabbi_overlay, reload_sabbi_overlay

    load_sabbi_overlay()
    reload_sabbi_overlay()
    o2 = load_sabbi_overlay()
    assert o2.via_sabbi_brokerage.administrador == "Credicorp Capital"
