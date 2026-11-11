from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # CORS, for browsers calling the gateway from another origin. Off: no CORS headers, so
    # only same-origin pages (the site behind the same domain, the Vite proxy) can call it.
    cors_enabled: bool = False
    # Comma-separated origins, or * for any. Credentials (cookies) are never allowed cross-origin.
    cors_origins: str = "*"

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
    people_service_url: str = "http://people:8000"
    finance_service_url: str = "http://finance:8000"
    # Inventory is the Fixly backend (Node), deployed on its own; it serves /api/inventory/v1.
    inventory_service_url: str = "http://localhost:3000"

    # Per-dependency timeout budget for aggregated screens (seconds).
    aggregation_timeout_seconds: float = 0.8

    # Who is calling: Identity's internal /authz/actor. The token must match Identity's
    # INTERNAL_SERVICE_TOKEN (Identity skips the check in development when it is unset).
    internal_service_token: str = ""
    identity_timeout_seconds: float = 5.0

    # The CEO Command Center reads one summary per service and company; each call gets this long.
    ceo_timeout_seconds: float = 5.0
    # Most summary calls in flight at once, across every company.
    ceo_max_parallel_calls: int = 20
    # The organization the inventory service (Fixly) serves (its FBOS_ORGANIZATION_ID). Empty: the
    # caller's own organization is asked, and any other answers ORGANIZATION_NOT_SERVED.
    inventory_organization_id: str = ""

    # Nightly snapshots of the Command Center's totals into Insight (CEO plan B4), which the
    # screen's trend and comparisons read. Turn on in one gateway only.
    ceo_snapshot_enabled: bool = False
    # Server-local hour of the nightly run; it snapshots the day before.
    ceo_snapshot_hour: int = Field(1, ge=0, le=23)
    # Money that happened (revenue, costs) is read again this many days back, so entries
    # recorded late still land on their own day. Positions (receivables, headcount) can't be.
    ceo_snapshot_refresh_days: int = Field(7, ge=1, le=62)
    # When identity can't list the companies, the night's run is tried again this much later.
    ceo_snapshot_retry_seconds: int = Field(900, ge=60)


settings = Settings()
