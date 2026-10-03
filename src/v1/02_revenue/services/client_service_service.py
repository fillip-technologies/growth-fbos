"""Outside services a client uses (hosting, insurance, telecom, accounting, anything),
with the organization's provider and category lists."""

import uuid
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    ClientNotFoundError,
    ClientServiceNotFoundError,
    DuplicateNameError,
    InvalidDateRangeError,
    PreconditionRequiredError,
    ProviderInUseError,
    ServiceCategoryNotFoundError,
    ServiceProviderNotFoundError,
    VersionConflictError,
)
from models.client import Client
from models.client_service import ClientServiceRecord, ServiceCategory, ServiceProvider
from schemas.client_service import (
    CategoryRef,
    ClientServiceCreate,
    ClientServiceResponse,
    ClientServiceUpdate,
    ProviderRef,
    ServiceCategoryCreate,
    ServiceCategoryResponse,
    ServiceCategoryUpdate,
    ServiceProviderCreate,
    ServiceProviderResponse,
    ServiceProviderUpdate,
)
from schemas.common import Money, PageMeta, PageResponse, decode_cursor, encode_cursor

# Created for an organization the first time it lists categories with none defined.
DEFAULT_CATEGORIES = [
    "Hosting",
    "Domain",
    "Email",
    "Software / SaaS",
    "Insurance",
    "Accounting / Tax",
    "Legal",
    "Banking / Finance",
    "Telecom / Internet",
    "Utilities",
    "Logistics",
    "Maintenance",
    "Equipment / Rental",
    "Other",
]


def _check_if_match(if_match: Optional[str], version: int) -> None:
    if if_match is None:
        raise PreconditionRequiredError()
    expected_version = int(if_match.strip('"').replace("W/", ""))
    if version != expected_version:
        raise VersionConflictError(version)


async def _get_category(session: AsyncSession, org_id: uuid.UUID, category_id: uuid.UUID) -> ServiceCategory:
    category = await session.get(ServiceCategory, category_id)
    if not category or category.organization_id != org_id:
        raise ServiceCategoryNotFoundError(str(category_id))
    return category


async def _get_provider(session: AsyncSession, org_id: uuid.UUID, provider_id: uuid.UUID) -> ServiceProvider:
    provider = await session.get(ServiceProvider, provider_id)
    if not provider or provider.organization_id != org_id:
        raise ServiceProviderNotFoundError(str(provider_id))
    return provider


async def _get_record(session: AsyncSession, org_id: uuid.UUID, record_id: uuid.UUID) -> ClientServiceRecord:
    record = await session.get(ClientServiceRecord, record_id)
    if not record or record.organization_id != org_id:
        raise ClientServiceNotFoundError(str(record_id))
    return record


async def _ensure_unique_name(session: AsyncSession, model, org_id: uuid.UUID, name: str, exclude_id=None) -> None:
    query = select(model.id).where(model.organization_id == org_id, func.lower(model.name) == name.lower())
    if exclude_id:
        query = query.where(model.id != exclude_id)
    if (await session.execute(query)).first():
        raise DuplicateNameError(name)


async def _category_refs(session: AsyncSession, ids: set) -> dict[uuid.UUID, CategoryRef]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    res = await session.execute(select(ServiceCategory).where(ServiceCategory.id.in_(ids)))
    return {c.id: CategoryRef(id=c.id, name=c.name) for c in res.scalars().all()}


def _format_provider(provider: ServiceProvider, categories: dict[uuid.UUID, CategoryRef]) -> ServiceProviderResponse:
    return ServiceProviderResponse(
        id=provider.id,
        name=provider.name,
        category=categories.get(provider.category_id),
        contact_name=provider.contact_name,
        phone=provider.phone,
        email=provider.email,
        website=provider.website,
        notes=provider.notes,
        version=provider.version,
    )


async def _format_records(session: AsyncSession, records: list[ClientServiceRecord]) -> list[ClientServiceResponse]:
    provider_ids = {r.provider_id for r in records}
    providers: dict[uuid.UUID, ProviderRef] = {}
    if provider_ids:
        res = await session.execute(select(ServiceProvider).where(ServiceProvider.id.in_(provider_ids)))
        providers = {p.id: ProviderRef(id=p.id, name=p.name) for p in res.scalars().all()}
    categories = await _category_refs(session, {r.category_id for r in records})

    return [
        ClientServiceResponse(
            id=r.id,
            client_id=r.client_id,
            provider=providers[r.provider_id],
            category=categories.get(r.category_id),
            name=r.name,
            reference_no=r.reference_no,
            managed_by=r.managed_by,
            start_date=r.start_date,
            end_date=r.end_date,
            renewal_date=r.renewal_date,
            auto_renew=r.auto_renew,
            cost=Money(amount=float(r.cost), currency=r.currency) if r.cost is not None else None,
            billing_cycle=r.billing_cycle,
            status=r.status,
            attributes=r.attributes or {},
            notes=r.notes,
            version=r.version,
            created_at=r.created_at,
        )
        for r in records
    ]


