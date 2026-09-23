from fastapi import APIRouter, Depends

from dependencies import get_bearer_token
from schemas.home import HomeSummary
from services.aggregation_service import aggregation_service

router = APIRouter()


@router.get("/home", response_model=HomeSummary, tags=["aggregated-screens"])
async def get_home_summary(token: str = Depends(get_bearer_token)) -> HomeSummary:
    return await aggregation_service.get_home_summary(token)
