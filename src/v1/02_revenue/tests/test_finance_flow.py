"""
Tax and billing through the API: configuration that changes without code, staged billing with
partial payments and TDS, credit and debit notes, write-offs, numbering and the GST-vs-cash view.
"""
from datetime import date, timedelta
import uuid

import httpx
import pytest

from tests.conftest import TEST_SUPPLIER_GSTIN, TEST_USER_ID, valid_gstin
from tests.test_sales_flow import BASE, _act, _converted_lead, _quotation

pytestmark = pytest.mark.asyncio

TODAY = date.today()
KARNATAKA_ADDRESS = {
    "line1": "MG Road", "city": "Bengaluru", "state": "Karnataka", "state_code": "29", "postal_code": "560001", "country": "IN",
}


def key() -> dict:
    return {"Idempotency-Key": str(uuid.uuid4())}


def amount(money: dict) -> str:
    return money["amount"]


async def customer(client: httpx.AsyncClient, address: dict | None = None, name: str = "Acme", headers: dict | None = None) -> str:
    res = await client.post(
        f"{BASE}/clients",
        json={"name": name, "legal_name": f"{name} Pvt Ltd", "billing_address": address or KARNATAKA_ADDRESS,
              "owner_user_id": str(TEST_USER_ID)},
        headers=headers,
    )
    assert res.status_code == 201, res.json()
    return res.json()["id"]


async def draft(client: httpx.AsyncClient, customer_id: str, price: float = 1000.0, **line) -> dict:
    res = await client.post(
        f"{BASE}/invoices",
        json={"client_id": customer_id, "lines": [{"description": "Consulting", "unit_price": {"amount": price, "currency": "INR"}, **line}]},
    )
    assert res.status_code == 201, res.json()
    return res.json()


async def issue(client: httpx.AsyncClient, invoice: dict, issue_date: date | None = None) -> dict:
    res = await client.post(
        f"{BASE}/invoices/{invoice['id']}/issue",
        json={"issue_date": issue_date.isoformat()} if issue_date else None,
        headers={"If-Match": f'"{invoice["version"]}"', **key()},
    )
    assert res.status_code == 200, res.json()
    return res.json()


async def pay(client: httpx.AsyncClient, customer_id: str, cash: float, invoice_id: str, tds: float = 0.0) -> httpx.Response:
    allocation = {"invoice_id": invoice_id, "amount": {"amount": cash, "currency": "INR"}}
    if tds:
        allocation["tds_amount"] = {"amount": tds, "currency": "INR"}
    return await client.post(
        f"{BASE}/payments",
        json={"client_id": customer_id, "received_on": TODAY.isoformat(), "amount": {"amount": cash, "currency": "INR"},
              "allocations": [allocation]},
        headers=key(),
    )


async def accepted_contract(client: httpx.AsyncClient, fake_documents, payment_terms: list, start: date = TODAY, end: date | None = None) -> dict:
    converted = await _converted_lead(client)  # a Maharashtra customer: inter-state from Karnataka
    quote = await _quotation(client, converted["opportunity"]["id"])  # one offering at 100,000 before tax
    for action in ("submit", "send", "accept"):
        quote = (await _act(client, quote, action)).json()
    body = {"quotation_id": quote["id"], "start_date": start.isoformat(), "payment_terms": payment_terms}
    if end:
        body["end_date"] = end.isoformat()
    contract = await client.post(f"{BASE}/contracts", json=body)
    assert contract.status_code == 201, contract.json()
    signed = fake_documents.add_linked("revenue.contract", contract.json()["id"])
    attached = await client.put(
        f"{BASE}/contracts/{contract.json()['id']}/signed-document", json={"document_id": signed},
        headers={"If-Match": contract.headers["ETag"]},
    )
    active = await client.post(f"{BASE}/contracts/{contract.json()['id']}/activate", headers={"If-Match": attached.headers["ETag"]})
    assert active.status_code == 200, active.json()
    return active.json()


# ------------------------------------------------------------------ setup