class ClientServiceService:
    # --- Categories ------------------------------------------------------

    @staticmethod
    async def list_categories(session: AsyncSession, org_id: uuid.UUID) -> PageResponse[ServiceCategoryResponse]:
        query = select(ServiceCategory).where(ServiceCategory.organization_id == org_id)
        categories = list((await session.execute(query.order_by(ServiceCategory.name.asc()))).scalars().all())
        if not categories:
            for name in DEFAULT_CATEGORIES:
                session.add(ServiceCategory(organization_id=org_id, name=name))
            await session.flush()
            categories = list((await session.execute(query.order_by(ServiceCategory.name.asc()))).scalars().all())
        # Categories are a short per-org list, so they come back as a single page.
        return PageResponse(
            data=[ServiceCategoryResponse.model_validate(c) for c in categories],
            page=PageMeta(next_cursor=None, has_more=False, limit=len(categories)),
        )

    @staticmethod
    async def create_category(
        session: AsyncSession, org_id: uuid.UUID, payload: ServiceCategoryCreate
    ) -> ServiceCategoryResponse:
        name = payload.name.strip()
        await _ensure_unique_name(session, ServiceCategory, org_id, name)
        category = ServiceCategory(organization_id=org_id, name=name)
        session.add(category)
        await session.flush()
        return ServiceCategoryResponse.model_validate(category)

    @staticmethod
    async def update_category(
        session: AsyncSession, org_id: uuid.UUID, category_id: uuid.UUID, payload: ServiceCategoryUpdate
    ) -> ServiceCategoryResponse:
        category = await _get_category(session, org_id, category_id)
        if payload.name is not None:
            name = payload.name.strip()
            await _ensure_unique_name(session, ServiceCategory, org_id, name, exclude_id=category.id)
            category.name = name
        if payload.is_active is not None:
            category.is_active = payload.is_active
        await session.flush()
        return ServiceCategoryResponse.model_validate(category)

    # --- Providers -------------------------------------------------------

    @staticmethod
    async def list_providers(
        session: AsyncSession,
        org_id: uuid.UUID,
        category_id: Optional[uuid.UUID] = None,
        q: Optional[str] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PageResponse[ServiceProviderResponse]:
        query = select(ServiceProvider).where(ServiceProvider.organization_id == org_id)
        if category_id:
            query = query.where(ServiceProvider.category_id == category_id)
        if q:
            query = query.where(func.lower(ServiceProvider.name).contains(q.lower()))
        if cursor:
            cursor_data = decode_cursor(cursor)
            if "last_name" in cursor_data:
                query = query.where(ServiceProvider.name > cursor_data["last_name"])

        query = query.order_by(ServiceProvider.name.asc()).limit(limit + 1)
        rows = list((await session.execute(query)).scalars().all())

        has_more = len(rows) > limit
        data_rows = rows[:limit]
        next_cursor = encode_cursor({"last_name": data_rows[-1].name}) if has_more and data_rows else None

        categories = await _category_refs(session, {p.category_id for p in data_rows})
        return PageResponse(
            data=[_format_provider(p, categories) for p in data_rows],
            page=PageMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    @staticmethod
    async def get_provider(session: AsyncSession, org_id: uuid.UUID, provider_id: uuid.UUID) -> ServiceProviderResponse:
        provider = await _get_provider(session, org_id, provider_id)
        return _format_provider(provider, await _category_refs(session, {provider.category_id}))

    @staticmethod
    async def create_provider(
        session: AsyncSession, org_id: uuid.UUID, payload: ServiceProviderCreate
    ) -> ServiceProviderResponse:
        name = payload.name.strip()
        await _ensure_unique_name(session, ServiceProvider, org_id, name)
        if payload.category_id:
            await _get_category(session, org_id, payload.category_id)
        provider = ServiceProvider(
            organization_id=org_id,
            name=name,
            category_id=payload.category_id,
            contact_name=payload.contact_name,
            phone=payload.phone,
            email=payload.email,
            website=payload.website,
            notes=payload.notes,
            version=1,
        )
        session.add(provider)
        await session.flush()
        return _format_provider(provider, await _category_refs(session, {provider.category_id}))

    @staticmethod
    async def update_provider(
        session: AsyncSession,
        org_id: uuid.UUID,
        provider_id: uuid.UUID,
        payload: ServiceProviderUpdate,
        if_match: Optional[str] = None,
    ) -> ServiceProviderResponse:
        provider = await _get_provider(session, org_id, provider_id)
        _check_if_match(if_match, provider.version)

        changes = payload.model_dump(exclude_unset=True)
        if changes.get("name") is not None:
            changes["name"] = changes["name"].strip()
            await _ensure_unique_name(session, ServiceProvider, org_id, changes["name"], exclude_id=provider.id)
        if changes.get("category_id"):
            await _get_category(session, org_id, changes["category_id"])
        for field, value in changes.items():
            setattr(provider, field, value)

        provider.version += 1
        await session.flush()
        return _format_provider(provider, await _category_refs(session, {provider.category_id}))

    @staticmethod
    async def delete_provider(session: AsyncSession, org_id: uuid.UUID, provider_id: uuid.UUID) -> None:
        provider = await session.get(ServiceProvider, provider_id)
        if not provider or provider.organization_id != org_id:
            return  # already gone: DELETE is idempotent
        in_use = await session.execute(
            select(ClientServiceRecord.id).where(ClientServiceRecord.provider_id == provider.id).limit(1)
        )
        if in_use.first():
            raise ProviderInUseError()
        await session.delete(provider)
        await session.flush()

    # --- Client services -------------------------------------------------

    @staticmethod
    async def list_services(
        session: AsyncSession,
        org_id: uuid.UUID,
        client_id: Optional[uuid.UUID] = None,
        provider_id: Optional[uuid.UUID] = None,
        category_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        managed_by: Optional[str] = None,
        renewal_within_days: Optional[int] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PageResponse[ClientServiceResponse]:
        query = select(ClientServiceRecord).where(ClientServiceRecord.organization_id == org_id)
        if client_id:
            query = query.where(ClientServiceRecord.client_id == client_id)
        if provider_id:
            query = query.where(ClientServiceRecord.provider_id == provider_id)
        if category_id:
            query = query.where(ClientServiceRecord.category_id == category_id)
        if status:
            query = query.where(ClientServiceRecord.status == status)
        if managed_by:
            query = query.where(ClientServiceRecord.managed_by == managed_by)
        if renewal_within_days is not None:
            # Includes overdue renewals so nothing slips past unnoticed.
            query = query.where(
                ClientServiceRecord.renewal_date.is_not(None),
                ClientServiceRecord.renewal_date <= date.today() + timedelta(days=renewal_within_days),
            )

        if cursor:
            cursor_data = decode_cursor(cursor)
            if "last_id" in cursor_data:
                query = query.where(ClientServiceRecord.id > uuid.UUID(cursor_data["last_id"]))

        query = query.order_by(ClientServiceRecord.id.asc()).limit(limit + 1)
        rows = list((await session.execute(query)).scalars().all())

        has_more = len(rows) > limit
        data_rows = rows[:limit]
        next_cursor = encode_cursor({"last_id": str(data_rows[-1].id)}) if has_more and data_rows else None

        return PageResponse(
            data=await _format_records(session, data_rows),
            page=PageMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    @staticmethod
    async def get_service(session: AsyncSession, org_id: uuid.UUID, record_id: uuid.UUID) -> ClientServiceResponse:
        record = await _get_record(session, org_id, record_id)
        return (await _format_records(session, [record]))[0]

    @staticmethod
    async def create_service(
        session: AsyncSession, org_id: uuid.UUID, client_id: uuid.UUID, payload: ClientServiceCreate
    ) -> ClientServiceResponse:
        res = await session.execute(select(Client).where(Client.id == client_id, Client.organization_id == org_id))
        if not res.scalars().first():
            raise ClientNotFoundError(str(client_id))

        provider = await _get_provider(session, org_id, payload.provider_id)
        category_id = payload.category_id or provider.category_id
        if payload.category_id:
            await _get_category(session, org_id, payload.category_id)

        record = ClientServiceRecord(
            organization_id=org_id,
            client_id=client_id,
            provider_id=provider.id,
            category_id=category_id,
            name=payload.name,
            reference_no=payload.reference_no,
            managed_by=payload.managed_by,
            start_date=payload.start_date,
            end_date=payload.end_date,
            renewal_date=payload.renewal_date,
            auto_renew=payload.auto_renew,
            cost=payload.cost.amount if payload.cost else None,
            currency=payload.cost.currency if payload.cost else "INR",
            billing_cycle=payload.billing_cycle,
            status=payload.status,
            attributes=payload.attributes or {},
            notes=payload.notes,
            version=1,
        )
        session.add(record)
        await session.flush()
        return (await _format_records(session, [record]))[0]

    @staticmethod
    async def update_service(
        session: AsyncSession,
        org_id: uuid.UUID,
        record_id: uuid.UUID,
        payload: ClientServiceUpdate,
        if_match: Optional[str] = None,
    ) -> ClientServiceResponse:
        record = await _get_record(session, org_id, record_id)
        _check_if_match(if_match, record.version)

        changes = payload.model_dump(exclude_unset=True)
        if changes.get("provider_id"):
            await _get_provider(session, org_id, changes["provider_id"])
        if changes.get("category_id"):
            await _get_category(session, org_id, changes["category_id"])
        if "cost" in changes:
            cost = changes.pop("cost")
            record.cost = cost["amount"] if cost else None
            if cost:
                record.currency = cost["currency"]
        for field, value in changes.items():
            setattr(record, field, value)

        if record.start_date and record.end_date and record.end_date < record.start_date:
            raise InvalidDateRangeError()

        record.version += 1
        await session.flush()
        return (await _format_records(session, [record]))[0]

    @staticmethod
    async def delete_service(session: AsyncSession, org_id: uuid.UUID, record_id: uuid.UUID) -> None:
        record = await session.get(ClientServiceRecord, record_id)
        if not record or record.organization_id != org_id:
            return  # already gone: DELETE is idempotent
        await session.delete(record)
        await session.flush()
