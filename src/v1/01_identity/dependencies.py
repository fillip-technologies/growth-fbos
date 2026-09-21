from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from schemas.token import TokenPayload

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> TokenPayload:
    # TODO: decode and validate JWT; raise InvalidTokenError on failure
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "NOT_IMPLEMENTED", "message": "Token validation not yet implemented", "status": 401},
    )
