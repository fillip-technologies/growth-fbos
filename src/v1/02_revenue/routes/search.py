"""`GET /search?q=`: records matching what someone typed, across revenue's kinds of record.

Open to anyone who may read at least one of them; each kind is searched only with its own read
permission (services/search_service.py), and the answer names the kinds left out.
"""
from fastapi import APIRouter, Depends, Query

from dependencies import CurrentActor, DatabaseSession, OrgId
from exceptions import PermissionDeniedError
from schemas.search import SearchResponse
from services.identity_client import Actor
from services.search_service import SEARCH_PERMISSIONS, SearchService

router = APIRouter(tags=["search"])


async def require_any_search_read(actor: CurrentActor) -> Actor:
    """Route guard: the actor may read at least one kind of record the search covers."""
    if not any(actor.has(code) for code in SEARCH_PERMISSIONS.values()):
        raise PermissionDeniedError(SEARCH_PERMISSIONS["customer"])
    return actor


@router.get("/search", response_model=SearchResponse, dependencies=[Depends(require_any_search_read)])
async def search(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    q: str = Query(..., max_length=100, description="Words to look for: a name, number, email or GSTIN"),
    per_type: int = Query(5, ge=1, le=20, description="Hits per kind of record"),
) -> SearchResponse:
    """Customers, leads, opportunities, quotations, contracts, invoices and payments matching `q`."""
    return await SearchService.search(session, org_id, actor, q, per_type)
