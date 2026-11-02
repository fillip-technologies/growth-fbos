import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from dependencies import verify_internal_caller
from schemas.people_sync import (
    AdoptRolesRequest,
    AdoptRolesResponse,
    CanGrantRequest,
    CanGrantResponse,
    EmploymentDeclaration,
    EmploymentStatesResponse,
    EmploymentSyncResponse,
    RoleOptionsResponse,
)
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


@router.get(
    "/people/roles",
    response_model=RoleOptionsResponse,
    status_code=status.HTTP_200_OK,
    summary="The roles People may offer on a post (internal)",
)
async def list_role_options(
    organization_id: uuid.UUID = Query(..., description="The organization whose roles to list"),
    x_fbos_internal_token: Optional[str] = Header(None, alias="X-FBOS-Internal-Token"),
    db: AsyncSession = Depends(get_db_session),
) -> RoleOptionsResponse:
    verify_internal_caller(x_fbos_internal_token)
    return RoleOptionsResponse(data=await people_sync.list_role_options(db, organization_id))


@router.post(
    "/people/users/{user_id}/role-adoptions",
    response_model=AdoptRolesResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Let People manage roles the user holds by hand (internal)",
)
async def adopt_roles(
    user_id: uuid.UUID,
    adoption: AdoptRolesRequest,
    organization_id: uuid.UUID = Query(..., description="The organization the user belongs to"),
    x_fbos_internal_token: Optional[str] = Header(None, alias="X-FBOS-Internal-Token"),
    db: AsyncSession = Depends(get_db_session),
) -> AdoptRolesResponse:
    """Grants and removes nothing: the assignments stay, and from now on a post in People gives them."""
    verify_internal_caller(x_fbos_internal_token)
    return await people_sync.adopt_roles(db, organization_id, user_id, adoption)


@router.post(
    "/people/role-grant-checks",
    response_model=CanGrantResponse,
    status_code=status.HTTP_200_OK,
    summary="Which roles a requester could not grant themselves (internal)",
)
async def check_role_grants(
    check: CanGrantRequest,
    organization_id: uuid.UUID = Query(..., description="The organization the roles belong to"),
    x_fbos_internal_token: Optional[str] = Header(None, alias="X-FBOS-Internal-Token"),
    db: AsyncSession = Depends(get_db_session),
) -> CanGrantResponse:
    """A read: nothing is granted. People adds an Identity admin to the approval when the requester could not grant."""
    verify_internal_caller(x_fbos_internal_token)
    return await people_sync.can_grant(db, organization_id, check)
