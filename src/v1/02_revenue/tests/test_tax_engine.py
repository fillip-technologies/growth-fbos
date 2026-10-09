"""
The pure tax engine, driven by the shipped packs. No database: a snapshot is built straight
from the pack files, so these tests also prove the packs say what the law (as researched) says.
"""
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

import pytest

from finance.errors import TaxConfigError
from finance.packs import load_packs
from finance.tax.context import (
    CustomerParty,
    LineInput,
    LowerDeductionCertificate,
    SupplierParty,
    TaxContext,
    WithholdingProfile,
)
from finance.tax.engine import calculate
from finance.tax.snapshot import ConfigSnapshot

TODAY = date(2026, 10, 9)
KARNATAKA, MAHARASHTRA, CHANDIGARH, DELHI = "29", "27", "04", "07"

Row = tuple[str, str, date, Optional[date], dict]


def pack_rows() -> list[Row]:
    return [
        (entry.kind, entry.code, entry.effective_from, entry.effective_to, dict(entry.data))
        for versions in load_packs().values()
        for pack in versions.values()
        for entry in pack.entries
    ]


def snapshot(
    on: date = TODAY,
    extra: Iterable[Row] = (),
    drop: Iterable[tuple[str, str]] = (),
    patch: Optional[dict[tuple[str, str], dict]] = None,
) -> ConfigSnapshot:
    dropped = set(drop)
    rows = []
    for kind, code, starts, ends, data in pack_rows():
        if (kind, code) in dropped:
            continue
        rows.append((kind, code, starts, ends, {**data, **(patch or {}).get((kind, code), {})}))
    return ConfigSnapshot.from_raw(on, 1, [*rows, *extra])


def context(
    lines: Iterable[LineInput],
    place: Optional[str] = KARNATAKA,
    country: str = "IN",
    registration_type: str = "registered",
    lut_valid: bool = False,
    on: date = TODAY,
    withholding: Optional[WithholdingProfile] = None,
    supplier_state: str = KARNATAKA,
) -> TaxContext:
    return TaxContext(
        tax_point_date=on,
        document_type="tax_invoice",
        currency="INR",
        supplier=SupplierParty(regime_code="IN-GST", country="IN", jurisdiction_code=supplier_state, lut_valid=lut_valid),
        customer=CustomerParty(country=country, registration_type=registration_type, place_of_supply=place, withholding=withholding),
        lines=tuple(lines),
    )


def line(category: str = "SVC_18", price: str = "100000", qty: str = "1", **extra) -> LineInput:
    return LineInput(line_no=extra.pop("line_no", 1), category_code=category, quantity=Decimal(qty), unit_price=Decimal(price), **extra)


def taxes(result) -> dict[str, Decimal]:
    return {tax.component_code: tax.amount for tax in result.taxes}


def test_same_state_splits_the_rate_into_central_and_state_gst():
    result = calculate(context([line(qty="2", discount_percent=Decimal(30))]), snapshot())
    assert result.supply_type == "intra_state"
    assert result.taxable_total == Decimal("140000.00")
    assert taxes(result) == {"CGST": Decimal("12600.00"), "SGST": Decimal("12600.00")}
    assert result.grand_total == Decimal("165200.00")


def test_other_state_charges_integrated_gst_at_the_full_rate():
    result = calculate(context([line()], place=MAHARASHTRA), snapshot())
    assert result.supply_type == "inter_state"
    assert taxes(result) == {"IGST": Decimal("18000.00")}
    assert result.grand_total == Decimal("118000.00")


def test_union_territory_without_legislature_charges_utgst_instead_of_sgst():
    result = calculate(context([line()], place=CHANDIGARH, supplier_state=CHANDIGARH), snapshot())
    assert taxes(result) == {"CGST": Decimal("9000.00"), "UTGST": Decimal("9000.00")}


def test_union_territory_with_legislature_charges_sgst():
    result = calculate(context([line()], place=DELHI, supplier_state=DELHI), snapshot())
    assert taxes(result) == {"CGST": Decimal("9000.00"), "SGST": Decimal("9000.00")}


def test_export_under_lut_is_zero_rated_with_a_note():
    result = calculate(context([line()], place=None, country="US", registration_type="overseas", lut_valid=True), snapshot())
    assert result.supply_type == "export"
    assert taxes(result) == {"IGST": Decimal("0.00")}
    assert result.grand_total == Decimal("100000.00")
    assert result.notes == ("Supply meant for export under LUT without payment of IGST",)


