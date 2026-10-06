from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8006
    debug: bool = False

    database_url: str = ""
    db_ssl: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

    # Every request is authenticated by asking identity who the caller is.
    identity_service_url: str = "http://localhost:8001"
    # Shared secret: sent as X-FBOS-Internal-Token on identity's /internal/* calls, and
    # required from other services on this service's own /internal/* endpoints.
    internal_service_token: str = ""
    identity_timeout_seconds: float = 5.0

    # Mail (SMTP)
    mail_mailer: str = "smtp"
    mail_host: str = ""
    mail_port: int = 587
    mail_encryption: str = "tls"
    mail_username: str = ""
    mail_password: str = ""
    mail_from_address: str = ""
    mail_from_name: str = "FBOS"


settings = Settings()
