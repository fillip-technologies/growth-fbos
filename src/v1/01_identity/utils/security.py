def hash_password(password: str) -> str:
    # TODO: implement with passlib[bcrypt] — add to requirements.txt when wiring auth
    raise NotImplementedError


def verify_password(plain_password: str, hashed_password: str) -> bool:
    # TODO: implement with passlib[bcrypt]
    raise NotImplementedError


def create_access_token(subject: str) -> str:
    # TODO: implement with python-jose[cryptography] — add to requirements.txt when wiring auth
    raise NotImplementedError
