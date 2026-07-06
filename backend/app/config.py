from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./data/health.db"
    session_secret: str = "dev-insecure-change-me"
    max_upload_mb: int = 500
    cookie_secure: bool = False

@lru_cache
def get_settings() -> Settings:
    return Settings()
