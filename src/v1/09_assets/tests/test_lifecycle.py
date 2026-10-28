import uuid
from datetime import date, timedelta
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


async def test_maintenance_lifecycle(async_client: httpx.AsyncClient):
    """Test scheduling maintenance, state transition to in_maintenance, completion, and cost logging."""
    # 1. Register asset
    asset = await ok(
        await async_client.post(
            f"{BASE}/assets",
            json={
                "name": "Cisco Catalyst 9300 Switch",
                "type_code": "network_equipment",
                "owner_unit_id": str(uuid.uuid4()),
                "acquisition_cost": {"amount": 150000.0, "currency": "INR"},
            },
        ),
        201,
    )
    asset_id = asset["id"]
    assert asset["status"] == "in_stock"

    # 2. Schedule maintenance / repair
    maint_payload = {
        "maintenance_type": "repair",
        "scheduled_on": date.today().isoformat(),
        "notes": "Port 12 faulty, power supply inspection",
    }
    maint = await ok(
        await async_client.post(f"{BASE}/assets/{asset_id}/maintenance", json=maint_payload),
        201,
    )
    record_id = maint["id"]
    assert maint["maintenance_type"] == "repair"

    # Asset status must now be in_maintenance
    asset_in_maint = await ok(await async_client.get(f"{BASE}/assets/{asset_id}"))
    assert asset_in_maint["status"] == "in_maintenance"

    # Attempting to assign while in_maintenance should fail with 409
    assign_res = await async_client.post(
        f"{BASE}/assets/{asset_id}/assignments",
        headers=if_match(asset_in_maint),
        json={"assignee_type": "identity.user", "assignee_id": str(uuid.uuid4())},
    )
    assert assign_res.status_code == 409

    # 3. Complete maintenance with repair cost
    complete_payload = {
        "completed_on": date.today().isoformat(),
        "cost": {"amount": 8500.0, "currency": "INR"},
        "notes": "Power supply unit replaced under vendor AMC",
    }
    completed = await ok(
        await async_client.patch(f"{BASE}/assets/{asset_id}/maintenance/{record_id}", json=complete_payload),
        200,
    )
    assert completed["completed_on"] == date.today().isoformat()
    assert completed["cost"]["amount"] == "8500.00"

    # Asset status must transition back to in_stock
    asset_restored = await ok(await async_client.get(f"{BASE}/assets/{asset_id}"))
    assert asset_restored["status"] == "in_stock"

    # 4. Check TCO costs: Acquisition (150,000) + Maintenance (8,500) = 158,500
    costs_res = await ok(await async_client.get(f"{BASE}/assets/{asset_id}/costs"))
    entries, summary = costs_res
    assert summary["total_cost"]["amount"] == "158500.00"
    assert summary["costs_by_type"]["maintenance"] == 8500.0


async def test_warranty_renewal_lifecycle(async_client: httpx.AsyncClient):
    """Test logging renewal alert and approving it to extend expiry date."""
    initial_expiry = date.today() + timedelta(days=60)
    asset = await ok(
        await async_client.post(
            f"{BASE}/assets",
            json={
                "name": "Figma Enterprise Organization Plan",
                "type_code": "saas_subscription",
                "owner_unit_id": str(uuid.uuid4()),
                "expires_at": initial_expiry.isoformat(),
            },
        ),
        201,
    )
    asset_id = asset["id"]

    # 1. Log renewal need
    renewal_payload = {
        "due_on": initial_expiry.isoformat(),
        "notes": "Annual contract renewal for 50 design seats",
    }
    renewal = await ok(
        await async_client.post(f"{BASE}/assets/{asset_id}/renewals", json=renewal_payload),
        201,
    )
    renewal_id = renewal["id"]
    assert renewal["status"] == "pending"

    # 2. Approve renewal with new expiry date extended by 1 year
    new_expiry = initial_expiry + timedelta(days=365)
    decision_payload = {
        "status": "approved",
        "new_expires_at": new_expiry.isoformat(),
    }
    decided = await ok(
        await async_client.post(f"{BASE}/assets/{asset_id}/renewals/{renewal_id}/decide", json=decision_payload),
        200,
    )
    assert decided["status"] == "approved"
    assert decided["new_expires_at"] == new_expiry.isoformat()

    # Asset expires_at must be updated
    updated_asset = await ok(await async_client.get(f"{BASE}/assets/{asset_id}"))
    assert updated_asset["expires_at"] == new_expiry.isoformat()


async def test_decommissioning_and_disposal_lifecycle(async_client: httpx.AsyncClient):
    """Test decommissioning, data wipe verification, and disposal."""
    asset = await ok(
        await async_client.post(
            f"{BASE}/assets",
            json={
                "name": "Legacy Core i5 Desktop PC",
                "type_code": "desktop",
                "owner_unit_id": str(uuid.uuid4()),
            },
        ),
        201,
    )
    asset_id = asset["id"]

    # 1. If asset is assigned (in_use), disposal must be rejected
    assigned = await ok(
        await async_client.post(
            f"{BASE}/assets/{asset_id}/assignments",
            headers=if_match(asset),
            json={"assignee_type": "identity.user", "assignee_id": str(uuid.uuid4())},
        ),
        201,
    )

    disposal_payload = {
        "method": "sold",
        "disposed_on": date.today().isoformat(),
        "value_realised": {"amount": 12000.0, "currency": "INR"},
        "data_wiped": True,
    }
    rej = await async_client.post(
        f"{BASE}/assets/{asset_id}/dispose", headers=if_match(assigned), json=disposal_payload
    )
    assert rej.status_code == 409

    # 2. Return asset first
    returned = await ok(
        await async_client.post(
            f"{BASE}/assets/{asset_id}/return",
            headers=if_match(assigned),
            json={"condition_in": "Retired from service"},
        ),
        200,
    )
    assert returned["status"] == "in_stock"

    # 3. Now dispose
    disposed = await ok(
        await async_client.post(
            f"{BASE}/assets/{asset_id}/dispose",
            headers=if_match(returned),
            json=disposal_payload,
        ),
        201,
    )
    assert disposed["method"] == "sold"
    assert disposed["data_wiped"] is True
    assert disposed["value_realised"]["amount"] == "12000.00"

    # Asset status must be disposed
    asset_final = await ok(await async_client.get(f"{BASE}/assets/{asset_id}"))
    assert asset_final["status"] == "disposed"


async def test_asset_relationships_bundling(async_client: httpx.AsyncClient):
    """Test linking parent-child assets (e.g. Laptop bundle with Monitor)."""
    laptop = await ok(
        await async_client.post(
            f"{BASE}/assets",
            json={"name": "Developer MacBook", "type_code": "laptop", "owner_unit_id": str(uuid.uuid4())},
        ),
        201,
    )
    monitor = await ok(
        await async_client.post(
            f"{BASE}/assets",
            json={"name": "Dell 4K Monitor", "type_code": "monitor", "owner_unit_id": str(uuid.uuid4())},
        ),
        201,
    )

    rel_payload = {
        "relation_type": "parent_of",
        "related_asset_id": monitor["id"],
    }
    rel = await ok(
        await async_client.post(f"{BASE}/assets/{laptop['id']}/relationships", json=rel_payload),
        201,
    )
    assert rel["relation_type"] == "parent_of"
    assert rel["related_asset_id"] == monitor["id"]

    rels = await ok(await async_client.get(f"{BASE}/assets/{laptop['id']}/relationships"))
    assert len(rels) == 1
    assert rels[0]["related_asset_id"] == monitor["id"]
