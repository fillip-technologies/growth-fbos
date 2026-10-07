"""
Document categories: each organization's own list, managed by its admins.

An upload must name one of them. An organization starts with a default set, created the
first time it touches categories, which admins then rename, restrict or extend.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import CategoryCodeExistsError, CategoryNotFoundError, CategoryUnknownError
from models.document import DocumentCategory
from schemas.category import CategoryCreate, CategoryResponse, CategoryUpdate

# (code, name, default classification)
DEFAULT_CATEGORIES = [
    ("attachment", "General Attachment", "internal"),
    ("contract", "Signed Contract", "confidential"),
    ("quotation", "Quotation", "confidential"),
    ("deliverable", "Deliverable", "confidential"),
    ("invoice", "Invoice PDF", "internal"),
    ("report", "Report", "internal"),
    ("policy", "Policy Document", "internal"),
]


def serialize_category(category: DocumentCategory) -> CategoryResponse:
    return CategoryResponse(
        id=category.id,
        code=category.code,
        name=category.name,
        default_classification=category.default_classification,
        allowed_mime_types=_split_mime_types(category.allowed_mime_types),
        max_file_size_bytes=category.max_file_size_bytes,
    )


def allowed_mime_types(category: DocumentCategory) -> list[str]:
    return _split_mime_types(category.allowed_mime_types)


def _split_mime_types(stored: str | None) -> list[str]:
    return [m.strip().lower() for m in (stored or "").split(",") if m.strip()]


def _join_mime_types(mime_types: list[str]) -> str | None:
    return ",".join(m.strip().lower() for m in mime_types if m.strip()) or None


class CategoryService:
    async def list_categories(self, session: AsyncSession, org_id: uuid.UUID) -> list[CategoryResponse]:
        categories = await self._org_categories(session, org_id)
        return [serialize_category(c) for c in categories]

    async def get_by_code(self, session: AsyncSession, org_id: uuid.UUID, code: str) -> DocumentCategory:
        categories = await self._org_categories(session, org_id)
        category = next((c for c in categories if c.code == code), None)
        if not category:
            raise CategoryUnknownError(code)
        return category

    async def create_category(
        self, session: AsyncSession, org_id: uuid.UUID, data: CategoryCreate
    ) -> CategoryResponse:
        categories = await self._org_categories(session, org_id)
        if any(c.code == data.code for c in categories):
            raise CategoryCodeExistsError(data.code)
        category = DocumentCategory(
            id=uuid.uuid4(),
            organization_id=org_id,
            code=data.code,
            name=data.name,
            default_classification=data.default_classification,
            allowed_mime_types=_join_mime_types(data.allowed_mime_types),
            max_file_size_bytes=data.max_file_size_bytes,
        )
        session.add(category)
        await session.commit()
        return serialize_category(category)

    async def update_category(
        self, session: AsyncSession, org_id: uuid.UUID, category_id: uuid.UUID, data: CategoryUpdate
    ) -> CategoryResponse:
        category = (
            await session.execute(
                select(DocumentCategory).where(
                    DocumentCategory.id == category_id, DocumentCategory.organization_id == org_id
                )
            )
        ).scalar_one_or_none()
        if not category:
            raise CategoryNotFoundError(str(category_id))

        provided = data.model_fields_set
        if data.name is not None:
            category.name = data.name
        if data.default_classification is not None:
            category.default_classification = data.default_classification
        if data.allowed_mime_types is not None:
            category.allowed_mime_types = _join_mime_types(data.allowed_mime_types)
        if "max_file_size_bytes" in provided:
            category.max_file_size_bytes = data.max_file_size_bytes
        await session.commit()
        return serialize_category(category)

    async def _org_categories(self, session: AsyncSession, org_id: uuid.UUID) -> list[DocumentCategory]:
        """The organization's categories, creating the default set on first use."""
        stmt = (
            select(DocumentCategory)
            .where(DocumentCategory.organization_id == org_id)
            .order_by(DocumentCategory.name)
        )
        categories = list((await session.execute(stmt)).scalars().all())
        if categories:
            return categories

        categories = [
            DocumentCategory(
                id=uuid.uuid4(),
                organization_id=org_id,
                code=code,
                name=name,
                default_classification=classification,
            )
            for code, name, classification in DEFAULT_CATEGORIES
        ]
        session.add_all(categories)
        try:
            await session.flush()
        except IntegrityError:
            # A parallel request created them first. Nothing else is pending yet: every
            # caller looks categories up before writing anything.
            await session.rollback()
            return list((await session.execute(stmt)).scalars().all())
        return sorted(categories, key=lambda c: c.name)


category_service = CategoryService()
