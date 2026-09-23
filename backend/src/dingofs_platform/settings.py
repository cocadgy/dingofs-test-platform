from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLATFORM_", extra="ignore")
    database_url: str
    cookie_secure: bool = True
    credential_encryption_key: str = Field(default="", repr=False)
    ssh_known_hosts: str = "/app/deploy/ssh/known_hosts"
    collection_timeout_seconds: float = Field(default=30, ge=1, le=30)
    cluster_discovery_timeout: int = Field(default=60, ge=1, le=600)
    cluster_status_timeout: int = Field(default=120, ge=1, le=1800)
    cluster_max_bytes: int = Field(default=2097152, ge=1024, le=2097152)
    cluster_machine_concurrency: int = Field(default=2, ge=1, le=8)
    cluster_auth_seconds: int = Field(default=300, ge=30, le=600)
    cluster_discovery_seconds: int = Field(default=900, ge=60, le=3600)
    session_hours: int = Field(default=12, ge=1, le=168)

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value):
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("PostgreSQL psycopg URL required")
        return value
