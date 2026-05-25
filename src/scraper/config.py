from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM APIs
    anthropic_api_key: str = Field(default="", description="Claude API key")
    openai_api_key: str = Field(default="", description="OpenAI API key")
    tavily_api_key: str = Field(default="", description="Tavily API key")

    # DB
    database_url: str = Field(default="sqlite+aiosqlite:///data/local.db")

    # Feature flags
    skip_deep_research: bool = Field(default=False)
    skip_intensive_search: bool = Field(default=True)  # N3 kill switch, default off

    # Fetcher backend
    fetcher_backend: str = Field(default="scrapling", description="legacy | scrapling")

    # Alerts
    alert_cost_daily_usd: float = Field(default=20.0)

    # Logging
    log_level: str = Field(default="INFO")

    # Auth
    auth_users_file: Path = Field(default=Path("config/users.yaml"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
