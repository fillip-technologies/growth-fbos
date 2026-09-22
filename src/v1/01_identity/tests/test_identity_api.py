import uuid
import pytest
import httpx
from tests.conftest import TEST_ORG_ID, TEST_USER_ID


@pytest.mark.asyncio
async def test_health_check(async_client: httpx.AsyncClient):
    response = await async_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "identity"}


@pytest.mark.asyncio
async def test_jwks_endpoints(async_client: httpx.AsyncClient):
    res1 = await async_client.get("/.well-known/jwks.json")
    assert res1.status_code == 200
    assert "keys" in res1.json()

    res2 = await async_client.get("/api/identity/v1/auth/.well-known/jwks.json")
    assert res2.status_code == 200
    assert "keys" in res2.json()


@pytest.mark.asyncio
async def test_users_crud(async_client: httpx.AsyncClient):
    # 1. Invite user
    invite_data = {
        "email": "sarah.connor@example.com",
        "name": "Sarah Connor",
        "employee_code": "EMP-001",
        "user_type": "employee",
    }
    invite_res = await async_client.post("/api/identity/v1/users", json=invite_data)
    assert invite_res.status_code == 201
    user = invite_res.json()
    assert user["email"] == "sarah.connor@example.com"
    assert user["status"] == "invited"
    user_id = user["id"]

    # 2. List users
    list_res = await async_client.get("/api/identity/v1/users")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert len(list_data["data"]) >= 2

    # 3. Get user
    get_res = await async_client.get(f"/api/identity/v1/users/{user_id}")
    assert get_res.status_code == 200
    etag = get_res.headers.get("ETag")
    assert etag is not None

    # 4. Update user with ETag
    update_res = await async_client.patch(
        f"/api/identity/v1/users/{user_id}",
        json={"name": "Sarah Connor J."},
        headers={"If-Match": etag},
    )
    assert update_res.status_code == 200
    updated_user = update_res.json()
    assert updated_user["name"] == "Sarah Connor J."
    new_etag = update_res.headers.get("ETag")

    # 5. Deactivate user with ETag
    deact_res = await async_client.post(
        f"/api/identity/v1/users/{user_id}/deactivate",
        json={"reason": "Left company"},
        headers={"If-Match": new_etag},
    )
    assert deact_res.status_code == 200
    assert deact_res.json()["status"] == "deactivated"


@pytest.mark.asyncio
async def test_org_units_hierarchy_and_move(async_client: httpx.AsyncClient):
    # 1. Create company (root)
    company_res = await async_client.post(
        "/api/identity/v1/org-units",
        json={"code": "CORP", "name": "Global Corp", "unit_type": "company"},
    )
    assert company_res.status_code == 201
    company = company_res.json()
    assert company["path"] == f"/{company['id']}/"

    # 2. Create department under company
    dept_res = await async_client.post(
        "/api/identity/v1/org-units",
        json={
            "code": "ENG",
            "name": "Engineering",
            "unit_type": "department",
            "parent_id": company["id"],
        },
    )
    assert dept_res.status_code == 201
    dept = dept_res.json()
    assert dept["path"] == f"/{company['id']}/{dept['id']}/"

    # 3. Create team under department
    team_res = await async_client.post(
        "/api/identity/v1/org-units",
        json={
            "code": "WEB",
            "name": "Web Team",
            "unit_type": "team",
            "parent_id": dept["id"],
        },
    )
    assert team_res.status_code == 201
    team = team_res.json()

    # 4. Try invalid hierarchy: team directly under company
    invalid_res = await async_client.post(
        "/api/identity/v1/org-units",
        json={
            "code": "BAD-TEAM",
            "name": "Bad Team",
            "unit_type": "team",
            "parent_id": company["id"],
        },
    )
    assert invalid_res.status_code == 422

    # 5. Create another department for move test
    dept2_res = await async_client.post(
        "/api/identity/v1/org-units",
        json={
            "code": "PROD",
            "name": "Product",
            "unit_type": "department",
            "parent_id": company["id"],
        },
    )
    assert dept2_res.status_code == 201
    dept2 = dept2_res.json()

    # 6. Move team from ENG to PROD
    team_get = await async_client.get(f"/api/identity/v1/org-units/{team['id']}")
    team_etag = team_get.headers.get("ETag")

    move_res = await async_client.post(
        f"/api/identity/v1/org-units/{team['id']}/move",
        json={"new_parent_id": dept2["id"], "reason": "Restructuring"},
        headers={"If-Match": team_etag},
    )
    assert move_res.status_code == 200
    moved_team = move_res.json()
    assert moved_team["parent_id"] == dept2["id"]
    assert moved_team["path"] == f"/{company['id']}/{dept2['id']}/{team['id']}/"