async def test_billing_needs_the_organizations_own_registration(async_client: httpx.AsyncClient):
    other_org = {"X-Organization-Id": str(uuid.uuid4())}
    customer_id = await customer(async_client, headers=other_org)
    res = await async_client.post(
        f"{BASE}/invoices",
        json={"client_id": customer_id, "lines": [{"description": "x", "unit_price": {"amount": 10, "currency": "INR"}}]},
        headers=other_org,
    )
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "SUPPLIER_REGISTRATION_REQUIRED"


async def test_registration_numbers_are_checked_by_the_regimes_validator(async_client: httpx.AsyncClient):
    body = {"regime_code": "IN-GST", "legal_name": "Fillip Mumbai"}
    bad = await async_client.post(f"{BASE}/tax-registrations", json=body | {"registration_no": valid_gstin("27")[:-1] + "0"})
    assert bad.json()["detail"]["code"] == "REGISTRATION_NUMBER_INVALID"

    mismatch = await async_client.post(
        f"{BASE}/tax-registrations", json=body | {"registration_no": valid_gstin("27"), "jurisdiction_code": "29"}
    )
    assert mismatch.json()["detail"]["code"] == "REGISTRATION_JURISDICTION_MISMATCH"

    created = await async_client.post(f"{BASE}/tax-registrations", json=body | {"registration_no": valid_gstin("27").lower()})
    assert created.status_code == 201
    assert created.json()["jurisdiction_code"] == "27"
    assert created.json()["registration_no"] == valid_gstin("27")

    again = await async_client.post(f"{BASE}/tax-registrations", json=body | {"registration_no": valid_gstin("27")})
    assert again.status_code == 409


async def test_finance_settings_start_at_their_defaults(async_client: httpx.AsyncClient):
    settings = await async_client.get(f"{BASE}/finance-settings")
    assert settings.json()["version"] == 0
    assert settings.json()["billing_mode"] == "staged"

    unknown = await async_client.patch(
        f"{BASE}/finance-settings", json={"default_tax_category": "NOPE"}, headers={"If-Match": '"0"'}
    )
    assert unknown.json()["detail"]["code"] == "TAX_CONFIG_NOT_EFFECTIVE"

    changed = await async_client.patch(
        f"{BASE}/finance-settings", json={"credit_note_deadline_mode": "warn_with_reason"}, headers={"If-Match": '"0"'}
    )
    assert changed.status_code == 200
    assert (changed.json()["version"], changed.json()["credit_note_deadline_mode"]) == (1, "warn_with_reason")


async def test_customer_tax_profile_is_checked_against_the_configuration(async_client: httpx.AsyncClient):
    customer_id = await customer(async_client)
    url = f"{BASE}/clients/{customer_id}/tax-profile"
    initial = await async_client.get(url)
    assert initial.json()["version"] == 0
    assert initial.json()["effective"]["place_of_supply"] == "29"
    assert initial.json()["effective"]["registration_type"] == "unregistered"

    wrong = await async_client.put(url, json={"registration_type": "martian"}, headers={"If-Match": '"0"'})
    assert wrong.json()["detail"]["code"] == "REGISTRATION_TYPE_UNKNOWN"

    unknown_section = await async_client.put(url, json={"tds_section_code": "999Z"}, headers={"If-Match": '"0"'})
    assert unknown_section.json()["detail"]["code"] == "WITHHOLDING_SECTION_NOT_EFFECTIVE"
    saved = await async_client.put(url, json={"tds_section_code": "194J"}, headers={"If-Match": '"0"'})
    assert saved.status_code == 200
    assert saved.json()["effective"]["tds_section_code"] == "194J"


# ------------------------------------------------------------------ configuration without code


