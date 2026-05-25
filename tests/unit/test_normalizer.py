def test_normalize_asset_class_exact_canonical_passes_through():
    from scraper.taxonomies.normalizer import normalize_asset_class
    assert normalize_asset_class("Mercados Públicos - Variable") == "Mercados Públicos - Variable"


def test_normalize_asset_class_known_variant():
    from scraper.taxonomies.normalizer import normalize_asset_class
    assert normalize_asset_class("Club deal") == "Club deals"
    assert normalize_asset_class("mercados publicos variable") == "Mercados Públicos - Variable"
    assert normalize_asset_class("Efectivo") == "Cash y Otros"


def test_normalize_asset_class_case_insensitive():
    from scraper.taxonomies.normalizer import normalize_asset_class
    assert normalize_asset_class("MERCADOS PUBLICOS FIJO") == "Mercados Públicos - Fijo"


def test_normalize_asset_class_fuzzy_match_above_threshold():
    from scraper.taxonomies.normalizer import normalize_asset_class
    # 'Mercados Publicos Variables' (typo extra 's') should match
    assert normalize_asset_class("Mercados Publicos Variables") == "Mercados Públicos - Variable"


def test_normalize_asset_class_unknown_returns_none():
    from scraper.taxonomies.normalizer import normalize_asset_class
    assert normalize_asset_class("Crypto Kingdom Nonsense") is None


def test_normalize_region_variants():
    from scraper.taxonomies.normalizer import normalize_region
    assert normalize_region("Peru") == "Perú"
    assert normalize_region("USA") == "EEUU"
    assert normalize_region("Latam ex-Peru") == "Latam ex-Perú"


def test_normalize_percentage_dict_asset_class():
    from scraper.taxonomies.normalizer import normalize_percentage_dict_asset_class
    raw = {"Club deal": 50.0, "Efectivo": 30.0, "Unknown Stuff": 20.0}
    result = normalize_percentage_dict_asset_class(raw)
    # Club deal → Club deals, Efectivo → Cash y Otros, Unknown → dropped
    assert result == {"Club deals": 50.0, "Cash y Otros": 30.0}


def test_normalize_percentage_dict_merges_duplicate_keys():
    from scraper.taxonomies.normalizer import normalize_percentage_dict_asset_class
    raw = {"Efectivo": 15.0, "Otros": 5.0, "cash y otros": 10.0}
    result = normalize_percentage_dict_asset_class(raw)
    assert result == {"Cash y Otros": 30.0}
