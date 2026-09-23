from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"

    # Downstream service base URLs, used to route /api/<service>/v1/* and to
    # fan out aggregated-screen requests (e.g. the home summary).
    identity_service_url: str = "http://identity:8000"
    revenue_service_url: str = "http://revenue:8000"
    delivery_service_url: str = "http://delivery:8000"
    control_service_url: str = "http://control:8000"
    documents_service_url: str = "http://documents:8000"
    communication_service_url: str = "http://communication:8000"
    management_service_url: str = "http://management:8000"
    insight_service_url: str = "http://insight:8000"
    assets_service_url: str = "http://assets:8000"

    # Per-dependency timeout budget for aggregated screens (seconds).
    aggregation_timeout_seconds: float = 0.8


settings = Settings()
