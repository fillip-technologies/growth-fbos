import uuid
import httpx
import pytest

from tests.conftest import TEST_ORG_ID

pytestmark = pytest.mark.asyncio
BASE = "/v1"


async def ok(response: httpx.Response, status: int = 200) -> dict:
    assert response.status_code == status, f"Expected {status}, got {response.status_code}: {response.text}"
    return response.json()


async def test_builtins_seeded(async_client: httpx.AsyncClient):
    """Verify built-in categories and types exist out of the box."""
    cats_res = await ok(await async_client.get(f"{BASE}/asset-categories"))
    cat_codes = {c["code"] for c in cats_res["data"]}
    assert {"hardware", "facility", "software", "credential"}.issubset(cat_codes)

    types_res = await ok(await async_client.get(f"{BASE}/asset-types"))
    type_codes = {t["code"] for t in types_res["data"]}
    assert {"laptop", "desktop", "monitor", "network_equipment", "saas_subscription"}.issubset(type_codes)


async def test_create_and_update_category(async_client: httpx.AsyncClient):
    """Test creating custom categories and nested sub-categories."""
    # Create top category
    cat_data = {
        "code": "vehicles",
        "name": "Fleet & Vehicles",
    }
    cat = await ok(await async_client.post(f"{BASE}/asset-categories", json=cat_data), 201)
    assert cat["code"] == "vehicles"
    assert cat["name"] == "Fleet & Vehicles"
    cat_id = cat["id"]

    # Duplicate code should fail with 409
    dup_res = await async_client.post(f"{BASE}/asset-categories", json=cat_data)
    assert dup_res.status_code == 409

    # Create sub-category
    subcat_data = {
        "code": "electric_cars",
        "name": "Electric Vehicles",
        "parent_id": cat_id,
    }
    subcat = await ok(await async_client.post(f"{BASE}/asset-categories", json=subcat_data), 201)
    assert subcat["parent_id"] == cat_id

    # Update category
    updated = await ok(
        await async_client.patch(f"{BASE}/asset-categories/{cat_id}", json={"name": "Company Fleet"}), 200
    )
    assert updated["name"] == "Company Fleet"


async def test_create_custom_asset_type(async_client: httpx.AsyncClient):
    """Test adding custom asset type to a category."""
    cats_res = await ok(await async_client.get(f"{BASE}/asset-categories"))
    hw_cat = next(c for c in cats_res["data"] if c["code"] == "hardware")

    type_data = {
        "category_id": hw_cat["id"],
        "code": "drone",
        "name": "Aerial Drone",
        "family": "hardware",
        "tracks_expiry": False,
        "single_custodian": True,
        "attribute_schema": {
            "flight_time_mins": {"type": "integer"},
            "camera_resolution": {"type": "string"},
        },
    }
    t = await ok(await async_client.post(f"{BASE}/asset-types", json=type_data), 201)
    assert t["code"] == "drone"
    assert t["attribute_schema"]["flight_time_mins"] == {"type": "integer"}

    # Fetch single type
    fetched = await ok(await async_client.get(f"{BASE}/asset-types/{t['id']}"))
    assert fetched["name"] == "Aerial Drone"


async def test_vendor_and_vendor_accounts(async_client: httpx.AsyncClient):
    """Test vendor and vendor account creation and listing."""
    vendor_data = {
        "name": "Apple India Private Limited",
        "vendor_type": "oem",
        "gstin": "29AAAAA0000A1Z5",
    }
    vendor = await ok(await async_client.post(f"{BASE}/vendors", json=vendor_data), 201)
    assert vendor["name"] == "Apple India Private Limited"
    assert vendor["code"].startswith("VND-")
    vendor_id = vendor["id"]

    # Create account with vendor
    acc_data = {
        "vendor_id": vendor_id,
        "account_identifier": "APPLE-CORP-PATNA-001",
        "billing_email": "accounts@filliptech.com",
    }
    account = await ok(await async_client.post(f"{BASE}/vendor-accounts", json=acc_data), 201)
    assert account["account_identifier"] == "APPLE-CORP-PATNA-001"
    assert account["vendor_id"] == vendor_id

    # List accounts for vendor
    acc_list = await ok(await async_client.get(f"{BASE}/vendor-accounts?vendor_id={vendor_id}"))
    assert len(acc_list["data"]) == 1
    assert acc_list["data"][0]["id"] == account["id"]


async def test_new_org_auto_seeds_builtins(async_client: httpx.AsyncClient):
    """Verify that a brand new organization calling categories/types is auto-seeded."""
    brand_new_org = uuid.uuid4()
    headers = {"X-Organization-Id": str(brand_new_org)}
    res = await ok(await async_client.get(f"{BASE}/asset-categories", headers=headers))
    codes = {c["code"] for c in res["data"]}
    assert {"hardware", "facility", "software", "credential"}.issubset(codes)

    types_res = await ok(await async_client.get(f"{BASE}/asset-types", headers=headers))
    type_codes = {t["code"] for t in types_res["data"]}
    assert {"laptop", "desktop", "monitor", "network_equipment", "saas_subscription"}.issubset(type_codes)

