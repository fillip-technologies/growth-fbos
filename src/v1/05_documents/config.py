from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8005
    debug: bool = False

    # Every request is authenticated by asking identity who the caller is.
    identity_service_url: str = "http://localhost:8001"
    # Shared secret sent as X-FBOS-Internal-Token on other services' /internal/* calls, and
    # required on this service's own /internal/* endpoints.
    internal_service_token: str = ""
    identity_timeout_seconds: float = 5.0

    # Services that own the records documents attach to, by subject-type prefix: a subject
    # `revenue.contract` is checked at `<revenue base>/internal/subject-access/...`.
    # Set as JSON, e.g. SUBJECT_SERVICES='{"revenue": "http://revenue:8000/api/revenue/v1"}'.
    subject_services: dict[str, str] = {
        "revenue": "http://localhost:8002/api/revenue/v1",
        "delivery": "http://localhost:8003/api/delivery/v1",
        "inventory": "http://localhost:3000/api/inventory/v1",
        "people": "http://localhost:8010/api/people/v1",
        "finance": "http://localhost:8011/api/finance/v1",
    }
    subject_check_timeout_seconds: float = 5.0
    # Read checks are cached this long per user and subject; attach checks never are.
    subject_read_cache_seconds: float = 30.0

    # File storage (ImageKit.io). Leave the private key empty for local stub mode.
    imagekit_public_key: str = ""
    imagekit_private_key: str = ""
    imagekit_url_endpoint: str = ""
    imagekit_folder: str = "fbos-documents"
    public_share_base_url: str = "https://share.fbos.example.com/s"
    max_upload_size_bytes: int = 104857600  # 100 MB default max
    # No virus scanner is wired in yet. While this is off, uploads are recorded as
    # `not_scanned` and can be downloaded; when on, they stay `pending` until a scanner
    # marks them clean.
    virus_scan_enabled: bool = False

    # Database
    database_url: str = "mysql+aiomysql://root:fbos_root_password@db:3306/fbos_documents"
    db_ssl: bool = False
    # The database user is shared by every service (75 connections in all on the hosted
    # MariaDB), so pools stay small; kept connections make up for it.
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout: int = 30
    # The hosted MariaDB drops connections idle for 20 s. Each connection raises its own
    # idle timeout to this value so the pool can keep it for minutes instead of reconnecting
    # (and, when that reconnect fails, answering 500) after every pause.
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


settings = Settings()
