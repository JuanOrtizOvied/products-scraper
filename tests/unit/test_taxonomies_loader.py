def test_loads_six_asset_classes():
    from scraper.taxonomies.loader import load_asset_classes
    classes = load_asset_classes()
    assert len(classes) == 6
    names = {c.name for c in classes}
    assert names == {
        "Inmobiliario Directo",
        "Mercados Públicos - Fijo",
        "Mercados Públicos - Variable",
        "Mercados Privados",
        "Club deals",
        "Cash y Otros",
    }


def test_canonical_assets_all_reference_valid_macro_class():
    from scraper.taxonomies.loader import load_asset_classes, load_canonical_assets
    macro_names = {c.name for c in load_asset_classes()}
    for asset in load_canonical_assets():
        assert asset.macro_class in macro_names, \
            f"{asset.name} references invalid macro {asset.macro_class}"


def test_loads_five_regions_summing_to_one():
    from scraper.taxonomies.loader import load_regions
    regions = load_regions()
    assert len(regions) == 5
    total = sum(r.benchmark_weight for r in regions)
    assert abs(total - 1.0) < 0.001, f"Weights sum to {total}, expected 1.0"


def test_asset_name_is_unique():
    from scraper.taxonomies.loader import load_canonical_assets
    names = [a.name for a in load_canonical_assets()]
    assert len(names) == len(set(names)), "Duplicate canonical asset names"
