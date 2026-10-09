from typing import Optional
import uuid

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8002
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

    # Documents stores the files attached to quotations and contracts.
    documents_service_url: str = "http://localhost:8005"
    documents_timeout_seconds: float = 10.0

    # In-app notifications (lead assigned, quotation approved...) go to the communication
    # service's /internal/notifications. Empty turns them off.
    communication_service_url: str = ""
    notification_timeout_seconds: float = 3.0

    # Enquiries from the company website become leads of one organization, and their status
    # changes go back to the website. The key alone turns on sending status changes back.
    # Importing also needs an interval above 0 and must run in exactly one process (nothing
    # in the database stops two importers duplicating leads, and every environment shares
    # the database), so only the live server sets it, and it runs a single uvicorn worker.
    website_leads_url: str = "https://filliptechnologies.com/api/integrations/leads"
    website_leads_api_key: str = ""
    website_leads_organization_id: Optional[uuid.UUID] = None
    website_leads_owner_user_id: Optional[uuid.UUID] = None
    website_leads_import_interval_seconds: int = 0
    website_leads_timeout_seconds: float = 15.0

    # Tax packs (finance/packs) an organization's tax configuration starts from, applied the
    # first time it uses billing. Later pack versions are reviewed and applied by its admins.
    default_tax_packs: str = "core,in_gst,in_itd"

    @property
    def default_tax_pack_codes(self) -> list[str]:
        return [code.strip() for code in self.default_tax_packs.split(",") if code.strip()]

    @field_validator("website_leads_organization_id", "website_leads_owner_user_id", mode="before")
    @classmethod
    def _blank_id_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def website_leads_import_enabled(self) -> bool:
        return bool(
            self.website_leads_api_key
            and self.website_leads_organization_id
            and self.website_leads_owner_user_id
            and self.website_leads_import_interval_seconds > 0
        )


settings = Settings()
