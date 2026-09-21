from uuid import UUID
from models.user import User
from schemas.user import UserCreate


def create_user(payload: UserCreate) -> User:
    # TODO: check for duplicate email, hash password, persist to database
    raise NotImplementedError


def get_user_by_email(email: str) -> User:
    # TODO: query database; raise UserNotFoundError if missing
    raise NotImplementedError


def get_user_by_id(user_id: UUID) -> User:
    # TODO: query database; raise UserNotFoundError if missing
    raise NotImplementedError