async def test_a_future_rate_change_is_configuration_not_code(async_client: httpx.AsyncClient):
    """Close today's services category at a date, add a new rate and category from that date: done."""
    customer_id = await customer(async_client)
    change_day = date(TODAY.year + 3, 1, 1)
    [services] = (await async_client.get(f"{BASE}/tax/config-entries", params={"kind": "category", "code": "SVC_18", "as_of": TODAY.isoformat()})).json()

    # Closing the category on its own would leave the regime's default category with nothing in effect.
    closed = await async_client.patch(
        f"{BASE}/tax/config-entries/{services['id']}", json={"effective_to": change_day.isoformat()},
        headers={"If-Match": f'"{services["version"]}"'},
    )
    assert closed.json()["detail"]["code"] == "TAX_CONFIG_BROKEN_REFERENCE"

    rate = await async_client.post(f"{BASE}/tax/config-entries", json={
        "kind": "rate", "code": "GST_16", "effective_from": change_day.isoformat(), "data": {"percent": 16, "notification": "Hypothetical"},
    })
    assert rate.status_code == 201, rate.json()
    successor = await async_client.post(f"{BASE}/tax/config-entries", json={
        "kind": "category", "code": "SVC_18", "effective_from": change_day.isoformat(), "supersedes_id": services["id"],
        "data": {"regime": "IN-GST", "name": "Services", "treatment": "taxable", "rate": "GST_16"},
    })
    assert successor.status_code == 201, successor.json()

    def preview(on: date):
        return async_client.post(f"{BASE}/tax/calculations", json={
            "client_id": customer_id, "tax_point_date": on.isoformat(),
            "lines": [{"unit_price": {"amount": 1000, "currency": "INR"}, "tax_category_code": "SVC_18"}],
        })

    assert amount((await preview(TODAY)).json()["tax_total"]) == "180.00"
    assert amount((await preview(change_day)).json()["tax_total"]) == "160.00"
    history = (await async_client.get(f"{BASE}/tax/config-revisions")).json()
    assert [entry["summary"].split()[0] for entry in history[:2]] == ["Superseded", "Added"]
    versions = (await async_client.get(f"{BASE}/tax/config-entries", params={"kind": "category", "code": "SVC_18"})).json()
    assert [(entry["effective_from"], entry["effective_to"]) for entry in versions][-2:] == [
        ("2017-07-01", change_day.isoformat()), (change_day.isoformat(), None),
    ]


async def test_entries_in_effect_are_protected(async_client: httpx.AsyncClient):
    [rate] = (await async_client.get(f"{BASE}/tax/config-entries", params={"kind": "rate", "code": "GST_18"})).json()
    etag = {"If-Match": f'"{rate["version"]}"'}

    rewrite = await async_client.patch(f"{BASE}/tax/config-entries/{rate['id']}", json={"data": {"percent": 17}}, headers=etag)
    assert rewrite.json()["detail"]["code"] == "TAX_CONFIG_ENTRY_IN_EFFECT"

    backdate = await async_client.patch(
        f"{BASE}/tax/config-entries/{rate['id']}", json={"effective_to": "2020-01-01"}, headers=etag
    )
    assert backdate.json()["detail"]["code"] == "TAX_CONFIG_ENTRY_IN_EFFECT"

    deletion = await async_client.delete(f"{BASE}/tax/config-entries/{rate['id']}", headers=etag)
    assert deletion.json()["detail"]["code"] == "TAX_CONFIG_ENTRY_IN_EFFECT"

    # Closing the rate would leave SVC_18 and others pointing at nothing.
    broken = await async_client.patch(
        f"{BASE}/tax/config-entries/{rate['id']}", json={"effective_to": (TODAY + timedelta(days=1)).isoformat()}, headers=etag
    )
    assert broken.json()["detail"]["code"] == "TAX_CONFIG_BROKEN_REFERENCE"

    overlap = await async_client.post(f"{BASE}/tax/config-entries", json={
        "kind": "rate", "code": "GST_18", "effective_from": TODAY.isoformat(), "data": {"percent": 18},
    })
    assert overlap.json()["detail"]["code"] == "TAX_CONFIG_OVERLAP"

    invalid = await async_client.post(f"{BASE}/tax/config-entries", json={
        "kind": "category", "code": "X", "effective_from": TODAY.isoformat(), "data": {"regime": "IN-GST", "name": "X", "treatment": "taxable"},
    })
    assert invalid.json()["detail"]["code"] == "TAX_CONFIG_INVALID"


