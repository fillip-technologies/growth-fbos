from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8010
    debug: bool = False

    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"

    database_url: str = "mysql+aiomysql://root:fbos_root_password@db:3306/fbos_people"
    db_ssl: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout: int = 30
    db_session_wait_timeout: int = 3600
    db_pool_recycle: int = 3300  # must stay below db_session_wait_timeout
    db_pool_pre_ping: bool = True

    @model_validator(mode="after")
    def _recycle_before_server_drops_connection(self) -> "Settings":
        if self.db_pool_recycle >= self.db_session_wait_timeout:
            raise ValueError(
                "DB_POOL_RECYCLE must be lower than DB_SESSION_WAIT_TIMEOUT: "
                "otherwise the server closes pooled connections before the pool retires them"
            )
        return self

    # Fernet key (urlsafe base64, 32 bytes) that encrypts ID and bank account numbers. While it is
    # empty or invalid the service still runs; only saving or revealing those numbers answers 503.
    field_encryption_key: str = ""

    identity_service_url: str = "http://identity:8000"
    internal_service_token: str = ""
    identity_timeout_seconds: float = 5.0

    assets_service_url: str = "http://localhost:8009"
    delivery_service_url: str = "http://localhost:8003"
    control_service_url: str = "http://localhost:8004"
    documents_service_url: str = "http://localhost:8005"
    communication_service_url: str = "http://localhost:8006"
    management_service_url: str = "http://localhost:8007"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
