from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass
class User:
    email: str
    hashed_password: str
    is_active: bool = True
    id: UUID = field(default_factory=uuid4)
