from fastapi import Header, HTTPException, status


async def get_bearer_token(authorization: str = Header(default="")) -> str:
    """Extract the bearer access token and forward it to downstream services."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )
    return authorization.removeprefix("Bearer ")


__all__ = ["get_bearer_token"]
