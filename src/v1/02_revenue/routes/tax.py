"""
Tax configuration: dated entries, their change history, packs, and a calculation preview.

Reading the configuration starts it from the default packs the first time (a one-off,
idempotent setup), which is why these GETs commit.
"""

from datetime import date
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, Header, Query, Response, status

from dependencies import DatabaseSession, OrgId, UserId, require_permission
import permissions
from schemas.tax import (
    TaxCalculationRequest,
    TaxCalculationResponse,
    TaxConfigEntryCreate,
    TaxConfigEntryResponse,
    TaxConfigEntryUpdate,
    TaxConfigRevisionResponse,
    TaxPackApplicationCreate,
    TaxPackApplicationResponse,
    TaxPackDiff,
    TaxPackSummary,
)
from services.tax_config_service import TaxConfigService

router = APIRouter(prefix="/tax", tags=["tax"])

CAN_READ = Depends(require_permission(permissions.TAX_READ))
CAN_MANAGE = Depends(require_permission(permissions.TAX_MANAGE))


@router.get("/config-entries", response_model=List[TaxConfigEntryResponse], dependencies=[CAN_READ])
async def list_config_entries(
    session: DatabaseSession,
    org_id: OrgId,
    kind: Optional[str] = Query(None, description="regime, component, rate, category, rule, jurisdiction, withholding_section, deadline, series_template"),
    code: Optional[str] = Query(None),
    as_of: Optional[date] = Query(None, description="Only entries in effect on this date"),
) -> List[TaxConfigEntryResponse]:
    """The organization's tax configuration, optionally as it stood on one date."""
    entries = await TaxConfigService.list_entries(session, org_id, kind, code, as_of)
    await session.commit()
    return entries


@router.post(
    "/config-entries", response_model=TaxConfigEntryResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE]
)
async def create_config_entry(
    payload: TaxConfigEntryCreate, session: DatabaseSession, org_id: OrgId, user_id: UserId, response: Response
) -> TaxConfigEntryResponse:
    """Add a dated entry: a new rate from a notification date, a rule, a category, a number format..."""
    entry = await TaxConfigService.create_entry(session, org_id, user_id, payload)
    await session.commit()
    response.headers["ETag"] = f'"{entry.version}"'
    response.headers["Location"] = f"/api/revenue/v1/tax/config-entries/{entry.id}"
    return entry


@router.get("/config-entries/{entry_id}", response_model=TaxConfigEntryResponse, dependencies=[CAN_READ])
async def get_config_entry(entry_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, response: Response) -> TaxConfigEntryResponse:
    entry = TaxConfigEntryResponse.model_validate(await TaxConfigService.get_entry(session, org_id, entry_id))
    response.headers["ETag"] = f'"{entry.version}"'
    return entry


@router.patch("/config-entries/{entry_id}", response_model=TaxConfigEntryResponse, dependencies=[CAN_MANAGE])
async def update_config_entry(
    entry_id: uuid.UUID,
    payload: TaxConfigEntryUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> TaxConfigEntryResponse:
    """Change an entry that hasn't started, or close one in effect (effective_to) to supersede it."""
    entry = await TaxConfigService.update_entry(session, org_id, user_id, entry_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{entry.version}"'
    return entry


@router.delete("/config-entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[CAN_MANAGE])
async def delete_config_entry(
    entry_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> Response:
    """Remove an entry that has not started yet."""
    await TaxConfigService.delete_entry(session, org_id, user_id, entry_id, if_match)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/config-revisions", response_model=List[TaxConfigRevisionResponse], dependencies=[CAN_READ])
async def list_config_revisions(session: DatabaseSession, org_id: OrgId) -> List[TaxConfigRevisionResponse]:
    """Every change to the tax configuration, newest first."""
    return await TaxConfigService.list_revisions(session, org_id)


@router.get("/packs", response_model=List[TaxPackSummary], dependencies=[CAN_READ])
async def list_packs(session: DatabaseSession, org_id: OrgId) -> List[TaxPackSummary]:
    """Packs shipped with the service, their latest version and the version applied here."""
    packs = await TaxConfigService.list_packs(session, org_id)
    await session.commit()
    return packs


@router.get("/packs/{code}/versions/{version}/diff", response_model=TaxPackDiff, dependencies=[CAN_READ])
async def diff_pack(code: str, version: int, session: DatabaseSession, org_id: OrgId) -> TaxPackDiff:
    """What applying this pack version would add, update, retire, or leave in conflict."""
    diff = await TaxConfigService.diff_pack(session, org_id, code, version)
    await session.commit()
    return diff


@router.get("/pack-applications", response_model=List[TaxPackApplicationResponse], dependencies=[CAN_READ])
async def list_pack_applications(session: DatabaseSession, org_id: OrgId) -> List[TaxPackApplicationResponse]:
    return await TaxConfigService.list_pack_applications(session, org_id)


@router.post(
    "/pack-applications", response_model=TaxPackApplicationResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_MANAGE],
)
async def apply_pack(
    payload: TaxPackApplicationCreate, session: DatabaseSession, org_id: OrgId, user_id: UserId
) -> TaxPackApplicationResponse:
    """Apply a reviewed pack version. Entries edited here are kept unless listed in `overwrite`."""
    application = await TaxConfigService.apply_pack(session, org_id, user_id, payload)
    await session.commit()
    return application


@router.post("/calculations", response_model=TaxCalculationResponse, dependencies=[CAN_READ])
async def calculate(payload: TaxCalculationRequest, session: DatabaseSession, org_id: OrgId) -> TaxCalculationResponse:
    """Work out taxes for lines without saving anything: the editors' live preview."""
    calculation = await TaxConfigService.calculate(session, org_id, payload)
    await session.commit()
    return calculation
