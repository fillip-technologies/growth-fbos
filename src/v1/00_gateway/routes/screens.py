from datetime import date
from typing import Annotated, Optional

import httpx
from fastapi import APIRouter, Depends, Query

from dependencies import Authorization, get_bearer_token, get_http_client, get_identity_client, require_permission
import permissions
from schemas.ceo import CeoScreen
from schemas.home import HomeSummary
from services.aggregation_service import aggregation_service
from services.ceo_service import load_ceo_screen
from services.identity_client import Actor, IdentityClient

router = APIRouter()


@router.get("/home", response_model=HomeSummary, tags=["aggregated-screens"])
async def get_home_summary(token: str = Depends(get_bearer_token)) -> HomeSummary:
    return await aggregation_service.get_home_summary(token)


@router.get("/screens/ceo", response_model=CeoScreen, tags=["aggregated-screens"])
async def get_ceo_screen(
    authorization: Authorization,
    actor: Annotated[Actor, Depends(require_permission(permissions.CEO_DASHBOARD_READ))],
    identity: Annotated[IdentityClient, Depends(get_identity_client)],
    http: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    from_date: Optional[date] = Query(None, alias="from", description="First day; defaults to the 1st of this month"),
    to_date: Optional[date] = Query(None, alias="to", description="Last day; defaults to today"),
    compare: str = Query("previous_period", pattern="^previous_period$", description="What to compare with"),
) -> CeoScreen:
    """The CEO Command Center: every company's revenue, delivery, people, health, costs and alerts,
    added up, each card with the period before. Sensitive figures need the financials permission."""
    return await load_ceo_screen(actor, authorization, identity, http, from_date, to_date)
