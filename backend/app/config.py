from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "RG Time API"
    database_url: str = "postgresql://postgres@127.0.0.1:5432/postgres"
    db_schema: str = "rgtime"
    timezone: str = "America/New_York"
    portal_admin_token: str = ""
    rgtime_to_rs_token: str = Field(default="", validation_alias="ROLLICLOCK_TO_RS_TOKEN")


@lru_cache
def get_settings() -> Settings:
    return Settings()