def test_export_without_lut_pays_igst():
    result = calculate(context([line()], place=None, country="US", registration_type="overseas"), snapshot())
    assert taxes(result) == {"IGST": Decimal("18000.00")}
    assert result.notes == ("Supply meant for export with payment of IGST",)


def test_sez_customer_under_lut_is_zero_rated_even_in_the_same_state():
    result = calculate(context([line()], registration_type="sez_unit", lut_valid=True), snapshot())
    assert taxes(result) == {"IGST": Decimal("0.00")}


def test_reverse_charge_shows_the_tax_but_does_not_charge_it():
    result = calculate(context([line("LEGAL_RCM")]), snapshot())
    assert result.reverse_charge is True
    assert {tax.behaviour for tax in result.taxes} == {"reverse_charge"}
    assert result.tax_total == Decimal("0")
    assert result.grand_total == Decimal("100000.00")
    assert result.notes == ("Tax payable on reverse charge by the recipient",)


def test_exempt_supply_has_no_tax_and_says_so():
    result = calculate(context([line("EXEMPT")]), snapshot())
    assert result.taxes == ()
    assert result.grand_total == Decimal("100000.00")
    assert result.notes == ("Exempt supply — no GST charged",)


def test_tax_inclusive_price_is_kept_exactly():
    result = calculate(context([line(price="118", price_includes_tax=True)]), snapshot())
    assert result.taxable_total == Decimal("100.00")
    assert taxes(result) == {"CGST": Decimal("9.00"), "SGST": Decimal("9.00")}
    assert result.grand_total == Decimal("118.00")


def test_tax_inclusive_rounding_paisa_stays_in_the_taxable_value():
    result = calculate(context([line(price="100", price_includes_tax=True)]), snapshot())
    assert result.grand_total == Decimal("100.00")
    assert result.taxable_total + result.tax_total == Decimal("100.00")


def test_rates_follow_the_tax_point_date_across_gst_2_0():
    before = calculate(context([line("GOODS_12")], on=date(2025, 9, 21)), snapshot(on=date(2025, 9, 21)))
    assert taxes(before) == {"CGST": Decimal("6000.00"), "SGST": Decimal("6000.00")}

    with pytest.raises(TaxConfigError) as retired:
        calculate(context([line("GOODS_12")], on=date(2025, 9, 22)), snapshot(on=date(2025, 9, 22)))
    assert retired.value.code == "TAX_CONFIG_NOT_EFFECTIVE"

    luxury = calculate(context([line("GOODS_40")], on=date(2025, 9, 22)), snapshot(on=date(2025, 9, 22)))
    assert taxes(luxury) == {"CGST": Decimal("20000.00"), "SGST": Decimal("20000.00")}


def test_line_level_and_document_level_rounding_differ_as_configured():
    lines = [line(price="0.05", line_no=n) for n in (1, 2, 3)]
    per_line = calculate(context(lines), snapshot())
    assert taxes(per_line)["CGST"] == Decimal("0.00")

    per_document = calculate(context(lines), snapshot(patch={("regime", "IN-GST"): {"rounding_level": "document"}}))
    assert taxes(per_document)["CGST"] == Decimal("0.01")


def test_document_round_off_rounds_the_grand_total_and_shows_the_difference():
    result = calculate(context([line(price="100.40")]), snapshot(patch={("regime", "IN-GST"): {"document_round_off": "1"}}))
    assert result.grand_total == Decimal("118.00")
    assert result.round_off == Decimal("-0.48")
    assert str(result.grand_total) == "118.00"


def test_withholding_follows_the_act_in_force_and_finds_old_section_numbers():
    profile = WithholdingProfile(section_code="194J")
    old_act = calculate(context([line()], on=date(2026, 3, 31), withholding=profile), snapshot(on=date(2026, 3, 31)))
    assert old_act.withholding[0].statute_ref == "Income-tax Act 1961, s.194J(b)"
    assert old_act.withholding[0].payment_code is None

    new_act = calculate(context([line()], withholding=profile), snapshot())
    assert new_act.withholding[0].statute_ref == "Income-tax Act 2025, s.393(1)"
    assert new_act.withholding[0].payment_code == "1027"
    # TDS is on the value before GST, and does not change what is invoiced.
    assert new_act.withholding[0].amount == Decimal("10000.00")
    assert new_act.grand_total == Decimal("118000.00")
    assert new_act.net_receivable == Decimal("108000.00")