@pytest.mark.asyncio
async def test_roles_and_permissions(async_client: httpx.AsyncClient):
    # 1. List permissions
    perms_res = await async_client.get("/api/identity/v1/permissions")
    assert perms_res.status_code == 200

    # 2. Create custom role
    role_res = await async_client.post(
        "/api/identity/v1/roles",
        json={
            "code": "qa_lead",
            "name": "QA Lead",
            "permissions": ["task.task.read", "task.task.assign"],
        },
    )
    assert role_res.status_code == 201
    role = role_res.json()
    assert role["code"] == "qa_lead"
    assert "task.task.read" in role["permissions"]

    # 3. Replace role permissions with ETag
    role_id = role["id"]
    put_res = await async_client.put(
        f"/api/identity/v1/roles/{role_id}/permissions",
        json={"permissions": ["task.task.read", "task.task.update"]},
        headers={"If-Match": '"1"'},
    )
    assert put_res.status_code == 200
    assert "task.task.update" in put_res.json()["permissions"]

    # 4. Create role assignment
    assign_res = await async_client.post(
        "/api/identity/v1/role-assignments",
        json={
            "user_id": str(TEST_USER_ID),
            "role_id": role_id,
            "reason": "Test Assignment",
        },
    )
    assert assign_res.status_code == 201
    assignment = assign_res.json()
    assignment_id = assignment["id"]

    # 5. List role assignments
    list_assign = await async_client.get("/api/identity/v1/role-assignments")
    assert list_assign.status_code == 200

    # 6. Internal effective grants check
    grants_res = await async_client.get(f"/api/identity/v1/internal/authz/grants?user_id={TEST_USER_ID}")
    assert grants_res.status_code == 200
    grants_data = grants_res.json()
    perm_names = [g["permission"] for g in grants_data["grants"]]
    assert "task.task.read" in perm_names

    # 7. Revoke role assignment
    revoke_res = await async_client.delete(f"/api/identity/v1/role-assignments/{assignment_id}?reason=Removed")
    assert revoke_res.status_code == 204


@pytest.mark.asyncio
async def test_calendars_and_holidays(async_client: httpx.AsyncClient):
    # 1. Create calendar
    cal_res = await async_client.post(
        "/api/identity/v1/calendars",
        json={
            "name": "Standard Office Hours",
            "timezone": "UTC",
            "weekly_hours": {
                "mon": [["09:00", "17:00"]],
                "tue": [["09:00", "17:00"]],
            },
        },
    )
    assert cal_res.status_code == 201
    cal = cal_res.json()
    cal_id = cal["id"]

    # 2. List calendars
    list_res = await async_client.get("/api/identity/v1/calendars")
    assert list_res.status_code == 200

    # 3. Replace holidays
    holidays_res = await async_client.put(
        f"/api/identity/v1/calendars/{cal_id}/holidays",
        json={
            "holidays": [
                {"date": "2026-12-25", "name": "Christmas Day", "is_half_day": False},
                {"date": "2026-12-31", "name": "New Year's Eve", "is_half_day": True},
            ]
        },
        headers={"If-Match": '"1"'},
    )
    assert holidays_res.status_code == 200
    assert len(holidays_res.json()["holidays"]) == 2


@pytest.mark.asyncio
async def test_verticals_and_custom_fields(async_client: httpx.AsyncClient):
    # 1. List object types
    obj_types_res = await async_client.get("/api/identity/v1/object-types")
    assert obj_types_res.status_code == 200
    types = obj_types_res.json()["data"]
    assert len(types) > 0

    # 2. Create custom field definition draft
    fd_res = await async_client.post(
        "/api/identity/v1/field-definitions",
        json={
            "object_type": "work.work_unit",
            "json_schema": {
                "type": "object",
                "properties": {"tier": {"type": "string", "enum": ["free", "pro"]}},
            },
        },
    )
    assert fd_res.status_code == 201
    fd = fd_res.json()
    assert fd["status"] == "draft"
    fd_id = fd["id"]

    # 3. Publish field definition
    pub_res = await async_client.post(
        f"/api/identity/v1/field-definitions/{fd_id}/publish",
        headers={"If-Match": '"1"'},
    )
    assert pub_res.status_code == 200
    assert pub_res.json()["status"] == "published"


