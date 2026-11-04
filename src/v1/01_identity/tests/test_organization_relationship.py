"""An organization's relationship to its client: own (default), associate or investment."""
import pytest
from pydantic import ValidationError

from schemas.client import ClientCreateRequest
from schemas.organization import OrganizationCreateRequest, OrganizationUpdateRequest
from services.client_service import client_service
from services.organization_service import organization_service


def _org(code: str, **extra) -> OrganizationCreateRequest:
    return OrganizationCreateRequest(
        name=code, code=code, email=f"{code.lower()}@example.com", base_currency="INR", timezone="Asia/Kolkata", **extra
    )


def test_unknown_relationship_is_refused():
    with pytest.raises(ValidationError):
        _org("X", relationship="partner")


@pytest.mark.asyncio
async def test_new_organizations_are_own_unless_said_otherwise_and_can_change(db_session):
    client = await client_service.create_client(
        session=db_session,
        data=ClientCreateRequest(name="Fillip", code="FIL", contact_email="ops@fil.example.com", max_organizations=None),
    )
    own = await organization_service.create_organization(session=db_session, client_id=client.id, data=_org("FIL-OWN"))
    associate = await organization_service.create_organization(
        session=db_session, client_id=client.id, data=_org("FIL-ASSOC", relationship="associate")
    )
    assert (own.relationship, associate.relationship) == ("own", "associate")

    changed = await organization_service.update_organization(
        session=db_session, organization_id=associate.id, client_id=client.id,
        data=OrganizationUpdateRequest(relationship="investment"),
    )
    assert changed.relationship == "investment"
    renamed = await organization_service.update_organization(
        session=db_session, organization_id=associate.id, client_id=client.id, data=OrganizationUpdateRequest(name="Renamed"),
    )
    assert renamed.relationship == "investment"