def test_withholding_rate_depends_on_deductee_pan_and_certificate():
    contractor = WithholdingProfile(section_code="CONTRACTOR", deductee_type="individual")
    result = calculate(context([line()], withholding=contractor), snapshot())
    assert (result.withholding[0].percent, result.withholding[0].payment_code) == (Decimal(1), "1023")

    no_pan = WithholdingProfile(section_code="PROFESSIONAL_FEES", has_pan=False)
    assert calculate(context([line()], withholding=no_pan), snapshot()).withholding[0].percent == Decimal(20)

    certificate = LowerDeductionCertificate("LDC-1", Decimal(2), date(2026, 4, 1), date(2027, 3, 31))
    lowered = WithholdingProfile(section_code="PROFESSIONAL_FEES", certificates=(certificate,))
    lowered_result = calculate(context([line()], withholding=lowered), snapshot())
    assert lowered_result.withholding[0].amount == Decimal("2000.00")
    assert lowered_result.withholding[0].certificate_no == "LDC-1"


def test_a_line_no_rule_covers_is_an_error_not_a_guess():
    with pytest.raises(TaxConfigError) as missing:
        calculate(context([line()], place=MAHARASHTRA), snapshot(drop=[("rule", "INTER_STATE")]))
    assert missing.value.code == "TAX_RULE_NOT_FOUND"
    assert missing.value.meta["facts"]["supply_type"] == "inter_state"


def test_two_rules_matching_with_the_same_priority_is_an_error():
    duplicate = ("rule", "INTRA_COPY", date(2017, 7, 1), None, {
        "regime": "IN-GST", "priority": 40, "when": {"supply_type": ["intra_state"]},
        "then": [{"component": "IGST", "rate_from_category": True}],
    })
    with pytest.raises(TaxConfigError) as ambiguous:
        calculate(context([line()]), snapshot(extra=[duplicate]))
    assert ambiguous.value.code == "TAX_RULE_AMBIGUOUS"


def test_unknown_or_missing_place_of_supply_is_reported():
    with pytest.raises(TaxConfigError) as missing:
        calculate(context([line()], place=None), snapshot())
    assert missing.value.code == "PLACE_OF_SUPPLY_UNKNOWN"

    with pytest.raises(TaxConfigError) as unknown:
        calculate(context([line()], place="99"), snapshot())
    assert unknown.value.code == "JURISDICTION_UNKNOWN"


def test_another_country_with_compound_tax_needs_no_code():
    """A Canada/Quebec-style compound tax, configured as data only."""
    start = date(2020, 1, 1)
    rows: list[Row] = [
        ("regime", "CA-QC", start, None, {"name": "Quebec sales tax", "country": "CA", "kind": "indirect"}),
        ("component", "GST_CA", start, None, {"regime": "CA-QC", "label": "GST", "sequence": 10}),
        ("component", "QST", start, None, {"regime": "CA-QC", "label": "QST", "sequence": 20, "base": "taxable_plus_previous"}),
        ("rate", "CA_GST_5", start, None, {"percent": "5"}),
        ("rate", "QC_QST", start, None, {"percent": "9.975"}),
        ("category", "CA_STANDARD", start, None, {"regime": "CA-QC", "name": "Standard", "treatment": "taxable", "rate": "CA_GST_5"}),
        ("rule", "CA_DOMESTIC", start, None, {
            "regime": "CA-QC", "priority": 10, "when": {"supply_type": ["intra_state"]},
            "then": [{"component": "GST_CA", "rate": "CA_GST_5"}, {"component": "QST", "rate": "QC_QST"}],
        }),
    ]
    quebec = TaxContext(
        tax_point_date=TODAY, document_type="tax_invoice", currency="CAD",
        supplier=SupplierParty(regime_code="CA-QC", country="CA", jurisdiction_code=None),
        customer=CustomerParty(country="CA", registration_type="registered"),
        lines=(line("CA_STANDARD", price="1000"),),
    )
    result = calculate(quebec, ConfigSnapshot.from_raw(TODAY, 1, rows))
    assert taxes(result) == {"GST_CA": Decimal("50.00"), "QST": Decimal("104.74")}
    assert result.grand_total == Decimal("1154.74")
