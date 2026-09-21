from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLATFORM_", extra="ignore")
    database_url: str
    cookie_secure: bool = True
    session_hours: int = Field(default=12, ge=1, le=168)

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value):
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("PostgreSQL psycopg URL required")
        return value
