def test_siteparser_protocol_shape():
    from scraper.search.level1_scrapers.base import SiteParser

    # Protocol must declare `domain`, `search_by_name`, `parse_ficha`
    assert hasattr(SiteParser, "domain")


def test_registry_is_empty_by_default():
    from scraper.search.level1_scrapers.registry import TARGETS

    # Phase 2b.1: 7 heuristic parsers removed, Claude web_search covers the
    # search layer. Framework preserved so parsers can be added when proven.
    assert TARGETS == []
