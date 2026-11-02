from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel


class IdentitySyncStatus(BaseModel):
    # not_linked: no login; not_synced: never sent; pending: change waiting; failed: Identity did not take it;
    # drift: delivered but Identity differs; in_sync
    status: Literal["not_linked", "not_synced", "pending", "failed", "drift", "in_sync"]
    last_synced_at: Optional[datetime] = None
    last_error: Optional[str] = None
    note: Optional[str] = None  # what People could not declare
    drift: List[dict[str, Any]] = []  # [{field, people, identity}]
    drift_checked_at: Optional[datetime] = None
    deactivated_at: Optional[datetime] = None
