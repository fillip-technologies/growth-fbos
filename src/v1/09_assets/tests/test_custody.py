import uuid
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


async def test_employee_custody_and_transfer_lifecycle(async_client: httpx.AsyncClient):
    """Test assigning an asset to an employee, direct transfer to another employee, and return."""
    # 1. Register asset
    asset = await ok(
        await async_client.post(
            f"{BASE}/assets",
            json={
                "name": "ThinkPad T14 Gen 4",
                "type_code": "laptop",
                "owner_unit_id": str(uuid.uuid4()),
            },
        ),
        201,
    )
    asset_id = asset["id"]
    assert asset["status"] == "in_stock"

    employee_1 = uuid.uuid4()
    employee_2 = uuid.uuid4()

    # 2. Assign to Employee 1
    assign_payload = {
        "assignee_type": "identity.user",
        "assignee_id": str(employee_1),
        "condition_out": "Brand new, sealed box",
        "note": "Issued for Patna Dev Team",
    }
    assigned = await ok(
        await async_client.post(f"{BASE}/assets/{asset_id}/assignments", headers=if_match(asset), json=assign_payload),
        201,
    )
    assert assigned["status"] == "in_use"
    assert assigned["custody"]["type"] == "identity.user"
    assert assigned["custody"]["id"] == str(employee_1)
    assert assigned["custodian"]["id"] == str(employee_1)
    assert assigned["version"] == 2

    # Double assignment should fail with 409
    dup = await async_client.post(
        f"{BASE}/assets/{asset_id}/assignments", headers=if_match(assigned), json=assign_payload
    )
    assert dup.status_code == 409

    # 3. Direct transfer from Employee 1 to Employee 2
    transfer_payload = {
        "to_assignee_type": "identity.user",
        "to_assignee_id": str(employee_2),
        "condition_transfer": "Good, minor scratch on lid",
        "note": "Handover on project rotation",
    }
    transferred = await ok(
        await async_client.post(f"{BASE}/assets/{asset_id}/transfer", headers=if_match(assigned), json=transfer_payload),
        200,
    )
    assert transferred["status"] == "in_use"
    assert transferred["custody"]["id"] == str(employee_2)
    assert transferred["custodian"]["id"] == str(employee_2)
    assert transferred["version"] == 3

    # Check employee clearance: Employee 2 should have it, Employee 1 should not
    emp2_clearance = await ok(await async_client.get(f"{BASE}/assets/clearance/employee/{employee_2}"))
    assert len(emp2_clearance) == 1
    assert emp2_clearance[0]["id"] == asset_id

    emp1_clearance = await ok(await async_client.get(f"{BASE}/assets/clearance/employee/{employee_1}"))
    assert len(emp1_clearance) == 0

    # 4. Return asset back to stock
    returned = await ok(
        await async_client.post(
            f"{BASE}/assets/{asset_id}/return",
            headers=if_match(transferred),
            json={"condition_in": "Clean, reset to factory settings"},
        ),
        200,
    )
    assert returned["status"] == "in_stock"
    assert returned["custody"] is None
    assert returned["custodian"] is None
    assert returned["version"] == 4

    # 5. Check chain of custody history
    history = await ok(await async_client.get(f"{BASE}/assets/{asset_id}/history"))
    assert len(history) == 2
    # Newest assignment first:
    assert history[0]["assignee"]["id"] == str(employee_2)
    assert history[0]["returned_at"] is not None
    assert history[0]["condition_in"] == "Clean, reset to factory settings"

    assert history[1]["assignee"]["id"] == str(employee_1)
    assert history[1]["condition_in"] == "Good, minor scratch on lid"


async def test_polymorphic_department_and_project_custody(async_client: httpx.AsyncClient):
    """Test assigning assets to Department Pools and Project allocations."""
    # 1. Department Shared Pool (e.g. QA testing devices)
    dept_id = uuid.uuid4()
    caretaker_id = uuid.uuid4()

    qa_phone = await ok(
        await async_client.post(
            f"{BASE}/assets",
            json={
                "name": "Google Pixel 8 (QA Lab Device)",
                "type_code": "mobile_device",
                "owner_unit_id": str(dept_id),
            },
        ),
        201,
    )

    dept_assignment = {
        "assignee_type": "identity.org_unit",
        "assignee_id": str(dept_id),
        "custodian_user_id": str(caretaker_id),
        "condition_out": "Good, screen protector on",
        "note": "QA Pool Phone",
    }
    assigned_dept = await ok(
        await async_client.post(
            f"{BASE}/assets/{qa_phone['id']}/assignments", headers=if_match(qa_phone), json=dept_assignment
        ),
        201,
    )
    assert assigned_dept["status"] == "in_use"
    assert assigned_dept["custody"]["type"] == "identity.org_unit"
    assert assigned_dept["custody"]["id"] == str(dept_id)
    assert assigned_dept["custodian"]["id"] == str(caretaker_id)

    # 2. Project Allocation (Dedicated staging server)
    project_id = uuid.uuid4()
    pm_id = uuid.uuid4()

    server = await ok(
        await async_client.post(
            f"{BASE}/assets",
            json={
                "name": "Dell PowerEdge R750 (Staging Server)",
                "type_code": "network_equipment",
                "owner_unit_id": str(dept_id),
            },
        ),
        201,
    )

    project_assignment = {
        "assignee_type": "delivery.work_unit",
        "assignee_id": str(project_id),
        "custodian_user_id": str(pm_id),
        "condition_out": "Mounted in Rack 4",
        "note": "Allocated for Patna ERP delivery",
    }
    assigned_project = await ok(
        await async_client.post(
            f"{BASE}/assets/{server['id']}/assignments", headers=if_match(server), json=project_assignment
        ),
        201,
    )
    assert assigned_project["status"] == "in_use"
    assert assigned_project["custody"]["type"] == "delivery.work_unit"
    assert assigned_project["custody"]["id"] == str(project_id)
    assert assigned_project["custodian"]["id"] == str(pm_id)
