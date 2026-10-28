"""
Default asset categories and types seeded deterministically.

Categories and types are seeded per organization with stable UUIDs (uuid5),
so re-running ensure_builtin_types is idempotent.
"""

import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from database.insert_ignore import insert_ignore
from models.asset import AssetCategory, AssetType

_BUILTIN_NAMESPACE = uuid.UUID("7a2e4b10-6c9f-4d3b-8e12-05af22f8c009")

BUILTIN_CATEGORIES = [
    {"code": "hardware", "name": "IT & Hardware"},
    {"code": "facility", "name": "Office Infrastructure & Facilities"},
    {"code": "software", "name": "Software & SaaS Subscriptions"},
    {"code": "credential", "name": "Security & Credentials"},
]

BUILTIN_TYPES = [
    {
        "category_code": "hardware",
        "code": "laptop",
        "name": "Laptop Workstation",
        "family": "hardware",
        "tracks_expiry": False,
        "single_custodian": True,
        "attribute_schema": {
            "processor": {"type": "string"},
            "ram_gb": {"type": "integer"},
            "storage_gb": {"type": "integer"},
            "os": {"type": "string"},
        },
    },
    {
        "category_code": "hardware",
        "code": "desktop",
        "name": "Desktop PC",
        "family": "hardware",
        "tracks_expiry": False,
        "single_custodian": True,
        "attribute_schema": {
            "processor": {"type": "string"},
            "ram_gb": {"type": "integer"},
            "storage_gb": {"type": "integer"},
        },
    },
    {
        "category_code": "hardware",
        "code": "monitor",
        "name": "External Monitor",
        "family": "hardware",
        "tracks_expiry": False,
        "single_custodian": False,
        "attribute_schema": {
            "screen_size_inches": {"type": "number"},
            "resolution": {"type": "string"},
        },
    },
    {
        "category_code": "hardware",
        "code": "mobile_device",
        "name": "Mobile Phone / Tablet",
        "family": "hardware",
        "tracks_expiry": False,
        "single_custodian": True,
        "attribute_schema": {
            "imei": {"type": "string"},
            "model_name": {"type": "string"},
        },
    },
    {
        "category_code": "facility",
        "code": "network_equipment",
        "name": "Network Router / Switch / AP",
        "family": "facility",
        "tracks_expiry": False,
        "single_custodian": False,
        "attribute_schema": {
            "mac_address": {"type": "string"},
            "port_count": {"type": "integer"},
        },
    },
    {
        "category_code": "facility",
        "code": "office_equipment",
        "name": "Office Equipment & Appliances",
        "family": "facility",
        "tracks_expiry": False,
        "single_custodian": False,
        "attribute_schema": {
            "make": {"type": "string"},
            "location_room": {"type": "string"},
        },
    },
    {
        "category_code": "software",
        "code": "saas_subscription",
        "name": "Cloud SaaS Subscription",
        "family": "software",
        "tracks_expiry": True,
        "single_custodian": False,
        "attribute_schema": {
            "plan_tier": {"type": "string"},
            "billing_frequency": {"type": "string"},
        },
    },
    {
        "category_code": "software",
        "code": "software_license",
        "name": "Software License",
        "family": "software",
        "tracks_expiry": True,
        "single_custodian": False,
        "attribute_schema": {
            "seats": {"type": "integer"},
            "license_type": {"type": "string"},
        },
    },
    {
        "category_code": "credential",
        "code": "api_credential",
        "name": "API Key / Service Account",
        "family": "credential",
        "tracks_expiry": True,
        "single_custodian": True,
        "attribute_schema": {
            "service_name": {"type": "string"},
            "environment": {"type": "string"},
        },
    },
]


async def ensure_builtin_types(session: AsyncSession, organization_id: uuid.UUID) -> None:
    """Ensure baseline categories and types exist for an organization."""
    category_ids: dict[str, uuid.UUID] = {}

    for cat in BUILTIN_CATEGORIES:
        cat_id = uuid.uuid5(_BUILTIN_NAMESPACE, f"{organization_id}:cat:{cat['code']}")
        category_ids[cat["code"]] = cat_id
        await session.execute(
            insert_ignore(AssetCategory).values(
                id=cat_id,
                organization_id=organization_id,
                code=cat["code"],
                name=cat["name"],
                parent_id=None,
            )
        )

    for item in BUILTIN_TYPES:
        cat_id = category_ids.get(item["category_code"])
        if not cat_id:
            continue
        type_id = uuid.uuid5(_BUILTIN_NAMESPACE, f"{organization_id}:type:{item['code']}")
        await session.execute(
            insert_ignore(AssetType).values(
                id=type_id,
                category_id=cat_id,
                code=item["code"],
                name=item["name"],
                family=item["family"],
                tracks_expiry=item["tracks_expiry"],
                single_custodian=item["single_custodian"],
                attribute_schema=item["attribute_schema"],
            )
        )
    await session.flush()
