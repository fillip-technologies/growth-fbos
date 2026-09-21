import uuid

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


class UUIDType(TypeDecorator):
    """Database-agnostic UUID stored as CHAR(36). Accepts uuid.UUID or strings."""

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value)
        return str(uuid.UUID(str(value)))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))