async def test_pack_upgrade_shows_its_changes_and_keeps_local_edits(async_client: httpx.AsyncClient, monkeypatch):
    from dataclasses import replace

    import finance.packs as packs_module
    import services.tax_config_service as service_module

    current = packs_module.load_packs()
    gst_v1 = current["in_gst"][1]
    changed_entries = []
    for entry in gst_v1.entries:
        if (entry.kind, entry.code) in (("rate", "GST_3"), ("jurisdiction", "97")):
            entry = replace(entry, data={**entry.data, "name": "Renamed"} if entry.kind == "jurisdiction" else {**entry.data, "notification": "Corrected reference"})
        changed_entries.append(entry)
    changed_entries.append(packs_module.PackEntry("rate", "GST_1", date(2030, 1, 1), None, {"percent": "1", "notification": None}))
    gst_v2 = replace(gst_v1, version=2, entries=tuple(changed_entries))
    upgraded = {**current, "in_gst": {1: gst_v1, 2: gst_v2}}

    # The organization starts on v1, and edits a jurisdiction (a far-off close date): v2 must not overwrite it silently.
    [territory] = (await async_client.get(f"{BASE}/tax/config-entries", params={"kind": "jurisdiction", "code": "97"})).json()
    edited = await async_client.patch(
        f"{BASE}/tax/config-entries/{territory['id']}", json={"effective_to": "2099-01-01"},
        headers={"If-Match": f'"{territory["version"]}"'},
    )
    assert edited.json()["locally_modified"] is True
    monkeypatch.setattr(packs_module, "load_packs", lambda: upgraded)
    monkeypatch.setattr(service_module, "load_packs", lambda: upgraded)
    packs = {pack["code"]: pack for pack in (await async_client.get(f"{BASE}/tax/packs")).json()}
    assert (packs["in_gst"]["applied_version"], packs["in_gst"]["latest_version"]) == (1, 2)

    diff = (await async_client.get(f"{BASE}/tax/packs/in_gst/versions/2/diff")).json()
    actions = {(change["kind"], change["code"]): change["action"] for change in diff["changes"]}
    assert actions[("rate", "GST_1")] == "add"
    assert actions[("rate", "GST_3")] == "update"
    assert actions[("jurisdiction", "97")] == "conflict"

    applied = await async_client.post(f"{BASE}/tax/pack-applications", json={"pack": "in_gst", "version": 2})
    assert applied.status_code == 201, applied.json()
    kept = (await async_client.get(f"{BASE}/tax/config-entries", params={"kind": "jurisdiction", "code": "97"})).json()
    assert (kept[0]["effective_to"], kept[0]["data"]["name"]) == ("2099-01-01", "Other Territory")
    updated = (await async_client.get(f"{BASE}/tax/config-entries", params={"kind": "rate", "code": "GST_3"})).json()
    assert updated[0]["data"]["notification"] == "Corrected reference"


# ------------------------------------------------------------------ documents


async def test_legacy_rate_maps_to_a_plain_category_and_inter_state_reads_back(async_client: httpx.AsyncClient):
    converted = await _converted_lead(async_client)  # Maharashtra
    quote = await _quotation(async_client, converted["opportunity"]["id"])
    assert quote["items"][0]["tax_category_code"] == "SVC_18"
    assert (amount(quote["totals"]["igst"]), amount(quote["totals"]["cgst"])) == ("18000.00", "0.00")
    read_back = (await async_client.get(f"{BASE}/quotations/{quote['id']}")).json()
    assert read_back["totals"] == quote["totals"]
    assert [tax["component_code"] for tax in read_back["totals"]["taxes"]] == ["IGST"]


