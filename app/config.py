from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    telegram_webhook_secret: str = Field(..., alias="TELEGRAM_WEBHOOK_SECRET")
    telegram_api_base: str = Field("https://api.telegram.org", alias="TELEGRAM_API_BASE")

    agent_api_url: str = Field(..., alias="AGENT_API_URL")
    agent_api_key: str = Field(..., alias="AGENT_API_KEY")
    agent_timeout_seconds: float = Field(30.0, alias="AGENT_TIMEOUT_SECONDS")

    outbound_api_key: str = Field(..., alias="OUTBOUND_API_KEY")

    public_base_url: str | None = Field(None, alias="PUBLIC_BASE_URL")

    log_level: str = Field("INFO", alias="LOG_LEVEL")


@lru_cache
def get_settings() -> Settings:
    return Settings() # type: ignore
