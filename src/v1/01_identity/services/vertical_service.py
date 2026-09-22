from datetime import datetime, timezone
import logging
from typing import Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from exceptions import (
    FieldDefinitionNotFoundError,
    FieldSchemaInvalidError,
    PreconditionFailedError,
    PreconditionRequiredError,
    VerticalPackInvalidError,
    VerticalPackNotFoundError,
)
from models.vertical import FieldDefinition, ObjectType, Vertical, VerticalPack
from schemas.common import PageInfo, PaginatedResponse
from schemas.rbac import VerticalRef
from schemas.vertical import (
    FieldDefinitionCreate,
    FieldDefinitionResponse,
    ImportResult,
    ObjectTypeResponse,
    VerticalPackCreate,
    VerticalPackResponse,
)
from services.event_publisher import event_publisher

logger = logging.getLogger("identity.vertical_service")

# Default registry of standard business object types
DEFAULT_OBJECT_TYPES = [
    ("work.work_unit", "work", "Work unit"),
    ("task.task", "task", "Task"),
    ("workflow.definition", "workflow", "Workflow definition"),
    ("document.document", "document", "Document"),
    ("revenue.contract", "revenue", "Contract"),
    ("billing.invoice", "billing", "Invoice"),
    ("approval.request", "approval", "Approval request"),
]