async def test_export_under_lut_is_zero_rated(async_client: httpx.AsyncClient):
    [registration] = (await async_client.get(f"{BASE}/tax-registrations")).json()
    await async_client.patch(
        f"{BASE}/tax-registrations/{registration['id']}",
        json={"lut_number": "AD290000000001", "lut_valid_from": f"{TODAY.year - 1}-04-01", "lut_valid_to": f"{TODAY.year + 1}-03-31"},
        headers={"If-Match": f'"{registration["version"]}"'},
    )
    overseas = await customer(async_client, {"line1": "1 Market St", "city": "San Francisco", "state": "CA", "state_code": "CA",
                                             "postal_code": "94105", "country": "US"}, name="Globex")
    invoice = await draft(async_client, overseas, price=2000)
    assert invoice["supply_type"] == "export"
    assert amount(invoice["totals"]["grand_total"]) == "2000.00"
    assert invoice["tax_notes"] == ["Supply meant for export under LUT without payment of IGST"]
    assert invoice["place_of_supply"] == "US"


async def test_each_registration_numbers_its_own_series(async_client: httpx.AsyncClient):
    customer_id = await customer(async_client)
    first = await issue(async_client, await draft(async_client, customer_id))
    mumbai = await async_client.post(
        f"{BASE}/tax-registrations",
        json={"regime_code": "IN-GST", "registration_no": valid_gstin("27"), "legal_name": "Fillip Mumbai"},
    )
    from_mumbai = await async_client.post(
        f"{BASE}/invoices",
        json={"client_id": customer_id, "tax_registration_id": mumbai.json()["id"],
              "lines": [{"description": "x", "unit_price": {"amount": 100, "currency": "INR"}}]},
    )
    issued_mumbai = await issue(async_client, from_mumbai.json())
    second = await issue(async_client, await draft(async_client, customer_id))

    assert first["invoice_no"].endswith("000001") and second["invoice_no"].endswith("000002")
    # Unique per registration (GSTIN), as the law asks: Mumbai starts its own series.
    assert issued_mumbai["invoice_no"] == first["invoice_no"]
    assert issued_mumbai["supplier_gstin"] == valid_gstin("27")
    assert first["supplier_gstin"] == TEST_SUPPLIER_GSTIN
    # A Karnataka customer billed from Maharashtra is inter-state.
    assert issued_mumbai["supply_type"] == "inter_state"


async def test_credit_note_deadline_blocks_unless_a_reason_is_allowed(async_client: httpx.AsyncClient):
    customer_id = await customer(async_client)
    old = await issue(async_client, await draft(async_client, customer_id), issue_date=date(2024, 5, 10))
    assert old["tax_point_date"] == "2024-05-10"
    assert [deadline["code"] for deadline in old["deadlines"]] == ["CUSTOMER_ITC_REVERSAL"]

    url = f"{BASE}/invoices/{old['id']}/credit-notes"
    blocked = await async_client.post(url, json={"reason": "price_correction"}, headers=key())
    assert blocked.json()["detail"]["code"] == "CREDIT_NOTE_DEADLINE_PASSED"
    assert blocked.json()["detail"]["meta"]["due_on"] == "2025-11-30"

    await async_client.patch(f"{BASE}/finance-settings", json={"credit_note_deadline_mode": "warn_with_reason"}, headers={"If-Match": '"0"'})
    still_blocked = await async_client.post(url, json={"reason": "price_correction"}, headers=key())
    assert still_blocked.json()["detail"]["code"] == "CREDIT_NOTE_DEADLINE_PASSED"
    allowed = await async_client.post(url, json={"reason": "price_correction", "override_reason": "Agreed with the CA"}, headers=key())
    assert allowed.status_code == 201, allowed.json()


