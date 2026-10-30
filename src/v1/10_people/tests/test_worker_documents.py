"""Employee ID numbers, documents, bank accounts and the onboarding checklist."""
import uuid

import pytest
from sqlalchemy import select

from config import settings
from dependencies import get_actor
from main import app
from models.worker import SensitiveAccessLog, WorkerDocument
from services.identity_client import Actor
from tests.conftest import TEST_ORG_ID

VALID_AADHAAR = "234123412346"  # passes the Verhoeff check


async def make_worker(client, email="doc.worker@company.com") -> str:
    res = await client.post(
        "/v1/workers",
        json={
            "first_name": "Doc", "last_name": "Worker", "work_email": email,
            "designation": "Engineer", "date_of_joining": "2024-01-01",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def item(onboarding: dict, code: str) -> dict:
    return next(i for i in onboarding["items"] if i["code"] == code)


def act_as(*codes: str) -> None:
    app.dependency_overrides[get_actor] = lambda: Actor(
        user_id=uuid.uuid4(), organization_id=TEST_ORG_ID, user_type="employee", name="Limited",
        permissions=frozenset(codes),
    )


@pytest.mark.asyncio
async def test_pan_is_validated_normalized_and_stored_encrypted(async_client, db_session):
    worker_id = await make_worker(async_client)
    bad = await async_client.put(f"/v1/workers/{worker_id}/documents/pan", json={"document_number": "ABC123"})
    assert bad.status_code == 422

    res = await async_client.put(f"/v1/workers/{worker_id}/documents/pan", json={"document_number": " abcde 1234f "})
    assert res.status_code == 200, res.text
    pan = item(res.json(), "pan")
    assert pan["status"] == "uploaded" and pan["has_number"] is True
    assert pan["number_masked"] == "•••• 234F"

    stored = (await db_session.execute(select(WorkerDocument))).scalar_one()
    assert "ABCDE1234F" not in (stored.number_encrypted or "")  # never in clear
    assert stored.number_last4 == "234F"


@pytest.mark.asyncio
async def test_aadhaar_needs_a_valid_check_digit(async_client):
    worker_id = await make_worker(async_client)
    wrong = await async_client.put(f"/v1/workers/{worker_id}/documents/aadhaar", json={"document_number": "234123412345"})
    assert wrong.status_code == 422
    short = await async_client.put(f"/v1/workers/{worker_id}/documents/aadhaar", json={"document_number": "1234"})
    assert short.status_code == 422
    ok = await async_client.put(f"/v1/workers/{worker_id}/documents/aadhaar", json={"document_number": "2341 2341 2346"})
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_unknown_types_and_misplaced_fields_are_refused(async_client):
    worker_id = await make_worker(async_client)
    assert (await async_client.put(f"/v1/workers/{worker_id}/documents/selfie", json={})).status_code == 422
    # A photo has no number, and a PAN does not expire.
    assert (await async_client.put(f"/v1/workers/{worker_id}/documents/photo", json={"document_number": "123"})).status_code == 422
    assert (await async_client.put(f"/v1/workers/{worker_id}/documents/pan", json={"expires_on": "2030-01-01"})).status_code == 422
    passport = await async_client.put(
        f"/v1/workers/{worker_id}/documents/passport",
        json={"document_number": "A1234567", "issued_on": "2020-01-01", "expires_on": "2030-01-01"},
    )
    assert passport.status_code == 200, passport.text


@pytest.mark.asyncio
async def test_verify_reject_and_changes_reset_verification(async_client):
    worker_id = await make_worker(async_client)
    base = f"/v1/workers/{worker_id}/documents"
    # Nothing to verify yet
    assert (await async_client.post(f"{base}/pan/verify")).status_code == 404

    await async_client.put(f"{base}/pan", json={"document_number": "ABCDE1234F"})
    verified = (await async_client.post(f"{base}/pan/verify")).json()
    assert item(verified, "pan")["status"] == "verified"
    assert (await async_client.post(f"{base}/pan/verify")).status_code == 409  # already verified

    # Changing the number sends it back for verification
    changed = (await async_client.put(f"{base}/pan", json={"document_number": "ABCDE1234G"})).json()
    assert item(changed, "pan")["status"] == "uploaded"

    rejected = (await async_client.post(f"{base}/pan/reject", json={"reason": "Blurry scan"})).json()
    assert item(rejected, "pan")["status"] == "rejected"
    assert item(rejected, "pan")["rejection_reason"] == "Blurry scan"

    # A file-only document needs its file before it can be verified
    await async_client.put(f"{base}/nda", json={"name_on_document": "Doc Worker"})
    assert (await async_client.post(f"{base}/nda/verify")).status_code == 409
    await async_client.put(f"{base}/nda", json={"document_id": str(uuid.uuid4()), "file_name": "nda.pdf"})
    assert item((await async_client.post(f"{base}/nda/verify")).json(), "nda")["status"] == "verified"


@pytest.mark.asyncio
async def test_reveal_returns_the_number_and_is_logged(async_client, db_session):
    worker_id = await make_worker(async_client)
    await async_client.put(f"/v1/workers/{worker_id}/documents/pan", json={"document_number": "ABCDE1234F"})
    res = await async_client.get(f"/v1/workers/{worker_id}/documents/pan/number")
    assert res.json() == {"value": "ABCDE1234F"}
    actions = [r.action for r in (await db_session.execute(select(SensitiveAccessLog))).scalars()]
    assert "reveal" in actions and "update" in actions


@pytest.mark.asyncio
async def test_numbers_are_hidden_from_those_who_may_not_see_them(async_client):
    worker_id = await make_worker(async_client)
    await async_client.put(f"/v1/workers/{worker_id}/documents/pan", json={"document_number": "ABCDE1234F"})

    act_as("people.employee.read")
    onboarding = (await async_client.get(f"/v1/workers/{worker_id}/onboarding")).json()
    pan = item(onboarding, "pan")
    assert pan["status"] == "uploaded" and pan["number_masked"] is None
    assert (await async_client.get(f"/v1/workers/{worker_id}/documents/pan/number")).status_code == 403
    assert (await async_client.put(f"/v1/workers/{worker_id}/documents/pan", json={})).status_code == 403
    assert (await async_client.get(f"/v1/workers/{worker_id}/bank-accounts")).status_code == 403

    act_as("people.employee.read", "people.employee.manage")  # sees it masked, but cannot reveal it
    assert item((await async_client.get(f"/v1/workers/{worker_id}/onboarding")).json(), "pan")["number_masked"] == "•••• 234F"
    assert (await async_client.get(f"/v1/workers/{worker_id}/documents/pan/number")).status_code == 403


@pytest.mark.asyncio
async def test_without_an_encryption_key_numbers_answer_503_but_the_rest_works(async_client, monkeypatch):
    worker_id = await make_worker(async_client)
    monkeypatch.setattr(settings, "field_encryption_key", "")
    res = await async_client.put(f"/v1/workers/{worker_id}/documents/pan", json={"document_number": "ABCDE1234F"})
    assert res.status_code == 503 and res.json()["code"] == "ENCRYPTION_UNAVAILABLE"
    assert (await async_client.get(f"/v1/workers/{worker_id}/onboarding")).status_code == 200
    monkeypatch.setattr(settings, "field_encryption_key", "not-a-valid-key")
    assert (await async_client.put(f"/v1/workers/{worker_id}/documents/pan", json={"document_number": "ABCDE1234F"})).status_code == 503


BANK = {
    "account_holder_name": "Doc Worker", "bank_name": "HDFC Bank", "branch": "MG Road",
    "account_number": "50100123456789", "ifsc": "hdfc0001234", "account_type": "savings",
}


@pytest.mark.asyncio
async def test_bank_account_is_validated_masked_and_first_one_is_primary(async_client):
    worker_id = await make_worker(async_client)
    base = f"/v1/workers/{worker_id}/bank-accounts"
    assert (await async_client.post(base, json={**BANK, "ifsc": "BAD"})).status_code == 422
    assert (await async_client.post(base, json={**BANK, "account_number": "12AB"})).status_code == 422
    assert (await async_client.post(base, json={**BANK, "account_type": "gold"})).status_code == 422

    created = await async_client.post(base, json=BANK)
    assert created.status_code == 201, created.text
    account = created.json()
    assert account["account_masked"] == "•••• 6789" and account["ifsc"] == "HDFC0001234"
    assert account["is_primary"] is True and account["status"] == "pending"
    assert "50100123456789" not in created.text

    reveal = await async_client.get(f"{base}/{account['id']}/number")
    assert reveal.json() == {"value": "50100123456789"}


@pytest.mark.asyncio
async def test_bank_primary_verification_and_deactivation(async_client):
    worker_id = await make_worker(async_client)
    base = f"/v1/workers/{worker_id}/bank-accounts"
    first = (await async_client.post(base, json=BANK)).json()
    second = (await async_client.post(base, json={**BANK, "bank_name": "ICICI", "account_number": "98765432101"})).json()
    assert second["is_primary"] is False

    # Verify the first; changing its number sends it back to pending
    assert (await async_client.post(f"{base}/{first['id']}/verify")).json()["status"] == "verified"
    onboarding = (await async_client.get(f"/v1/workers/{worker_id}/onboarding")).json()
    assert item(onboarding, "bank_account")["status"] == "verified"
    edited = (await async_client.patch(f"{base}/{first['id']}", json={"account_number": "11122233344"})).json()
    assert edited["status"] == "pending" and edited["account_masked"] == "•••• 3344"

    # The primary cannot be deactivated until another takes over
    assert (await async_client.post(f"{base}/{first['id']}/deactivate")).status_code == 409
    made = (await async_client.post(f"{base}/{second['id']}/primary")).json()
    assert made["is_primary"] is True
    listed = (await async_client.get(base)).json()
    assert [a["is_primary"] for a in listed] == [True, False]
    assert (await async_client.post(f"{base}/{first['id']}/deactivate")).json()["status"] == "inactive"
    assert (await async_client.patch(f"{base}/{first['id']}", json={"branch": "X"})).status_code == 409


@pytest.mark.asyncio
async def test_onboarding_progress_follows_the_required_list(async_client):
    worker_id = await make_worker(async_client)
    onboarding = (await async_client.get(f"/v1/workers/{worker_id}/onboarding")).json()
    required = {i["code"] for i in onboarding["items"] if i["required"]}
    assert required == {"pan", "aadhaar", "address_proof", "offer_letter", "nda", "bank_account"}
    assert onboarding["required_done"] == 0 and onboarding["complete"] is False

    # A company narrows its list to PAN only
    saved = await async_client.put("/v1/onboarding/requirements", json={"required": ["pan"]})
    assert saved.status_code == 200, saved.text
    assert [i["code"] for i in saved.json()["items"] if i["required"]] == ["pan"]
    assert (await async_client.put("/v1/onboarding/requirements", json={"required": ["selfie"]})).status_code == 422

    await async_client.put(f"/v1/workers/{worker_id}/documents/pan", json={"document_number": "ABCDE1234F"})
    onboarding = (await async_client.post(f"/v1/workers/{worker_id}/documents/pan/verify")).json()
    assert onboarding["required_total"] == 1 and onboarding["required_done"] == 1 and onboarding["complete"] is True


@pytest.mark.asyncio
async def test_documents_service_can_check_access_to_an_employee(async_client):
    worker_id = await make_worker(async_client)
    ok = await async_client.get(f"/v1/internal/subject-access/people.employee/{worker_id}", params={"action": "attach"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["label"] == "Doc Worker" and ok.json()["organization_id"] == str(TEST_ORG_ID)
    assert (await async_client.get(f"/v1/internal/subject-access/people.employee/{uuid.uuid4()}")).status_code == 404
    assert (await async_client.get(f"/v1/internal/subject-access/people.unknown/{worker_id}")).status_code == 404

    act_as("people.employee.read")
    assert (await async_client.get(f"/v1/internal/subject-access/people.employee/{worker_id}")).status_code == 200
    assert (
        await async_client.get(f"/v1/internal/subject-access/people.employee/{worker_id}", params={"action": "attach"})
    ).status_code == 403
