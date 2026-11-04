from datetime import date, datetime, timedelta, timezone
from typing import Optional

from models.client import Client

EXPIRING_SOON_DAYS = 30
USABLE_STATES = ("active", "expiring", "unlimited")


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def add_one_year(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 29 Feb -> 28 Feb
        return d.replace(year=d.year + 1, day=28)


def subscription_state(client: Client, today: Optional[date] = None) -> str:
    # No end date: the client has no service window at all (the operator company running FBOS).
    if client.subscription_end is None:
        return "unlimited"
    today = today or today_utc()
    if today < client.subscription_start:
        return "upcoming"
    if today > client.subscription_end:
        return "expired"
    if client.subscription_end - today <= timedelta(days=EXPIRING_SOON_DAYS):
        return "expiring"
    return "active"


def is_client_usable(client: Optional[Client]) -> bool:
    """A client may use the platform only while active and inside its service window (if it has one)."""
    if client is None:
        return False
    return client.status == "active" and subscription_state(client) in USABLE_STATES
