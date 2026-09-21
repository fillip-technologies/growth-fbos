from uuid import UUID
from fastapi import APIRouter, Depends
from schemas.token import TokenPayload
from schemas.user import UserResponse
from dependencies import get_current_user

router = APIRouter()


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    current_user: TokenPayload = Depends(get_current_user),
) -> UserResponse:
    # TODO: call user_service.get_user_by_id(user_id)
    raise NotImplementedError
