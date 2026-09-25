"""Cross-service reference builders.

Control has no direct database access to the Identity service, so UserRef
names cannot be resolved here — only the id. The display name is a readable
placeholder. A production implementation would resolve via HTTP call to
identity or a local read projection updated by consuming identity events.
"""

import uuid
from typing import Optional

from schemas.common import UserRef


def user_ref(user_id: Optional[uuid.UUID], placeholder: str = "User") -> Optional[UserRef]:
    if user_id is None:
        return None
    return UserRef(id=user_id, name=placeholder)
