from datetime import datetime, timezone
import logging
from typing import Any, Optional
import uuid

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    DuplicateCodeError,
    FieldDefinitionNotFoundError,
    FieldSchemaInvalidError,
    PackVersionConflictError,
    PreconditionFailedError,
    VerticalNotFoundError,
    VerticalPackInvalidError,
    VerticalPackNotFoundError,
)
from models.organization import Organization
from models.vertical import (
    FieldDefinition,
    ObjectType,
    Vertical,
    VerticalPack,
    VerticalPackInstallation,
    VerticalPackVersion,
)
from schemas.common import PageInfo, PaginatedResponse
from schemas.rbac import VerticalRef
from schemas.vertical import (
    CustomFieldsSection,
    FieldDefinitionCreate,
    FieldDefinitionResponse,
    ObjectTypeResponse,
    PackContent,
    PackField,
    PackInstallationResponse,
    PackPlanItem,
    PackPreviewResponse,
    PackVersionResponse,
    VerticalCreate,
    VerticalPackCreate,
    VerticalPackResponse,
    VerticalPackUpdate,
    VerticalResponse,
    VerticalUpdate,
)
from services.event_publisher import event_publisher
from utils.dates import iso_utc

logger = logging.getLogger("identity.vertical_service")

# Default registry of standard business object types
DEFAULT_OBJECT_TYPES = [
    ("work.work_unit", "work", "Work unit"),
    ("task.task", "task", "Task"),
    ("workflow.definition", "workflow", "Workflow definition"),
    ("document.document", "document", "Document"),
    ("revenue.contract", "revenue", "Contract"),
    ("revenue.deal", "revenue", "Deal"),
    ("revenue.lead", "revenue", "Lead"),
    ("billing.invoice", "billing", "Invoice"),
    ("approval.request", "approval", "Approval request"),
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _check_if_match(if_match: Optional[str], current: int) -> None:
    """Optimistic locking: a stale If-Match (an older revision) is rejected; none is allowed."""
    if if_match is None:
        return
    expected = if_match.strip(' "')
    if expected.isdigit() and int(expected) != current:
        raise PreconditionFailedError(f"ETag mismatch. Current version is '{current}'")


# ---------------------------------------------------------------------------
# Pack field -> JSON Schema. Pack sections are stored in the builder's own shape and
# turned into the same JSON Schema that manually created field definitions use.
# ---------------------------------------------------------------------------

def _field_property(field: PackField) -> dict[str, Any]:
    prop: dict[str, Any] = {"title": field.label}
    if field.type == "text":
        prop["type"] = "string"
    elif field.type == "date":
        prop.update(type="string", format="date")
    elif field.type == "choice":
        prop.update(type="string", enum=list(field.options))
    else:
        prop["type"] = field.type
    return prop


def section_schemas(section: CustomFieldsSection) -> tuple[dict[str, Any], dict[str, Any]]:
    """The (json_schema, ui_schema) a custom-fields section installs."""
    json_schema: dict[str, Any] = {
        "type": "object",
        "properties": {f.key: _field_property(f) for f in section.fields},
    }
    required = [f.key for f in section.fields if f.required]
    if required:
        json_schema["required"] = required
    return json_schema, {"ui:order": [f.key for f in section.fields]}


def _field_signatures(json_schema: Optional[dict[str, Any]]) -> dict[str, tuple[Any, bool]]:
    """key -> (property, required): what decides whether a field changed between versions."""
    schema = json_schema or {}
    required = set(schema.get("required") or [])
    return {key: (prop, key in required) for key, prop in (schema.get("properties") or {}).items()}


def _plan_section(
    section: CustomFieldsSection, installed: Optional[FieldDefinition]
) -> PackPlanItem:
    json_schema, ui_schema = section_schemas(section)
    if installed is None:
        return PackPlanItem(
            object_type=section.object_type, action="create", added_fields=[f.key for f in section.fields]
        )

    old = _field_signatures(installed.json_schema)
    new = _field_signatures(json_schema)
    item = PackPlanItem(
        object_type=section.object_type,
        action="update",
        added_fields=[k for k in new if k not in old],
        removed_fields=[k for k in old if k not in new],
        changed_fields=[k for k in new if k in old and new[k] != old[k]],
        field_definition_id=installed.id,
    )
    unchanged = not (item.added_fields or item.removed_fields or item.changed_fields)
    if unchanged and (installed.ui_schema or {}) == ui_schema:
        item.action = "unchanged"
    return item


class VerticalService:
    async def _ensure_object_types(self, session: AsyncSession) -> None:
        for code, svc, name in DEFAULT_OBJECT_TYPES:
            existing = await session.get(ObjectType, code)
            if not existing:
                session.add(ObjectType(code=code, owning_service=svc, display_name=name))
        await session.commit()

    async def _page(
        self, session: AsyncSession, query: Select, limit: int, cursor: Optional[str]
    ) -> tuple[list, PageInfo]:
        offset = int(cursor) if cursor and cursor.isdigit() else 0
        result = await session.execute(query.offset(offset).limit(limit + 1))
        items = list(result.scalars().all())
        has_more = len(items) > limit
        next_cursor = str(offset + limit) if has_more else None
        return items[:limit], PageInfo(next_cursor=next_cursor, has_more=has_more, limit=limit)

    async def _client_id(self, session: AsyncSession, organization_id: uuid.UUID) -> uuid.UUID:
        """Verticals and packs belong to the client, shared by all of its organizations."""
        organization = await session.get(Organization, organization_id)
        return organization.client_id

    def _build_field_definition_response(self, fd: FieldDefinition) -> FieldDefinitionResponse:
        return FieldDefinitionResponse(
            id=fd.id,
            object_type=fd.object_type,
            vertical_id=fd.vertical_id,
            version_no=fd.version_no,
            json_schema=fd.json_schema or {},
            ui_schema=fd.ui_schema or {},
            status=fd.status,
            source_pack_id=fd.source_pack_id,
            source_pack_version=fd.source_pack_version,
        )

    # -----------------------------------------------------------------------
    # Object types
    # -----------------------------------------------------------------------

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

        items, page = await self._page(session, query, limit, cursor)
        data = [
            ObjectTypeResponse(code=item.code, owning_service=item.owning_service, display_name=item.display_name)
            for item in items
        ]
        return PaginatedResponse(data=data, page=page)

    async def _check_object_types(self, session: AsyncSession, content: PackContent) -> None:
        await self._ensure_object_types(session)
        for section in content.sections:
            if not await session.get(ObjectType, section.object_type):
                raise VerticalPackInvalidError(f"Record type '{section.object_type}' is not registered.")

    # -----------------------------------------------------------------------
    # Verticals
    # -----------------------------------------------------------------------

    async def _get_vertical(self, session: AsyncSession, client_id: uuid.UUID, vertical_id: uuid.UUID) -> Vertical:
        vertical = await session.get(Vertical, vertical_id)
        if not vertical or vertical.client_id != client_id:
            raise VerticalNotFoundError()
        return vertical

    async def list_verticals(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        status: Optional[str] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PaginatedResponse[VerticalResponse]:
        client_id = await self._client_id(session, organization_id)
        query = select(Vertical).where(Vertical.client_id == client_id)
        if status:
            query = query.where(Vertical.status == status)
        query = query.order_by(Vertical.name.asc(), Vertical.id.asc())

        items, page = await self._page(session, query, limit, cursor)
        return PaginatedResponse(data=[VerticalResponse.model_validate(v) for v in items], page=page)

    async def create_vertical(
        self, session: AsyncSession, organization_id: uuid.UUID, data: VerticalCreate
    ) -> VerticalResponse:
        client_id = await self._client_id(session, organization_id)
        clash = await session.execute(
            select(Vertical.id).where(Vertical.client_id == client_id, Vertical.code == data.code)
        )
        if clash.scalar_one_or_none():
            raise DuplicateCodeError(data.code)

        vertical = Vertical(client_id=client_id, name=data.name.strip(), code=data.code, status="active")
        session.add(vertical)
        await session.commit()
        await session.refresh(vertical)
        return VerticalResponse.model_validate(vertical)

    async def update_vertical(
        self, session: AsyncSession, organization_id: uuid.UUID, vertical_id: uuid.UUID, data: VerticalUpdate
    ) -> VerticalResponse:
        client_id = await self._client_id(session, organization_id)
        vertical = await self._get_vertical(session, client_id, vertical_id)
        if data.name is not None:
            vertical.name = data.name.strip()
        if data.status is not None:
            vertical.status = data.status
        await session.commit()
        await session.refresh(vertical)
        return VerticalResponse.model_validate(vertical)

    # -----------------------------------------------------------------------
    # Field definitions
    # -----------------------------------------------------------------------

    async def list_field_definitions(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        object_type: Optional[str] = None,
        vertical_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
        sort: Optional[str] = None,
    ) -> PaginatedResponse[FieldDefinitionResponse]:
        query = select(FieldDefinition).where(FieldDefinition.organization_id == organization_id)

        if object_type:
            query = query.where(FieldDefinition.object_type == object_type)
        if vertical_id:
            query = query.where(FieldDefinition.vertical_id == vertical_id)
        if status:
            query = query.where(FieldDefinition.status == status)

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

        items, page = await self._page(session, query, limit, cursor)
        return PaginatedResponse(data=[self._build_field_definition_response(fd) for fd in items], page=page)

    async def create_field_definition(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        data: FieldDefinitionCreate,
    ) -> FieldDefinitionResponse:
        if not isinstance(data.json_schema, dict) or "type" not in data.json_schema:
            raise FieldSchemaInvalidError("Schema must be a valid JSON Schema object with a 'type' property")

        await self._ensure_object_types(session)

        obj_type = await session.get(ObjectType, data.object_type)
        if not obj_type:
            raise FieldSchemaInvalidError(f"Object type '{data.object_type}' is not registered.")

        if data.vertical_id:
            client_id = await self._client_id(session, organization_id)
            vertical = await session.get(Vertical, data.vertical_id)
            if not vertical or vertical.client_id != client_id:
                raise FieldSchemaInvalidError(f"Vertical '{data.vertical_id}' does not exist.")

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

        _check_if_match(if_match, fd.version_no)

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

    # -----------------------------------------------------------------------
    # Vertical packs: design (client-wide)
    # -----------------------------------------------------------------------

    def _build_version_response(self, version: VerticalPackVersion) -> PackVersionResponse:
        return PackVersionResponse(
            version_no=version.version_no,
            status=version.status,
            revision=version.revision,
            content=PackContent.model_validate(version.content),
            created_at=iso_utc(version.created_at),
            published_at=iso_utc(version.published_at),
        )

    def _build_installation_response(self, installation: VerticalPackInstallation) -> PackInstallationResponse:
        return PackInstallationResponse(
            organization_id=installation.organization_id,
            version_no=installation.version_no,
            status=installation.status,
            results=[PackPlanItem.model_validate(r) for r in installation.results or []],
            installed_at=iso_utc(installation.installed_at),
        )

    def _build_pack_response(
        self, pack: VerticalPack, installation: Optional[VerticalPackInstallation]
    ) -> VerticalPackResponse:
        published = [v.version_no for v in pack.versions if v.status == "published"]
        drafts = [v.version_no for v in pack.versions if v.status == "draft"]
        return VerticalPackResponse(
            id=pack.id,
            code=pack.code,
            name=pack.name,
            description=pack.description,
            vertical=VerticalRef(id=pack.vertical.id, name=pack.vertical.name),
            versions=[self._build_version_response(v) for v in pack.versions],
            latest_published_version=max(published, default=None),
            draft_version=max(drafts, default=None),
            installation=self._build_installation_response(installation) if installation else None,
        )

    async def _get_pack(self, session: AsyncSession, client_id: uuid.UUID, pack_id: uuid.UUID) -> VerticalPack:
        pack = await session.get(VerticalPack, pack_id)
        if not pack or pack.client_id != client_id:
            raise VerticalPackNotFoundError()
        return pack

    def _get_version(self, pack: VerticalPack, version_no: int) -> VerticalPackVersion:
        version = next((v for v in pack.versions if v.version_no == version_no), None)
        if not version:
            raise VerticalPackNotFoundError()
        return version

    async def _installation(
        self, session: AsyncSession, pack_id: uuid.UUID, organization_id: uuid.UUID
    ) -> Optional[VerticalPackInstallation]:
        result = await session.execute(
            select(VerticalPackInstallation).where(
                VerticalPackInstallation.pack_id == pack_id,
                VerticalPackInstallation.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def _pack_response(
        self, session: AsyncSession, pack: VerticalPack, organization_id: uuid.UUID
    ) -> VerticalPackResponse:
        await session.refresh(pack, attribute_names=["versions", "vertical"])
        return self._build_pack_response(pack, await self._installation(session, pack.id, organization_id))

    async def list_vertical_packs(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        vertical_id: Optional[uuid.UUID] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PaginatedResponse[VerticalPackResponse]:
        client_id = await self._client_id(session, organization_id)
        query = select(VerticalPack).where(VerticalPack.client_id == client_id)
        if vertical_id:
            query = query.where(VerticalPack.vertical_id == vertical_id)
        query = query.order_by(VerticalPack.name.asc(), VerticalPack.id.asc())

        packs, page = await self._page(session, query, limit, cursor)
        installations = {}
        if packs:
            result = await session.execute(
                select(VerticalPackInstallation).where(
                    VerticalPackInstallation.organization_id == organization_id,
                    VerticalPackInstallation.pack_id.in_([p.id for p in packs]),
                )
            )
            installations = {i.pack_id: i for i in result.scalars().all()}

        return PaginatedResponse(
            data=[self._build_pack_response(p, installations.get(p.id)) for p in packs],
            page=page,
        )

    async def get_vertical_pack(
        self, session: AsyncSession, organization_id: uuid.UUID, pack_id: uuid.UUID
    ) -> VerticalPackResponse:
        client_id = await self._client_id(session, organization_id)
        pack = await self._get_pack(session, client_id, pack_id)
        return await self._pack_response(session, pack, organization_id)

    async def create_vertical_pack(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        data: VerticalPackCreate,
    ) -> VerticalPackResponse:
        client_id = await self._client_id(session, organization_id)
        vertical = await self._get_vertical(session, client_id, data.vertical_id)
        if vertical.status != "active":
            raise VerticalPackInvalidError(f"Vertical '{vertical.name}' is archived.")
        clash = await session.execute(
            select(VerticalPack.id).where(VerticalPack.client_id == client_id, VerticalPack.code == data.code)
        )
        if clash.scalar_one_or_none():
            raise DuplicateCodeError(data.code)
        await self._check_object_types(session, data.content)

        pack = VerticalPack(
            client_id=client_id,
            vertical_id=vertical.id,
            code=data.code,
            name=data.name.strip(),
            description=data.description,
        )
        pack.versions.append(
            VerticalPackVersion(version_no=1, content=data.content.model_dump(), status="draft", revision=1)
        )
        session.add(pack)
        await session.commit()
        return await self._pack_response(session, pack, organization_id)

    async def update_vertical_pack(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        pack_id: uuid.UUID,
        data: VerticalPackUpdate,
    ) -> VerticalPackResponse:
        client_id = await self._client_id(session, organization_id)
        pack = await self._get_pack(session, client_id, pack_id)
        if data.vertical_id is not None and data.vertical_id != pack.vertical_id:
            vertical = await self._get_vertical(session, client_id, data.vertical_id)
            if vertical.status != "active":
                raise VerticalPackInvalidError(f"Vertical '{vertical.name}' is archived.")
            pack.vertical_id = vertical.id
        if data.name is not None:
            pack.name = data.name.strip()
        if "description" in data.model_fields_set:
            pack.description = data.description
        await session.commit()
        return await self._pack_response(session, pack, organization_id)

    async def create_pack_version(
        self, session: AsyncSession, organization_id: uuid.UUID, pack_id: uuid.UUID
    ) -> VerticalPackResponse:
        """Start the next draft as a copy of the latest published version."""
        client_id = await self._client_id(session, organization_id)
        pack = await self._get_pack(session, client_id, pack_id)
        if any(v.status == "draft" for v in pack.versions):
            raise PackVersionConflictError("This pack already has a draft. Edit or publish it first.")

        latest = max(pack.versions, key=lambda v: v.version_no)
        pack.versions.append(
            VerticalPackVersion(
                version_no=latest.version_no + 1, content=latest.content, status="draft", revision=1
            )
        )
        await session.commit()
        return await self._pack_response(session, pack, organization_id)

    async def replace_pack_version_content(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        pack_id: uuid.UUID,
        version_no: int,
        content: PackContent,
        if_match: Optional[str] = None,
    ) -> VerticalPackResponse:
        client_id = await self._client_id(session, organization_id)
        pack = await self._get_pack(session, client_id, pack_id)
        version = self._get_version(pack, version_no)
        if version.status != "draft":
            raise PackVersionConflictError(f"Version {version_no} is published and can't be changed. Start a new version.")
        _check_if_match(if_match, version.revision)
        await self._check_object_types(session, content)

        version.content = content.model_dump()
        version.revision += 1
        await session.commit()
        return await self._pack_response(session, pack, organization_id)

    async def publish_pack_version(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        pack_id: uuid.UUID,
        version_no: int,
        if_match: Optional[str] = None,
    ) -> VerticalPackResponse:
        client_id = await self._client_id(session, organization_id)
        pack = await self._get_pack(session, client_id, pack_id)
        version = self._get_version(pack, version_no)
        if version.status != "draft":
            raise PackVersionConflictError(f"Version {version_no} is already published.")
        _check_if_match(if_match, version.revision)
        content = PackContent.model_validate(version.content)
        if not content.sections:
            raise VerticalPackInvalidError("Add at least one section before publishing.")
        await self._check_object_types(session, content)

        version.status = "published"
        version.published_at = _utc_now()
        await session.commit()

        await event_publisher.publish(
            "identity.vertical_pack.published.v1",
            {"pack_id": str(pack.id), "client_id": str(client_id), "code": pack.code, "version_no": version_no},
        )
        return await self._pack_response(session, pack, organization_id)

    # -----------------------------------------------------------------------
    # Vertical packs: install into one organization
    # -----------------------------------------------------------------------

    async def _installed_definitions(
        self, session: AsyncSession, pack_id: uuid.UUID, organization_id: uuid.UUID
    ) -> dict[str, FieldDefinition]:
        """object_type -> the live (published) definition this pack installed in the organization."""
        result = await session.execute(
            select(FieldDefinition).where(
                FieldDefinition.organization_id == organization_id,
                FieldDefinition.source_pack_id == pack_id,
                FieldDefinition.status == "published",
            )
        )
        return {fd.object_type: fd for fd in result.scalars().all()}

    async def _plan(
        self,
        session: AsyncSession,
        pack: VerticalPack,
        version: VerticalPackVersion,
        organization_id: uuid.UUID,
    ) -> tuple[PackContent, dict[str, FieldDefinition], list[PackPlanItem]]:
        if version.status != "published":
            raise PackVersionConflictError(f"Version {version.version_no} is a draft. Publish it before installing.")
        content = PackContent.model_validate(version.content)
        installed = await self._installed_definitions(session, pack.id, organization_id)

        items = [_plan_section(s, installed.get(s.object_type)) for s in content.sections]
        wanted = {s.object_type for s in content.sections}
        items += [
            PackPlanItem(
                object_type=object_type,
                action="retire",
                removed_fields=list(_field_signatures(fd.json_schema)),
                field_definition_id=fd.id,
            )
            for object_type, fd in installed.items()
            if object_type not in wanted
        ]
        return content, installed, items

    async def preview_installation(
        self, session: AsyncSession, organization_id: uuid.UUID, pack_id: uuid.UUID, version_no: int
    ) -> PackPreviewResponse:
        client_id = await self._client_id(session, organization_id)
        pack = await self._get_pack(session, client_id, pack_id)
        version = self._get_version(pack, version_no)
        _, _, items = await self._plan(session, pack, version, organization_id)
        installation = await self._installation(session, pack.id, organization_id)
        return PackPreviewResponse(
            version_no=version_no,
            installed_version_no=installation.version_no if installation else None,
            items=items,
        )

    async def install_pack(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        pack_id: uuid.UUID,
        version_no: int,
    ) -> PackInstallationResponse:
        """
        Bring the organization to exactly `version_no` of the pack, in one transaction.
        Installing the same version again changes nothing; a changed section replaces the
        old definition (retired, never deleted, so values already entered are kept).
        """
        client_id = await self._client_id(session, organization_id)
        pack = await self._get_pack(session, client_id, pack_id)
        version = self._get_version(pack, version_no)
        content, installed, items = await self._plan(session, pack, version, organization_id)
        sections = {s.object_type: s for s in content.sections}

        for item in items:
            previous = installed.get(item.object_type)
            if item.action in ("update", "retire"):
                previous.status = "retired"
            if item.action not in ("create", "update"):
                continue
            json_schema, ui_schema = section_schemas(sections[item.object_type])
            definition = FieldDefinition(
                id=uuid.uuid4(),
                organization_id=organization_id,
                vertical_id=pack.vertical_id,
                object_type=item.object_type,
                version_no=previous.version_no + 1 if previous else 1,
                json_schema=json_schema,
                ui_schema=ui_schema,
                status="published",
                source_pack_id=pack.id,
                source_pack_version=version_no,
            )
            session.add(definition)
            item.field_definition_id = definition.id

        installation = await self._installation(session, pack.id, organization_id)
        if installation is None:
            installation = VerticalPackInstallation(pack_id=pack.id, organization_id=organization_id)
            session.add(installation)
        installation.version_no = version_no
        installation.status = "active"
        installation.results = [i.model_dump(mode="json") for i in items]
        installation.installed_at = _utc_now()
        installation.installed_by = user_id
        await session.commit()
        await session.refresh(installation)

        await event_publisher.publish(
            "identity.vertical_pack.installed.v1",
            {
                "pack_id": str(pack.id),
                "organization_id": str(organization_id),
                "code": pack.code,
                "version_no": version_no,
            },
        )
        return self._build_installation_response(installation)


vertical_service = VerticalService()