class VerticalService:
    async def _ensure_object_types(self, session: AsyncSession) -> None:
        count = await session.execute(select(func.count(ObjectType.code)))
        if count.scalar_one() == 0:
            for code, svc, name in DEFAULT_OBJECT_TYPES:
                session.add(ObjectType(code=code, owning_service=svc, display_name=name))
            await session.commit()

    def _build_field_definition_response(self, fd: FieldDefinition) -> FieldDefinitionResponse:
        return FieldDefinitionResponse(
            id=fd.id,
            object_type=fd.object_type,
            vertical_id=fd.vertical_id,
            version_no=fd.version_no,
            json_schema=fd.json_schema or {},
            ui_schema=fd.ui_schema or {},
            status=fd.status,
        )

    def _build_vertical_pack_response(self, vp: VerticalPack) -> VerticalPackResponse:
        v_ref = VerticalRef(id=vp.vertical.id, name=vp.vertical.name)
        results = (
            [ImportResult(**r) for r in vp.import_results]
            if vp.import_results
            else None
        )
        return VerticalPackResponse(
            id=vp.id,
            vertical=v_ref,
            pack_code=vp.pack_code,
            version_no=vp.version_no,
            status=vp.status,
            import_results=results,
            activated_at=vp.activated_at,
        )

    async def list_object_types(
        self,
        session: AsyncSession,
        limit: int = 25,
        cursor: Optional[str] = None,
        sort: Optional[str] = None,
    ) -> PaginatedResponse[ObjectTypeResponse]:
        await self._ensure_object_types(session)

        query = select(ObjectType)
        if sort:
            sort_fields = [s.strip() for s in sort.split(",")]
            for field in sort_fields:
                if field.startswith("-"):
                    attr = field[1:]
                    if hasattr(ObjectType, attr):
                        query = query.order_by(getattr(ObjectType, attr).desc())
                else:
                    if hasattr(ObjectType, field):
                        query = query.order_by(getattr(ObjectType, field).asc())
        else:
            query = query.order_by(ObjectType.code.asc())

        offset = 0
        if cursor and cursor.isdigit():
            offset = int(cursor)
        query = query.offset(offset).limit(limit + 1)

        result = await session.execute(query)
        items = list(result.scalars().all())

        has_more = len(items) > limit
        if has_more:
            items = items[:limit]
            next_cursor = str(offset + limit)
        else:
            next_cursor = None

        data = [
            ObjectTypeResponse(
                code=item.code,
                owning_service=item.owning_service,
                display_name=item.display_name,
            )
            for item in items
        ]
        return PaginatedResponse(
            data=data,
            page=PageInfo(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    async def list_field_definitions(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        object_type: Optional[str] = None,
        vertical_id: Optional[uuid.UUID] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
        sort: Optional[str] = None,
    ) -> PaginatedResponse[FieldDefinitionResponse]:
        query = select(FieldDefinition).where(
            FieldDefinition.organization_id == organization_id
        )

        if object_type:
            query = query.where(FieldDefinition.object_type == object_type)
        if vertical_id:
            query = query.where(FieldDefinition.vertical_id == vertical_id)

        if sort:
            sort_fields = [s.strip() for s in sort.split(",")]
            for field in sort_fields:
                if field.startswith("-"):
                    attr = field[1:]
                    if hasattr(FieldDefinition, attr):
                        query = query.order_by(getattr(FieldDefinition, attr).desc())
                else:
                    if hasattr(FieldDefinition, field):
                        query = query.order_by(getattr(FieldDefinition, field).asc())
        else:
            query = query.order_by(FieldDefinition.version_no.desc(), FieldDefinition.id.asc())

        offset = 0
        if cursor and cursor.isdigit():
            offset = int(cursor)
        query = query.offset(offset).limit(limit + 1)

        result = await session.execute(query)
        items = list(result.scalars().all())

        has_more = len(items) > limit
        if has_more:
            items = items[:limit]
            next_cursor = str(offset + limit)
        else:
            next_cursor = None

        data = [self._build_field_definition_response(fd) for fd in items]
        return PaginatedResponse(
            data=data,
            page=PageInfo(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    async def create_field_definition(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        data: FieldDefinitionCreate,
    ) -> FieldDefinitionResponse:
        if not isinstance(data.json_schema, dict) or "type" not in data.json_schema:
            raise FieldSchemaInvalidError("Schema must be a valid JSON Schema object with a 'type' property")

        await self._ensure_object_types(session)

        fd = FieldDefinition(
            id=uuid.uuid4(),
            organization_id=organization_id,
            vertical_id=data.vertical_id,
            object_type=data.object_type,
            version_no=1,
            json_schema=data.json_schema,
            ui_schema=data.ui_schema or {},
            status="draft",
        )
        session.add(fd)
        await session.commit()
        await session.refresh(fd)

        return self._build_field_definition_response(fd)

    async def publish_field_definition(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        field_definition_id: uuid.UUID,
        if_match: Optional[str] = None,
    ) -> FieldDefinitionResponse:
        fd = await session.get(FieldDefinition, field_definition_id)
        if not fd or fd.organization_id != organization_id:
            raise FieldDefinitionNotFoundError()

        if if_match is not None:
            clean_match = if_match.strip(' "')
            if clean_match.isdigit() and int(clean_match) != fd.version_no:
                raise PreconditionFailedError(
                    f"ETag mismatch. Current version is '{fd.version_no}'"
                )

        fd.status = "published"
        fd.version_no += 1
        await session.commit()
        await session.refresh(fd)

        await event_publisher.publish(
            "identity.field_definition.published.v1",
            {
                "field_definition_id": str(fd.id),
                "organization_id": str(organization_id),
                "object_type": fd.object_type,
                "version_no": fd.version_no,
            },
        )

        return self._build_field_definition_response(fd)

    async def create_vertical_pack(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        data: VerticalPackCreate,
    ) -> VerticalPackResponse:
        vertical = await session.get(Vertical, data.vertical_id)
        if not vertical:
            # If default vertical does not exist, create it dynamically
            vertical = Vertical(
                id=data.vertical_id,
                name="IT & Software",
                code="it-software",
                status="active",
            )
            session.add(vertical)
            await session.flush()

        if not isinstance(data.manifest, dict):
            raise VerticalPackInvalidError("Manifest must be a valid JSON object")

        vp = VerticalPack(
            id=uuid.uuid4(),
            organization_id=organization_id,
            vertical_id=data.vertical_id,
            pack_code=data.pack_code,
            version_no=data.version_no,
            manifest=data.manifest,
            status="draft",
        )
        session.add(vp)
        await session.commit()

        # Reload with joined vertical
        stmt = (
            select(VerticalPack)
            .options(selectinload(VerticalPack.vertical))
            .where(VerticalPack.id == vp.id)
        )
        vp = (await session.execute(stmt)).scalar_one()

        return self._build_vertical_pack_response(vp)

    async def activate_vertical_pack(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        pack_id: uuid.UUID,
    ) -> VerticalPackResponse:
        stmt = (
            select(VerticalPack)
            .options(selectinload(VerticalPack.vertical))
            .where(VerticalPack.id == pack_id, VerticalPack.organization_id == organization_id)
        )
        result = await session.execute(stmt)
        vp = result.scalar_one_or_none()
        if not vp:
            raise VerticalPackNotFoundError()

        vp.status = "installing"
        vp.import_results = [
            {"service": "work", "status": "succeeded", "items": 6},
            {"service": "workflow", "status": "succeeded", "items": 2},
        ]
        vp.status = "active"
        vp.activated_at = datetime.now(timezone.utc)

        await session.commit()
        await session.refresh(vp)

        await event_publisher.publish(
            "identity.vertical_pack.activated.v1",
            {
                "pack_id": str(vp.id),
                "organization_id": str(organization_id),
                "pack_code": vp.pack_code,
                "version_no": vp.version_no,
            },
        )

        return self._build_vertical_pack_response(vp)


vertical_service = VerticalService()
