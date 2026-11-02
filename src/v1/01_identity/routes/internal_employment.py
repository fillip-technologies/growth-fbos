import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from dependencies import verify_internal_caller
from schemas.people_sync import EmploymentDeclaration, EmploymentStatesResponse, EmploymentSyncResponse
from services import people_sync

router = APIRouter()


@router.put(
    "/people/users/{user_id}/employment",
    response_model=EmploymentSyncResponse,
    status_code=status.HTTP_200_OK,
    summary="Declare what People holds about an employee's login (internal)",
)
async def declare_employment(
    user_id: uuid.UUID,
    declaration: EmploymentDeclaration,
    organization_id: uuid.UUID = Query(..., description="The organization the user belongs to"),
    x_fbos_internal_token: Optional[str] = Header(None, alias="X-FBOS-Internal-Token"),
    db: AsyncSession = Depends(get_db_session),
) -> EmploymentSyncResponse:
    """
    People is the source for an employee's department, manager, employee code, name, phone, the
    access their job brings and whether they have left. It declares them here; Identity applies what is
    named and answers what it did and what it could not. Repeating a declaration changes nothing.
    """
    verify_internal_caller(x_fbos_internal_token)
    return await people_sync.apply_declaration(db, organization_id, user_id, declaration)


@router.get(
    "/people/users/employment",
    response_model=EmploymentStatesResponse,
    status_code=status.HTTP_200_OK,
    summary="What Identity holds for employees, in the shape People declares it (internal)",
)
async def read_employment(
    organization_id: uuid.UUID = Query(..., description="The organization the users belong to"),
    user_id: list[uuid.UUID] = Query(..., max_length=people_sync.STATES_LIMIT, description="The users to answer for"),
    x_fbos_internal_token: Optional[str] = Header(None, alias="X-FBOS-Internal-Token"),
    db: AsyncSession = Depends(get_db_session),
) -> EmploymentStatesResponse:
    """People's drift check compares this with what it would declare. Reads only."""
    verify_internal_caller(x_fbos_internal_token)
    return EmploymentStatesResponse(data=await people_sync.employment_states(db, organization_id, user_id))
