import os
from pathlib import Path
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
    port: int = 8000
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

    # Rate Limiting
    auth_rate_limit_per_minute: int = 60

    # Database
    database_url: str = ""
    db_ssl: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800


settings = Settings()
