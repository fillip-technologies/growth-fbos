import os
from pathlib import Path
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_CURRENT_DIR = Path(__file__).resolve().parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_CURRENT_DIR / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8001
    debug: bool = False

    # JWT Authentication
    jwt_secret: str = "changeme"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30
    mfa_token_expire_minutes: int = 5  # short-lived 5-minute MFA token

    # Password Hashing (Argon2id)
    argon2_time_cost: int = 2
    argon2_memory_cost: int = 19456  # 19 MiB
    argon2_parallelism: int = 1

    # Security & Lockout Policy
    lockout_threshold: int = 5  # 5 failed attempts
    lockout_window_minutes: int = 15  # within 15 minutes
    lockout_duration_minutes: int = 15  # locks account for 15 minutes

    # Shared secret other services send as X-FBOS-Internal-Token on /internal/* calls.
    # Empty is accepted only when app_env is "development".
    internal_service_token: str = ""

    # Rate Limiting
    auth_rate_limit_per_minute: int = 60

    # Database
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

    # Auth cache (services/auth_cache.py). Empty turns it off: every check reads the database.
    redis_url: str = ""

    # Mail (SMTP)
    mail_enabled: bool = False  # explicit opt-in so tests/dev never send real mail
    mail_mailer: str = "smtp"
    mail_host: str = ""
    mail_port: int = 587
    mail_encryption: str = "tls"
    mail_username: str = ""
    mail_password: str = ""
    mail_from_address: str = ""
    mail_from_name: str = "FBOS"
    # Base URL of the client-admin frontend. Every link in outgoing emails (activate
    # account, reset password, sign in) is built from it: change it here for staging/prod.
    client_admin_base_url: str = "http://localhost:5174"


settings = Settings()