async def test_partial_credit_note_is_taxed_like_the_original_and_never_pays_it(async_client: httpx.AsyncClient):
    customer_id = await customer(async_client)
    invoice = await issue(async_client, await draft(async_client, customer_id, price=100000))
    credit = await async_client.post(
        f"{BASE}/invoices/{invoice['id']}/credit-notes",
        json={"reason": "service_deficiency", "lines": [{"description": "Deficiency", "unit_price": {"amount": 10000, "currency": "INR"}}]},
        headers=key(),
    )
    assert credit.status_code == 201, credit.json()
    assert (amount(credit.json()["totals"]["cgst_total"]), amount(credit.json()["totals"]["grand_total"])) == ("900.00", "11800.00")
    original = (await async_client.get(f"{BASE}/invoices/{invoice['id']}")).json()
    assert (original["status"], amount(original["balance_due"]), amount(original["credited_amount"])) == ("issued", "106200.00", "11800.00")

    too_much = await async_client.post(
        f"{BASE}/invoices/{invoice['id']}/credit-notes",
        json={"reason": "other", "lines": [{"description": "x", "unit_price": {"amount": 100000, "currency": "INR"}}]},
        headers=key(),
    )
    assert too_much.json()["detail"]["code"] == "CREDIT_EXCEEDS_INVOICE"


async def test_debit_notes_are_payable_and_write_offs_change_no_tax(async_client: httpx.AsyncClient):
    customer_id = await customer(async_client)
    invoice = await issue(async_client, await draft(async_client, customer_id, price=1000))
    debit = await async_client.post(
        f"{BASE}/invoices/{invoice['id']}/debit-notes",
        json={"reason": "additional_charges", "lines": [{"description": "Extra visit", "unit_price": {"amount": 500, "currency": "INR"}}]},
        headers=key(),
    )
    assert debit.status_code == 201, debit.json()
    assert (debit.json()["doc_type"], amount(debit.json()["balance_due"])) == ("debit_note", "590.00")
    assert (await pay(async_client, customer_id, 590, debit.json()["id"])).status_code == 201

    paid_part = await pay(async_client, customer_id, 1000, invoice["id"])
    assert paid_part.status_code == 201
    current = (await async_client.get(f"{BASE}/invoices/{invoice['id']}")).json()
    written = await async_client.post(
        f"{BASE}/invoices/{invoice['id']}/write-offs", json={"amount": {"amount": 180, "currency": "INR"}, "reason": "Customer refuses the GST portion"},
        headers={"If-Match": f'"{current["version"]}"', **key()},
    )
    assert written.status_code == 201, written.json()
    assert (written.json()["status"], amount(written.json()["balance_due"])) == ("paid", "0.00")
    # The GST on the invoice is unchanged by the write-off.
    assert amount(written.json()["totals"]["tax_total"]) == "180.00"


