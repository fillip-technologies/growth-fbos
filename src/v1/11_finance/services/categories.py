"""
Expense categories. Every organization starts with the built-in ones (stable uuid5 ids, so
seeding twice or from two instances at once inserts nothing new) and may add its own.

There is deliberately no hardware, salary or project-cost category: those are recorded in
inventory, people and delivery, and the dashboard adds them from there.
"""
import uuid
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.insert_ignore import insert_ignore
from exceptions import CategoryCodeTakenError, CategoryInactiveError, ExpenseCategoryNotFoundError
from models.finance import ExpenseCategory
from schemas.finance import CategoryCreate, CategoryUpdate

_BUILTIN_NAMESPACE = uuid.UUID("3c1f8e52-9a7d-4b6e-a0f4-11f1a2b3c011")

BUILTIN_CATEGORIES: list[tuple[str, str, str]] = [
    ("rent", "Rent & lease", "Office, warehouse and other premises rent"),
    ("utilities", "Utilities", "Electricity, water, internet, phone"),
    ("travel", "Travel & conveyance", "Tickets, hotels, cabs, fuel, per diem"),
    ("marketing", "Marketing & advertising", "Ads, events, sponsorships, collateral"),
    ("software", "Software & cloud", "Software bought outside the assets register"),
    ("professional_fees", "Professional fees", "Legal, audit, consulting, CA fees"),
    ("office_supplies", "Office supplies", "Stationery, pantry, consumables"),
    ("repairs", "Repairs & upkeep", "Premises repairs not tied to a tracked asset"),
    ("insurance", "Insurance", "Business insurance premiums"),
    ("bank_charges", "Bank charges", "Bank fees, payment gateway charges"),
    ("taxes_and_fees", "Taxes, duties & fees", "Licences, registrations, government fees"),
    ("other", "Other", "Anything that fits no other category"),
]


def builtin_id(organization_id: uuid.UUID, code: str) -> uuid.UUID:
    return uuid.uuid5(_BUILTIN_NAMESPACE, f"{organization_id}:{code}")


async def ensure_builtin_categories(session: AsyncSession, organization_id: uuid.UUID) -> None:
    rows = [
        {
            "id": builtin_id(organization_id, code),
            "organization_id": organization_id,
            "code": code,
            "name": name,
            "description": description,
            "is_builtin": True,
            "is_active": True,
        }
        for code, name, description in BUILTIN_CATEGORIES
    ]
    await session.execute(insert_ignore(ExpenseCategory), rows)


async def list_categories(session: AsyncSession, organization_id: uuid.UUID, active_only: bool) -> list[ExpenseCategory]:
    await ensure_builtin_categories(session, organization_id)
    await session.commit()
    query = select(ExpenseCategory).where(ExpenseCategory.organization_id == organization_id)
    if active_only:
        query = query.where(ExpenseCategory.is_active.is_(True))
    return list((await session.execute(query.order_by(ExpenseCategory.name))).scalars().all())


async def get_category(session: AsyncSession, organization_id: uuid.UUID, category_id: uuid.UUID) -> ExpenseCategory:
    category = await session.get(ExpenseCategory, category_id)
    if category is None or category.organization_id != organization_id:
        raise ExpenseCategoryNotFoundError()
    return category


async def usable_category(session: AsyncSession, organization_id: uuid.UUID, category_id: uuid.UUID) -> ExpenseCategory:
    """The category a new or changed expense goes in: it must exist here and be switched on."""
    await ensure_builtin_categories(session, organization_id)
    category = await get_category(session, organization_id, category_id)
    if not category.is_active:
        raise CategoryInactiveError()
    return category


async def create_category(session: AsyncSession, organization_id: uuid.UUID, body: CategoryCreate) -> ExpenseCategory:
    await ensure_builtin_categories(session, organization_id)
    taken = await session.scalar(
        select(ExpenseCategory.id).where(
            ExpenseCategory.organization_id == organization_id, ExpenseCategory.code == body.code
        )
    )
    if taken:
        raise CategoryCodeTakenError(body.code)
    category = ExpenseCategory(organization_id=organization_id, **body.model_dump(), is_builtin=False)
    session.add(category)
    try:
        await session.commit()
    except IntegrityError as exc:  # someone created the same code in the meantime
        await session.rollback()
        raise CategoryCodeTakenError(body.code) from exc
    await session.refresh(category)
    return category


async def update_category(
    session: AsyncSession, organization_id: uuid.UUID, category_id: uuid.UUID, body: CategoryUpdate
) -> ExpenseCategory:
    category = await get_category(session, organization_id, category_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        if field in ("name", "is_active") and value is None:
            continue  # required columns: null means "leave as is"
        setattr(category, field, value)
    await session.commit()
    await session.refresh(category)
    return category


__all__ = [
    "BUILTIN_CATEGORIES",
    "builtin_id",
    "create_category",
    "ensure_builtin_categories",
    "get_category",
    "list_categories",
    "update_category",
    "usable_category",
]
