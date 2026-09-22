import json
import re
import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    ClientNotFoundError,
    DuplicateClientError,
    GSTINInvalidError,
    VersionConflictError,
)
from models.client import Client, ClientContact
from schemas.client import ClientCreate, ClientResponse, ClientUpdate, ContactCreate, ContactResponse
from schemas.common import Address, PageMeta, PageResponse, decode_cursor, encode_cursor

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


def validate_gstin(gstin: Optional[str], state_code: str) -> None:
    """Validate Indian GSTIN format and state code prefix match."""
    if not gstin:
        return
    cleaned = gstin.strip().upper()
    if not GSTIN_REGEX.match(cleaned):
        raise GSTINInvalidError("Invalid GSTIN structure or checksum")
    if not cleaned.startswith(state_code):
        raise GSTINInvalidError(f"GSTIN state prefix '{cleaned[:2]}' does not match billing state code '{state_code}'")


def format_client_response(client: Client, contacts: list[ClientContact]) -> ClientResponse:
    billing_addr: Optional[Address] = None
    if client.billing_address:
        try:
            addr_dict = json.loads(client.billing_address) if isinstance(client.billing_address, str) else client.billing_address
            billing_addr = Address(**addr_dict)
        except Exception:
            billing_addr = None

    return ClientResponse(
        id=client.id,
        code=client.code,
        name=client.name,
        legal_name=client.legal_name,
        client_type=client.client_type,
        pan=client.pan,
        gstin=client.gstin,
        status=client.status,
        billing_address=billing_addr,
        owner_user_id=client.owner_user_id,
        version=client.version,
        contacts=[ContactResponse.model_validate(c) for c in contacts],
    )


class ClientService:
    @staticmethod
    async def list_clients(
        session: AsyncSession,
        org_id: uuid.UUID,
        status: Optional[str] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PageResponse[ClientResponse]:
        query = select(Client).where(Client.organization_id == org_id)
        if status:
            query = query.where(Client.status == status)

        if cursor:
            cursor_data = decode_cursor(cursor)
            if "last_code" in cursor_data:
                query = query.where(Client.code > cursor_data["last_code"])

        query = query.order_by(Client.code.asc()).limit(limit + 1)
        result = await session.execute(query)
        rows = list(result.scalars().all())

        has_more = len(rows) > limit
        data_rows = rows[:limit]

        next_cursor = None
        if has_more and data_rows:
            next_cursor = encode_cursor({"last_code": data_rows[-1].code})

        client_ids = [c.id for c in data_rows]
        contact_map: dict[uuid.UUID, list[ClientContact]] = {cid: [] for cid in client_ids}
        if client_ids:
            c_query = select(ClientContact).where(ClientContact.client_id.in_(client_ids))
            c_res = await session.execute(c_query)
            for contact in c_res.scalars().all():
                contact_map[contact.client_id].append(contact)

        return PageResponse(
            data=[format_client_response(c, contact_map.get(c.id, [])) for c in data_rows],
            page=PageMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    @staticmethod
    async def create_client(
        session: AsyncSession,
        org_id: uuid.UUID,
        payload: ClientCreate,
    ) -> ClientResponse:
        validate_gstin(payload.gstin, payload.billing_address.state_code)

        # Check for duplicates by GSTIN or PAN
        if payload.gstin:
            dup_gstin = await session.execute(
                select(Client).where(Client.organization_id == org_id, Client.gstin == payload.gstin.strip().upper())
            )
            existing = dup_gstin.scalars().first()
            if existing:
                raise DuplicateClientError(existing.id, field="GSTIN")

        if payload.pan:
            dup_pan = await session.execute(
                select(Client).where(Client.organization_id == org_id, Client.pan == payload.pan.strip().upper())
            )
            existing = dup_pan.scalars().first()
            if existing:
                raise DuplicateClientError(existing.id, field="PAN")

        count_res = await session.execute(
            select(func.count(Client.id)).where(Client.organization_id == org_id)
        )
        total_count = count_res.scalar_one() or 0
        code = f"CL-{total_count + 1:04d}"

        client = Client(
            organization_id=org_id,
            code=code,
            name=payload.name,
            legal_name=payload.legal_name,
            client_type=payload.client_type,
            pan=payload.pan.strip().upper() if payload.pan else None,
            gstin=payload.gstin.strip().upper() if payload.gstin else None,
            status="active",
            billing_address=payload.billing_address.model_dump_json(),
            owner_user_id=payload.owner_user_id,
            version=1,
        )
        session.add(client)
        await session.flush()
        return format_client_response(client, [])

    @staticmethod
    async def get_client(
        session: AsyncSession,
        client_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> ClientResponse:
        res = await session.execute(
            select(Client).where(Client.id == client_id, Client.organization_id == org_id)
        )
        client = res.scalars().first()
        if not client:
            raise ClientNotFoundError(str(client_id))

        c_res = await session.execute(
            select(ClientContact).where(ClientContact.client_id == client.id)
        )
        contacts = list(c_res.scalars().all())
        return format_client_response(client, contacts)

    @staticmethod
    async def update_client(
        session: AsyncSession,
        client_id: uuid.UUID,
        org_id: uuid.UUID,
        payload: ClientUpdate,
        if_match: Optional[str] = None,
    ) -> ClientResponse:
        res = await session.execute(
            select(Client).where(Client.id == client_id, Client.organization_id == org_id)
        )
        client = res.scalars().first()
        if not client:
            raise ClientNotFoundError(str(client_id))

        if if_match is not None:
            expected_version = int(if_match.strip('"').replace("W/", ""))
            if client.version != expected_version:
                raise VersionConflictError(client.version)

        if payload.gstin:
            state_code = "10"
            if payload.billing_address:
                state_code = payload.billing_address.state_code
            elif client.billing_address:
                try:
                    state_code = json.loads(client.billing_address).get("state_code", "10")
                except Exception:
                    state_code = "10"
            validate_gstin(payload.gstin, state_code)
            client.gstin = payload.gstin.strip().upper()

        if payload.name is not None:
            client.name = payload.name
        if payload.legal_name is not None:
            client.legal_name = payload.legal_name
        if payload.billing_address is not None:
            client.billing_address = payload.billing_address.model_dump_json()
        if payload.owner_user_id is not None:
            client.owner_user_id = payload.owner_user_id
        if payload.status is not None:
            client.status = payload.status

        client.version += 1
        await session.flush()

        c_res = await session.execute(
            select(ClientContact).where(ClientContact.client_id == client.id)
        )
        contacts = list(c_res.scalars().all())
        return format_client_response(client, contacts)

    @staticmethod
    async def add_contact(
        session: AsyncSession,
        client_id: uuid.UUID,
        org_id: uuid.UUID,
        payload: ContactCreate,
    ) -> ContactResponse:
        res = await session.execute(
            select(Client).where(Client.id == client_id, Client.organization_id == org_id)
        )
        client = res.scalars().first()
        if not client:
            raise ClientNotFoundError(str(client_id))

        contact = ClientContact(
            client_id=client.id,
            name=payload.name,
            designation=payload.designation,
            email=str(payload.email) if payload.email else None,
            phone=payload.phone,
            is_primary=payload.is_primary,
        )
        session.add(contact)
        await session.flush()
        return ContactResponse.model_validate(contact)
