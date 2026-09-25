from typing import Any, Optional

from pydantic import BaseModel


class QuietHours(BaseModel):
    start: str  # HH:MM
    end: str    # HH:MM
    timezone: str


class NotificationPreferenceItem(BaseModel):
    event_category: str
    channel_type: str
    enabled: bool = True
    digest: str = "none"  # none | instant | hourly | daily
    quiet_hours: Optional[QuietHours] = None


class PreferencesReplace(BaseModel):
    preferences: list[NotificationPreferenceItem]


class DeviceTokenCreate(BaseModel):
    platform: str  # android | ios | web
    token: str
