import uuid
from datetime import date
import httpx
import pytest

from tests.conftest import TEST_ORG_ID, TEST_USER_ID

pytestmark = pytest.mark.asyncio
BASE = "/v1"


def if_match(record: dict) -> dict:
    return {"If-Match": f'"{record["version"]}"'}


async def ok(response: httpx.Response, status: int = 200) -> dict:
    assert response.status_code == status, f"Expected {status}, got {response.status_code}: {response.text}"
    return response.json()


async def test_register_asset_and_tag_generation(async_client: httpx.AsyncClient):
    """Test asset registration with atomic sequence tag generation."""
    owning_unit_id = uuid.uuid4()
    branch_id = uuid.uuid4()

    asset_data = {
        "name": 'MacBook Pro 16" M3 Max',
        "type_code": "laptop",
        "owner_unit_id": str(owning_unit_id),
        "location_branch_id": str(branch_id),
        "location_details": "Patna Office - 2nd Floor Dev Bay",
        "criticality": "high",
        "serial_no": "C02XYZ123456",
        "acquisition_cost": {"amount": 249000.0, "currency": "INR"},
        "attributes": {"ram_gb": 36, "storage_gb": 1000},
    }

    res = await ok(await async_client.post(f"{BASE}/assets", json=asset_data), 201)
    assert res["name"] == 'MacBook Pro 16" M3 Max'
    assert res["status"] == "in_stock"
    assert res["version"] == 1
    assert res["asset_tag"].startswith("LAP-")
    assert res["location_branch_id"] == str(branch_id)
    assert res["location_details"] == "Patna Office - 2nd Floor Dev Bay"
    assert res["acquisition_cost"]["amount"] == "249000.00"

    # Second asset gets next incremented sequence number
    res2 = await ok(await async_client.post(f"{BASE}/assets", json=asset_data), 201)
    assert res2["asset_tag"] != res["asset_tag"]


async def test_update_asset_concurrency(async_client: httpx.AsyncClient):
    """Test optimistic locking with ETag and If-Match on asset updates."""
    asset_data = {
        "name": 'Dell UltraSharp 27" 4K',
        "type_code": "monitor",
        "owner_unit_id": str(uuid.uuid4()),
    }
    asset = await ok(await async_client.post(f"{BASE}/assets", json=asset_data), 201)
    asset_id = asset["id"]

    # Update without If-Match should fail with 428
    no_etag_res = await async_client.patch(
        f"{BASE}/assets/{asset_id}",
        json={"name": 'Dell UltraSharp 27" USB-C Hub'},
    )
    assert no_etag_res.status_code == 428

    # Update with wrong version should fail with 412
    wrong_etag_res = await async_client.patch(
        f"{BASE}/assets/{asset_id}",
        headers={"If-Match": '"999"'},
        json={"name": 'Dell UltraSharp 27" USB-C Hub'},
    )
    assert wrong_etag_res.status_code == 412

    # Update with valid If-Match should succeed and increment version
    updated = await ok(
        await async_client.patch(
            f"{BASE}/assets/{asset_id}",
            headers=if_match(asset),
            json={"name": 'Dell UltraSharp 27" USB-C Hub'},
        ),
        200,
    )
    assert updated["name"] == 'Dell UltraSharp 27" USB-C Hub'
    assert updated["version"] == 2
