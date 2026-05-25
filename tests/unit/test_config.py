import os
from unittest.mock import patch


def test_settings_loads_database_url_from_env():
    from scraper.config import Settings
    with patch.dict(os.environ, {"DATABASE_URL": "sqlite+aiosqlite:///test.db"}, clear=False):
        s = Settings()
        assert s.database_url == "sqlite+aiosqlite:///test.db"

def test_settings_defaults_skip_deep_research_false():
    from scraper.config import Settings
    s = Settings(_env_file=None)
    assert s.skip_deep_research is False

def test_settings_alert_cost_daily_default_20():
    from scraper.config import Settings
    s = Settings(_env_file=None)
    assert s.alert_cost_daily_usd == 20.0