async def test_staged_billing_with_partial_payment_and_tds(async_client: httpx.AsyncClient, fake_documents):
    """docs/tax-and-finance-research.md §7.8: bill each stage, GST on what is billed, TDS tracked."""
    contract = await accepted_contract(async_client, fake_documents, [
        {"seq": 1, "trigger_type": "advance", "percent": 50},
        {"seq": 2, "trigger_type": "on_completion", "percent": 50},
    ])
    [schedule] = (await async_client.get(f"{BASE}/billing-schedules", params={"contract_id": contract["id"]})).json()
    assert amount(schedule["basis_amount"]) == "100000.00"
    advance, completion = schedule["lines"]
    assert (amount(advance["amount"]), advance["billable"]) == ("50000.00", True)
    assert (amount(completion["amount"]), completion["billable"]) == ("50000.00", False)

    ready = (await async_client.get(f"{BASE}/billing-schedule-lines", params={"billable": "true", "contract_id": contract["id"]})).json()
    assert [line["id"] for line in ready] == [advance["id"]]

    client_id = schedule["client_id"]
    direct = await async_client.post(f"{BASE}/invoices", json={
        "client_id": client_id, "contract_id": contract["id"],
        "lines": [{"description": "x", "unit_price": {"amount": 1, "currency": "INR"}}],
    })
    assert direct.json()["detail"]["code"] == "INVOICE_REQUIRES_SCHEDULE_LINE"

    await async_client.put(
        f"{BASE}/clients/{client_id}/tax-profile", json={"tds_section_code": "PROFESSIONAL_FEES"}, headers={"If-Match": '"0"'}
    )
    bill_url = f"{BASE}/billing-schedules/{schedule['id']}/lines/{advance['id']}/invoices"
    advance_invoice = await async_client.post(bill_url, headers=key())
    assert advance_invoice.status_code == 201, advance_invoice.json()
    assert (await async_client.post(bill_url, headers=key())).json()["detail"]["code"] == "SCHEDULE_LINE_NOT_BILLABLE"

    issued = await issue(async_client, advance_invoice.json())
    # Inter-state (Maharashtra customer): IGST on the advance only, TDS expected on the pre-GST value.
    assert (amount(issued["totals"]["igst_total"]), amount(issued["totals"]["grand_total"])) == ("9000.00", "59000.00")
    assert amount(issued["withholding"][0]["amount"]) == "5000.00"
    assert amount(issued["net_receivable"]) == "54000.00"

    # The customer settles half: 27,000 in cash plus 2,500 TDS withheld.
    payment = await pay(async_client, client_id, 27000, issued["id"], tds=2500)
    assert payment.status_code == 201, payment.json()
    after = (await async_client.get(f"{BASE}/invoices/{issued['id']}")).json()
    assert (after["status"], amount(after["balance_due"])) == ("partially_paid", "29500.00")

    [receivable] = (await async_client.get(f"{BASE}/tds-receivables", params={"client_id": client_id})).json()
    assert (amount(receivable["amount"]), receivable["section_code"], receivable["status"]) == ("2500.00", "PROFESSIONAL_FEES", "expected")
    reconciled = await async_client.patch(
        f"{BASE}/tds-receivables/{receivable['id']}", json={"status": "reflected"}, headers={"If-Match": f'"{receivable["version"]}"'}
    )
    assert reconciled.json()["status"] == "reflected"

    report = (await async_client.get(f"{BASE}/reports/gst-vs-cash", params={"period": TODAY.strftime("%Y-%m")})).json()
    assert amount(report["gst_on_documents"]) == "9000.00"
    assert amount(report["gst_in_settlements"]) == "4500.00"
    assert amount(report["gap"]) == "4500.00"

    # The completion milestone is billable once marked reached.
    marked = await async_client.patch(
        f"{BASE}/billing-schedules/{schedule['id']}/lines/{completion['id']}", json={"status": "ready"},
        headers={"If-Match": f'"{completion["version"]}"'},
    )
    assert marked.json()["billable"] is True


async def test_full_upfront_mode_bills_the_contract_in_one_line(async_client: httpx.AsyncClient, fake_documents):
    await async_client.patch(f"{BASE}/finance-settings", json={"billing_mode": "full_upfront"}, headers={"If-Match": '"0"'})
    contract = await accepted_contract(async_client, fake_documents, [
        {"seq": 1, "trigger_type": "advance", "percent": 50},
        {"seq": 2, "trigger_type": "on_completion", "percent": 50},
    ])
    [schedule] = (await async_client.get(f"{BASE}/billing-schedules", params={"contract_id": contract["id"]})).json()
    assert [(amount(line["amount"]), line["billable"]) for line in schedule["lines"]] == [("100000.00", True)]


async def test_monthly_terms_spread_the_contract_over_its_months(async_client: httpx.AsyncClient, fake_documents):
    start = TODAY.replace(day=1)
    end = date(start.year + (start.month + 1) // 12, (start.month + 1) % 12 + 1, 15)  # three billing months
    contract = await accepted_contract(async_client, fake_documents, [{"seq": 1, "trigger_type": "monthly", "percent": 100}], start=start, end=end)
    [schedule] = (await async_client.get(f"{BASE}/billing-schedules", params={"contract_id": contract["id"]})).json()
    amounts = [amount(line["amount"]) for line in schedule["lines"]]
    assert amounts == ["33333.33", "33333.33", "33333.34"]