@pytest.mark.asyncio
async def test_auth_extended_flows(async_client: httpx.AsyncClient):
    # 1. Forgot password
    forgot_res = await async_client.post(
        "/api/identity/v1/auth/password/forgot",
        json={"email": "test@example.com", "organization_code": "TEST"},
    )
    assert forgot_res.status_code == 202

    # 2. MFA enroll
    enroll_res = await async_client.post("/api/identity/v1/auth/mfa/enroll")
    assert enroll_res.status_code == 200
    assert "otpauth_uri" in enroll_res.json()

    # 3. Confirm MFA enrollment
    confirm_res = await async_client.post(
        "/api/identity/v1/auth/mfa/enroll/confirm",
        json={"code": "123456"},
    )
    assert confirm_res.status_code == 200
    assert "codes" in confirm_res.json()

    # 4. Get signed-in user /me
    me_res = await async_client.get("/api/identity/v1/auth/me")
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_invitation_and_reset_password_flow(async_client: httpx.AsyncClient, db_session):
    # 1. Invite a user
    invite_res = await async_client.post(
        "/api/identity/v1/users",
        json={"email": "new.member@example.com", "name": "New Member", "user_type": "employee"},
    )
    assert invite_res.status_code == 201
    user_id = uuid.UUID(invite_res.json()["id"])

    # 2. Get invitation token from DB
    from models.auth import UserCredential
    cred = await db_session.get(UserCredential, user_id)
    assert cred is not None
    inv_token = cred.invitation_token
    assert inv_token is not None

    # 3. Accept invitation
    accept_res = await async_client.post(
        "/api/identity/v1/auth/invitations/accept",
        json={"token": inv_token, "password": "SecurePassword123!"},
    )
    assert accept_res.status_code == 204

    # 4. Forgot password to trigger reset token
    forgot_res = await async_client.post(
        "/api/identity/v1/auth/password/forgot",
        json={"email": "new.member@example.com"},
    )
    assert forgot_res.status_code == 202

    await db_session.refresh(cred)
    reset_token = cred.reset_token
    assert reset_token is not None

    # 5. Reset password
    reset_res = await async_client.post(
        "/api/identity/v1/auth/password/reset",
        json={"token": reset_token, "new_password": "EvenMoreSecurePassword999!"},
    )
    assert reset_res.status_code == 204


@pytest.mark.asyncio
async def test_oauth_and_vertical_packs(async_client: httpx.AsyncClient, db_session):
    # 1. Seed an active ApiClient
    from models.auth import ApiClient
    from models.vertical import Vertical
    client_record = ApiClient(
        id=uuid.uuid4(),
        organization_id=TEST_ORG_ID,
        client_id="cli_test_integration",
        client_secret_hash=None,  # No secret required for test client
        name="Test Integration",
        allowed_scopes="billing.invoice.read",
        status="active",
    )
    vert = Vertical(
        id=uuid.uuid4(),
        name="IT Services",
        code="it-services",
        status="active",
    )
    db_session.add(client_record)
    db_session.add(vert)
    await db_session.commit()

    # 2. Request OAuth client credentials token
    oauth_res = await async_client.post(
        "/api/identity/v1/auth/oauth/token",
        json={
            "grant_type": "client_credentials",
            "client_id": "cli_test_integration",
            "client_secret": "any_secret",
            "scope": "billing.invoice.read",
        },
    )
    assert oauth_res.status_code == 200
    assert "access_token" in oauth_res.json()

    # 3. Create vertical pack
    pack_res = await async_client.post(
        "/api/identity/v1/vertical-packs",
        json={
            "vertical_id": str(vert.id),
            "pack_code": "it-starter",
            "version_no": 1,
            "manifest": {"work_templates": ["standard"]},
        },
    )
    assert pack_res.status_code == 201
    pack = pack_res.json()
    pack_id = pack["id"]

    # 4. Activate vertical pack
    act_res = await async_client.post(f"/api/identity/v1/vertical-packs/{pack_id}/activate")
    assert act_res.status_code == 202
    assert act_res.json()["status"] == "active"

