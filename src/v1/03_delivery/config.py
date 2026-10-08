from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8003
    debug: bool = False

    database_url: str = ""
    db_ssl: bool = False
    # The database user is shared by every service (75 connections in all on the hosted
    # MariaDB), so pools stay small; kept connections make up for it.
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout: int = 30
    # The hosted MariaDB drops connections idle for 20 s. Each connection raises its own
    # idle timeout to this value so the pool can keep it for minutes instead of paying a
    # ~1 s reconnect to the remote server after every pause.
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

    # Every request is authenticated by asking identity who the caller is.
    identity_service_url: str = "http://localhost:8001"
    # Shared secret sent as X-FBOS-Internal-Token on identity's /internal/* calls.
    internal_service_token: str = ""
    identity_timeout_seconds: float = 5.0

    # Notifications about tasks go to the communication service's /internal/notifications,
    # sent by the background worker (services/outbox_worker.py) from the outbox.
    communication_service_url: str = ""
    notification_timeout_seconds: float = 5.0
    # Seconds between the worker's runs; 0 = off. Every environment shares the database, so
    # only the live server turns it on (docker-compose.aapanel.yml): one worker sends each event.
    worker_interval_seconds: int = 0

    @property
    def worker_enabled(self) -> bool:
        return self.worker_interval_seconds > 0 and bool(self.communication_service_url)


settings = Settings()
