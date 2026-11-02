from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8007
    debug: bool = False

    database_url: str = "mysql+aiomysql://root:password@localhost:3306/management_db"
    db_ssl: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

    # Who is calling is decided by identity (services/identity_client.py), never by caller headers.
    identity_service_url: str = "http://identity:8000"
    internal_service_token: str = ""
    identity_timeout_seconds: float = 5.0

    # Targets and budgets are approved through control's approval requests.
    control_service_url: str = "http://control:8000"
    control_timeout_seconds: float = 5.0

    # Read-only aggregates pulled for the capacity ledger and utilization. Until those services serve the
    # endpoints (services/source_clients.py), absences and recorded effort are simply not counted.
    people_service_url: str = "http://people:8000"
    delivery_service_url: str = "http://delivery:8000"
    revenue_service_url: str = "http://revenue:8000"
    source_timeout_seconds: float = 5.0

    # Rebuilds the capacity ledger (resource x day) in the background. Run it on ONE server only.
    capacity_worker_enabled: bool = False
    capacity_worker_interval_seconds: int = 3600
    capacity_window_past_days: int = 14
    capacity_window_future_days: int = 120

    # Mirrors Revenue's issued documents (net of tax) into each budget's "revenue" line, once a day,
    # over every open fiscal year (documents can be backdated). ONE server only.
    revenue_pull_enabled: bool = False
    revenue_pull_interval_seconds: int = 86400


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
