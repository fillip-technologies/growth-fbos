from models.user import User
from schemas.token import Token


def authenticate_user(email: str, password: str) -> User:
    # TODO: fetch user by email, verify password hash; raise InvalidCredentialsError on failure
    raise NotImplementedError


def issue_token(user: User) -> Token:
    # TODO: encode JWT with user.id as subject; return Token
    raise NotImplementedError
