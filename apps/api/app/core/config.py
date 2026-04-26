from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Huoke API"
    app_env: str = "development"
    app_port: int = 8000
    allowed_origins: list[str] = ["http://localhost:4000"]
    database_url: str = "sqlite:///./huoke.db"
    redis_url: str = "redis://localhost:6379/0"
    joinf_username: Optional[str] = "hcct010"
    joinf_password: Optional[str] = "hcct86069640"
    joinf_login_user_id: Optional[int] = None
    linkedin_username: Optional[str] = None
    linkedin_password: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
