import uuid
from typing import Optional

from sqlalchemy import BINARY, Dialect
from sqlalchemy.types import TypeDecorator


class UUIDType(TypeDecorator):
    """
    Platform-independent UUID type.
    Stores as BINARY(16) for MySQL/MariaDB and transparently converts to/from Python uuid.UUID.
    """

    impl = BINARY(16)
    cache_ok = True

    def process_bind_param(self, value: Optional[object], dialect: Dialect) -> Optional[bytes]:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value.bytes
        if isinstance(value, str):
            return uuid.UUID(value).bytes
        if isinstance(value, bytes):
            if len(value) == 16:
                return value
            raise ValueError(f"Expected 16-byte binary for UUID, got {len(value)}")
        raise ValueError(f"Cannot bind value of type {type(value)} as UUID")

    def process_result_value(self, value: Optional[bytes], dialect: Dialect) -> Optional[uuid.UUID]:
        if value is None:
            return None
        return uuid.UUID(bytes=value)
