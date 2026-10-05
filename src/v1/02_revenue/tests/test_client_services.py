import uuid
from datetime import date, timedelta

import httpx
import pytest

pytestmark = pytest.mark.asyncio

BASE = "/api/revenue/v1"


async def _create_client(async_client: httpx.AsyncClient, name: str = "Acme Traders") -> str:
    payload = {
        "name": name,
        "legal_name": f"{name} Pvt Ltd",
        "client_type": "company",
        "billing_address": {
            "line1": "1 Market Road",
            "city": "Patna",
            "state": "Bihar",
            "state_code": "10",
            "postal_code": "800001",
            "country": "IN",
        },
        "owner_user_id": str(uuid.uuid4()),
    }
    res = await async_client.post(f"{BASE}/clients", json=payload)
    assert res.status_code == 201
    return res.json()["id"]


async def _category_id(async_client: httpx.AsyncClient, name: str) -> str:
    res = await async_client.get(f"{BASE}/service-categories")
    assert res.status_code == 200
    return next(c["id"] for c in res.json()["data"] if c["name"] == name)


async def test_categories_defaults_and_custom(async_client: httpx.AsyncClient):
    res = await async_client.get(f"{BASE}/service-categories")
    assert res.status_code == 200
    names = {c["name"] for c in res.json()["data"]}
    assert {"Hosting", "Insurance", "Logistics"} <= names

    # Listing again must not duplicate the defaults
    again = await async_client.get(f"{BASE}/service-categories")
    assert len(again.json()["data"]) == len(names)

    created = await async_client.post(f"{BASE}/service-categories", json={"name": "Security Guards"})
    assert created.status_code == 201

    dup = await async_client.post(f"{BASE}/service-categories", json={"name": "security guards"})
    assert dup.status_code == 409
    assert dup.json()["detail"]["code"] == "DUPLICATE_NAME"


async def test_client_service_lifecycle(async_client: httpx.AsyncClient):
    client_id = await _create_client(async_client)
    insurance_id = await _category_id(async_client, "Insurance")

    prov = await async_client.post(
        f"{BASE}/service-providers",
        json={"name": "LIC", "category_id": insurance_id, "phone": "1800-000-000"},
    )
    assert prov.status_code == 201
    provider_id = prov.json()["id"]
    assert prov.json()["category"]["name"] == "Insurance"

    # Category defaults to the provider's; start date may be in the past
    create = await async_client.post(
        f"{BASE}/clients/{client_id}/services",
        json={
            "provider_id": provider_id,
            "name": "Fire insurance policy",
            "reference_no": "POL-123",
            "managed_by": "client",
            "start_date": "2023-04-01",
            "renewal_date": (date.today() + timedelta(days=10)).isoformat(),
            "cost": {"amount": 12000, "currency": "INR"},
            "billing_cycle": "yearly",
            "attributes": {"sum_insured": "5000000"},
        },
    )
    assert create.status_code == 201
    record = create.json()
    assert record["category"]["name"] == "Insurance"
    assert record["provider"]["name"] == "LIC"
    assert record["cost"]["amount"] == "12000.00"
    assert record["attributes"]["sum_insured"] == "5000000"
    record_id = record["id"]

    # Shows up for the client and in the renewals search
    for_client = await async_client.get(f"{BASE}/clients/{client_id}/services")
    assert [r["id"] for r in for_client.json()["data"]] == [record_id]
    due = await async_client.get(f"{BASE}/client-services", params={"renewal_within_days": 30})
    assert record_id in [r["id"] for r in due.json()["data"]]
    not_due = await async_client.get(f"{BASE}/client-services", params={"renewal_within_days": 5})
    assert record_id not in [r["id"] for r in not_due.json()["data"]]

    # Update requires If-Match
    no_etag = await async_client.patch(f"{BASE}/client-services/{record_id}", json={"status": "expired"})
    assert no_etag.status_code == 428
    upd = await async_client.patch(
        f"{BASE}/client-services/{record_id}",
        json={"status": "expired", "cost": None},
        headers={"If-Match": create.headers["ETag"]},
    )
    assert upd.status_code == 200
    assert upd.json()["status"] == "expired"
    assert upd.json()["cost"] is None

    # A provider in use cannot be deleted
    in_use = await async_client.delete(f"{BASE}/service-providers/{provider_id}")
    assert in_use.status_code == 409

    deleted = await async_client.delete(f"{BASE}/client-services/{record_id}")
    assert deleted.status_code == 204
    assert (await async_client.delete(f"{BASE}/client-services/{record_id}")).status_code == 204
    assert (await async_client.get(f"{BASE}/client-services/{record_id}")).status_code == 404
    assert (await async_client.delete(f"{BASE}/service-providers/{provider_id}")).status_code == 204


async def test_client_service_validation(async_client: httpx.AsyncClient):
    client_id = await _create_client(async_client)
    prov = await async_client.post(f"{BASE}/service-providers", json={"name": "Hostinger"})
    provider_id = prov.json()["id"]

    future_start = (date.today() + timedelta(days=1)).isoformat()
    res = await async_client.post(
        f"{BASE}/clients/{client_id}/services",
        json={"provider_id": provider_id, "name": "acme.com", "start_date": future_start},
    )
    assert res.status_code == 422

    res = await async_client.post(
        f"{BASE}/clients/{client_id}/services",
        json={"provider_id": provider_id, "name": "acme.com", "start_date": "2024-01-10", "end_date": "2024-01-01"},
    )
    assert res.status_code == 422

    res = await async_client.post(
        f"{BASE}/clients/{uuid.uuid4()}/services",
        json={"provider_id": provider_id, "name": "acme.com"},
    )
    assert res.status_code == 404

    res = await async_client.post(
        f"{BASE}/clients/{client_id}/services",
        json={"provider_id": str(uuid.uuid4()), "name": "acme.com"},
    )
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "SERVICE_PROVIDER_NOT_FOUND"


async def test_client_services_are_org_scoped(async_client: httpx.AsyncClient):
    client_id = await _create_client(async_client)
    prov = await async_client.post(f"{BASE}/service-providers", json={"name": "Airtel"})
    create = await async_client.post(
        f"{BASE}/clients/{client_id}/services",
        json={"provider_id": prov.json()["id"], "name": "Leased line"},
    )
    record_id = create.json()["id"]

    other_org = {"X-Organization-Id": str(uuid.uuid4())}
    assert (await async_client.get(f"{BASE}/client-services/{record_id}", headers=other_org)).status_code == 404
    listing = await async_client.get(f"{BASE}/client-services", headers=other_org)
    assert listing.json()["data"] == []
    providers = await async_client.get(f"{BASE}/service-providers", headers=other_org)
    assert providers.json()["data"] == []
