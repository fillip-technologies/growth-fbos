import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import permissions
import services.identity_sync as identity_sync
from dependencies import CurrentActor, DatabaseSession, require_permission
from exceptions import ConflictError, MappingNotFoundError, ValidationFailedError
from models.identity_sync import AccessRoleMapping
from models.job_architecture import JobProfile
from schemas.identity_sync import (
    AccessRoleMappingCreate,
    AccessRoleMappingList,
    AccessRoleMappingResponse,
    IdentitySyncStatus,
)
from services.worker_documents import ensure_worker

router = APIRouter(tags=["identity-sync"])

CAN_READ = Depends(require_permission(permissions.EMPLOYEE_READ))
CAN_MANAGE = Depends(require_permission(permissions.EMPLOYEE_MANAGE))
CAN_SET_UP = Depends(require_permission(permissions.ROLE_CHANGE_MANAGE))
# A mapping hands out access, so creating one also needs the right to apply roles in Identity.
CAN_APPLY_ROLES = Depends(require_permission(permissions.IDENTITY_ROLE_ASSIGNMENT_CREATE))


@router.get("/workers/{worker_id}/identity-sync", response_model=IdentitySyncStatus, dependencies=[CAN_READ])
async def get_identity_sync(session: DatabaseSession, actor: CurrentActor, worker_id: uuid.UUID):
    """Whether this person's login matches their job: in sync, waiting, failed, or what differs."""
    worker = await ensure_worker(session, actor.organization_id, worker_id)
    return await identity_sync.sync_status(session, worker)


@router.post(
    "/workers/{worker_id}/identity-sync-requests",
    response_model=IdentitySyncStatus,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[CAN_MANAGE],
)
async def request_identity_sync(session: DatabaseSession, actor: CurrentActor, worker_id: uuid.UUID):
    """Send this person's login what People holds for it again (after fixing a role in Identity, say)."""
    worker = await ensure_worker(session, actor.organization_id, worker_id)
    await identity_sync.queue_sync(session, worker)
    await session.commit()
    return await identity_sync.sync_status(session, worker)


@router.get("/access-role-mappings", response_model=AccessRoleMappingList, dependencies=[CAN_SET_UP])
async def list_access_role_mappings(session: DatabaseSession, actor: CurrentActor):
    """Which jobs bring which access roles."""
    rows = (
        await session.execute(
            select(AccessRoleMapping)
            .where(AccessRoleMapping.organization_id == actor.organization_id)
            .order_by(AccessRoleMapping.match_type, AccessRoleMapping.match_value, AccessRoleMapping.role_code)
        )
    ).scalars().all()
    return {"data": rows}


@router.post(
    "/access-role-mappings",
    response_model=AccessRoleMappingResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_SET_UP, CAN_APPLY_ROLES],
)
async def create_access_role_mapping(session: DatabaseSession, actor: CurrentActor, payload: AccessRoleMappingCreate):
    """
    Give a job an access role: everyone who holds a matching post gets the role (for their
    post's department, or company-wide). Roles are named by their Identity code; a code Identity does not
    know shows up on each person's sync status.
    """
    value = payload.match_value.strip()
    if payload.match_type == "job_profile":
        try:
            profile_id = uuid.UUID(value)
        except ValueError:
            raise ValidationFailedError("match_value", "A job profile is named by its id") from None
        profile = await session.get(JobProfile, profile_id)
        if profile is None or profile.organization_id != actor.organization_id:
            raise ValidationFailedError("match_value", "Job profile not found in this organization")
        value = str(profile_id)
    else:
        value = value.lower()

    mapping = AccessRoleMapping(
        organization_id=actor.organization_id, match_type=payload.match_type, match_value=value,
        role_code=payload.role_code.strip(), scope=payload.scope, created_by=actor.user_id,
    )
    session.add(mapping)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise ConflictError("This job already brings that role", code="MAPPING_EXISTS") from None
    await identity_sync.queue_sync_for_organization(session, actor.organization_id)
    await session.commit()
    return mapping


@router.delete("/access-role-mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[CAN_SET_UP])
async def delete_access_role_mapping(session: DatabaseSession, actor: CurrentActor, mapping_id: uuid.UUID) -> Response:
    """Stop a job bringing a role: people who got it from this job lose it on the next delivery."""
    mapping = await session.get(AccessRoleMapping, mapping_id)
    if mapping is None or mapping.organization_id != actor.organization_id:
        raise MappingNotFoundError()
    await session.delete(mapping)
    await identity_sync.queue_sync_for_organization(session, actor.organization_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
