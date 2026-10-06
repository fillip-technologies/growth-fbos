"""References to records other services own (see the note in ``schemas/common.py``).

Delivery holds only their ids; names are left for consoles to fill in from their own
lookups instead of being made up here.
"""

import uuid
from typing import Optional

from schemas.common import ClientRef, UnitRef, UserRef, VerticalRef


def user_ref(user_id: Optional[uuid.UUID]) -> Optional[UserRef]:
    return UserRef(id=user_id) if user_id is not None else None


def unit_ref(unit_id: Optional[uuid.UUID]) -> Optional[UnitRef]:
    return UnitRef(id=unit_id) if unit_id is not None else None


def vertical_ref(vertical_id: Optional[uuid.UUID]) -> Optional[VerticalRef]:
    return VerticalRef(id=vertical_id) if vertical_id is not None else None


def client_ref(client_id: Optional[uuid.UUID]) -> Optional[ClientRef]:
    return ClientRef(id=client_id) if client_id is not None else None
