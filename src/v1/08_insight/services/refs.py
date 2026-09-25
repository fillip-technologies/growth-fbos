import uuid
from typing import Optional

from schemas.common import UserRef


def user_ref(user_id: Optional[uuid.UUID], placeholder: str = "User") -> Optional[UserRef]:
    if user_id is None:
        return None
    return UserRef(id=user_id, name=placeholder)
