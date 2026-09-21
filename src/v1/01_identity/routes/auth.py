from fastapi import APIRouter
from schemas.token import Token
from schemas.user import LoginRequest, UserCreate, UserResponse

router = APIRouter()


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(payload: UserCreate) -> UserResponse:
    # TODO: call user_service.create_user(payload)
    raise NotImplementedError


@router.post("/login", response_model=Token)
async def login(payload: LoginRequest) -> Token:
    # TODO: call auth_service.authenticate_user then auth_service.issue_token
    raise NotImplementedError
