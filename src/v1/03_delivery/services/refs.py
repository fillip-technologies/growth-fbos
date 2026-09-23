"""Cross-service reference builders.

Delivery has no direct database access to the Identity or Revenue services,
so ``UserRef``/``UnitRef``/``VerticalRef``/``ClientRef`` *names* cannot be
resolved here -- only the id, which is a real foreign id already stored on
this service's own tables. The display name is a readable placeholder
instead of a resolved value. This mirrors the same simplification already
used in this codebase (``02_revenue/services/lead_service.py`` builds
``UserRef(id=lead.owner_user_id, name="Assigned Owner")``). A production
implementation would resolve these through a synchronous HTTP call to
identity-org (see the spec's "Service -> service (sync)" timeout row) or a
locally maintained read projection kept warm by consuming identity/org-unit
events.
"""

import uuid
from typing import Optional

from schemas.common import ClientRef, UnitRef, UserRef, VerticalRef


def user_ref(user_id: Optional[uuid.UUID], placeholder: str = "User") -> Optional[UserRef]:
    if user_id is None:
        return None
    return UserRef(id=user_id, name=placeholder)


def unit_ref(unit_id: Optional[uuid.UUID], placeholder: str = "Org Unit") -> Optional[UnitRef]:
    if unit_id is None:
        return None
    return UnitRef(id=unit_id, name=placeholder)


def vertical_ref(vertical_id: Optional[uuid.UUID], placeholder: str = "Vertical") -> Optional[VerticalRef]:
    if vertical_id is None:
        return None
    return VerticalRef(id=vertical_id, name=placeholder)


def client_ref(client_id: Optional[uuid.UUID], placeholder: str = "Client") -> Optional[ClientRef]:
    if client_id is None:
        return None
    return ClientRef(id=client_id, name=placeholder)
