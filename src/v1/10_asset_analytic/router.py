from fastapi import APIRouter

router = APIRouter(prefix="/v1")


@router.get("/ping", tags=["system"])
async def ping() -> dict:
    return {"message": "pong"}
