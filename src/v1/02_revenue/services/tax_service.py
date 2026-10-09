"""
The bridge between documents and the tax engine.

Services describe a document (customer, lines, date); this module works out the supplier
registration, the customer's tax facts and each line's category from the database, runs the
engine on the configuration in effect that day, and stores or reads the frozen tax lines.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from typing import Any, Iterable, Optional
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from finance import policies
from finance.errors import FinanceNotFoundError, TaxConfigError
from finance.money import ZERO, to_decimal
from finance.tax.config_schema import RegimeData
from finance.tax.context import (
    CustomerParty,
    LineInput,
    LowerDeductionCertificate,
    SupplierParty,
    TaxContext,
    WithholdingProfile,
)
from finance.tax.engine import calculate
from finance.tax.registrations import jurisdiction_from_registration
from finance.tax.result import TaxResult
from finance.tax.snapshot import ConfigSnapshot
from finance.tax.store import load_snapshot
from models.client import Client
from models.client_tax_profile import ClientTaxProfile
from models.document_tax import DocumentTaxLine
from models.finance_settings import FinanceSettings
from models.tax_registration import OrgTaxRegistration

# The base vocabulary for customers without a tax profile; packs list the full set per regime.
REGISTERED, UNREGISTERED, OVERSEAS = "registered", "unregistered", "overseas"


@dataclass(frozen=True)
class DocumentLineSpec:
    """A line as a document describes it, before its tax category is settled."""

    line_no: int
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal = ZERO
    discount_percent: Decimal = ZERO
    category_code: Optional[str] = None
    # A bare GST percentage from an older client or offering: mapped to a category with that rate.
    legacy_rate: Optional[Decimal] = None
    classification_code: Optional[str] = None
    price_includes_tax: bool = False


@dataclass(frozen=True)
class TaxCalculation:
    result: TaxResult
    snapshot: ConfigSnapshot
    registration: OrgTaxRegistration
    regime: RegimeData
    settings: FinanceSettings


# ---------------------------------------------------------------- parties


def parse_address(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def legacy_rate(text: Optional[str]) -> Optional[Decimal]:
    """'18', '18.0' or 'GST18' as a percentage; None when it isn't one."""
    if not text:
        return None
    cleaned = text.strip().upper().removeprefix("GST").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


async def resolve_registration(
    session: AsyncSession, org_id: uuid.UUID, registration_id: Optional[uuid.UUID], on: date
) -> OrgTaxRegistration:
    if registration_id is not None:
        chosen = await session.get(OrgTaxRegistration, registration_id)
        if chosen is None or chosen.organization_id != org_id:
            raise FinanceNotFoundError("TAX_REGISTRATION_NOT_FOUND", f"Tax registration '{registration_id}' not found")
        if not chosen.active_on(on):
            raise TaxConfigError(
                "TAX_REGISTRATION_INACTIVE", f"Tax registration {chosen.registration_no} is not active on {on.isoformat()}."
            )
        return chosen

    rows = await session.execute(select(OrgTaxRegistration).where(OrgTaxRegistration.organization_id == org_id))
    active = [registration for registration in rows.scalars().all() if registration.active_on(on)]
    defaults = [registration for registration in active if registration.is_default]
    if len(defaults) == 1:
        return defaults[0]
    if len(active) == 1:
        return active[0]
    if not active:
        raise TaxConfigError(
            "SUPPLIER_REGISTRATION_REQUIRED",
            "Add your organization's tax registration (GSTIN) in the tax settings before billing.",
        )
    raise TaxConfigError(
        "TAX_REGISTRATION_CHOICE_REQUIRED",
        "The organization has several tax registrations and none is the default. Choose one for this document.",
    )


def supplier_party(registration: OrgTaxRegistration, regime: RegimeData, on: date) -> SupplierParty:
    return SupplierParty(
        regime_code=registration.regime_code,
        country=regime.country,
        jurisdiction_code=registration.jurisdiction_code or jurisdiction_from_registration(regime, registration.registration_no),
        registration_no=registration.registration_no,
        registration_type=registration.registration_type,
        lut_valid=registration.lut_valid_on(on),
    )


def _certificates(raw: Iterable[dict]) -> tuple[LowerDeductionCertificate, ...]:
    return tuple(
        LowerDeductionCertificate(
            certificate_no=item["certificate_no"],
            percent=to_decimal(item["percent"]),
            valid_from=date.fromisoformat(item["valid_from"]),
            valid_to=date.fromisoformat(item["valid_to"]),
        )
        for item in raw
    )


def customer_party(
    client: Client,
    profile: Optional[ClientTaxProfile],
    regime: RegimeData,
    supplier: SupplierParty,
    deductee_type: Optional[str] = None,
) -> CustomerParty:
    """
    The customer's tax facts. When it withholds TDS, the deductee is the organization itself:
    its own type and PAN (inside its registration number) decide the rate, not the customer's.
    """
    address = parse_address(client.billing_address)
    registration_no = (profile.registration_no if profile else None) or client.gstin
    country = ((profile.country if profile else None) or address.get("country") or supplier.country).upper()

    registration_type = profile.registration_type if profile else None
    if not registration_type:
        if country != supplier.country.upper():
            registration_type = OVERSEAS
        else:
            registration_type = REGISTERED if registration_no else UNREGISTERED

    domestic = country == supplier.country.upper()
    place = profile.place_of_supply if profile else None
    if not place and domestic:
        # A foreign address's region is not a place of supply in this regime.
        place = address.get("state_code") or jurisdiction_from_registration(regime, registration_no)

    withholding = None
    if profile is not None and profile.tds_section_code:
        withholding = WithholdingProfile(
            section_code=profile.tds_section_code,
            deductee_type=deductee_type or "default",
            has_pan=bool(supplier.registration_no),
            certificates=_certificates(profile.lower_deduction_certificates or []),
        )
    return CustomerParty(
        country=country,
        registration_type=registration_type,
        place_of_supply=str(place) if place else None,
        registration_no=registration_no,
        withholding=withholding,
    )


# ---------------------------------------------------------------- categories


def category_for_rate(snapshot: ConfigSnapshot, regime_code: str, percent: Decimal, preferred: Optional[str] = None) -> str:
    """
    The plain category charging `percent`, for lines that only give a rate. Reverse-charge
    categories never match (a bare rate doesn't say the customer pays the tax); the preferred
    (default) category wins, then services, then the lowest code.
    """
    matches = []
    for code, category in snapshot.categories(regime_code):
        if category.treatment != "taxable" or category.reverse_charge or not category.rate:
            continue
        if snapshot.find("rate", category.rate) is None:
            continue
        if snapshot.rate(category.rate).percent == percent:
            matches.append((code != preferred, category.supply_kind != "service", code))
    if not matches:
        raise TaxConfigError(
            "TAX_CATEGORY_FOR_RATE_NOT_FOUND",
            f"No tax category charges {percent}% on {snapshot.as_of.isoformat()}. Choose a tax category instead of a rate.",
            meta={"percent": str(percent)},
        )
    return min(matches)[2]


def resolve_category(
    snapshot: ConfigSnapshot, regime_code: str, regime: RegimeData, settings: FinanceSettings, line: DocumentLineSpec
) -> str:
    if line.category_code:
        return line.category_code
    fallback = policies.default_category(settings, regime)
    if line.legacy_rate is not None:
        return category_for_rate(snapshot, regime_code, line.legacy_rate, preferred=fallback)
    if fallback:
        return fallback
    raise TaxConfigError("TAX_CATEGORY_REQUIRED", f"Line {line.line_no} needs a tax category.", meta={"line_no": line.line_no})


# ---------------------------------------------------------------- calculation


async def calculate_document(
    session: AsyncSession,
    org_id: uuid.UUID,
    client: Client,
    lines: list[DocumentLineSpec],
    tax_point_date: date,
    document_type: str,
    currency: str = "INR",
    registration_id: Optional[uuid.UUID] = None,
    place_of_supply: Optional[str] = None,
) -> TaxCalculation:
    settings = await policies.load_settings(session, org_id)
    snapshot = await load_snapshot(session, org_id, tax_point_date)
    registration = await resolve_registration(session, org_id, registration_id, tax_point_date)
    regime = snapshot.regime(registration.regime_code)
    supplier = supplier_party(registration, regime, tax_point_date)
    profile = await session.get(ClientTaxProfile, client.id)
    customer = customer_party(client, profile, regime, supplier, settings.deductee_type)

    engine_lines = tuple(
        LineInput(
            line_no=line.line_no,
            category_code=resolve_category(snapshot, registration.regime_code, regime, settings, line),
            quantity=line.quantity,
            unit_price=line.unit_price,
            discount_amount=line.discount_amount,
            discount_percent=line.discount_percent,
            price_includes_tax=line.price_includes_tax,
            classification_code=line.classification_code,
        )
        for line in lines
    )
    context = TaxContext(
        tax_point_date=tax_point_date,
        document_type=document_type,
        currency=currency,
        supplier=supplier,
        customer=customer,
        lines=engine_lines,
        place_of_supply_override=place_of_supply,
    )
    return TaxCalculation(calculate(context, snapshot), snapshot, registration, regime, settings)


def registration_snapshot(registration: OrgTaxRegistration) -> dict[str, Any]:
    return {
        "registration_id": str(registration.id),
        "regime_code": registration.regime_code,
        "registration_no": registration.registration_no,
        "legal_name": registration.legal_name,
        "trade_name": registration.trade_name,
        "jurisdiction_code": registration.jurisdiction_code,
        "address": registration.address,
    }


def withholding_json(result: TaxResult) -> list[dict[str, Any]]:
    return [
        {
            "section_code": item.section_code,
            "statute_ref": item.statute_ref,
            "payment_code": item.payment_code,
            "percent": str(item.percent),
            "base": str(item.base),
            "amount": str(item.amount),
            "certificate_no": item.certificate_no,
        }
        for item in result.withholding
    ]


# ---------------------------------------------------------------- stored tax lines


async def replace_tax_lines(
    session: AsyncSession, org_id: uuid.UUID, document_type: str, document_id: uuid.UUID, result: TaxResult
) -> None:
    await session.execute(
        delete(DocumentTaxLine).where(
            DocumentTaxLine.document_type == document_type, DocumentTaxLine.document_id == document_id
        )
    )
    for line in result.lines:
        for tax in line.taxes:
            session.add(DocumentTaxLine(
                organization_id=org_id, document_type=document_type, document_id=document_id, line_no=line.line_no,
                component_code=tax.component_code, label=tax.label, behaviour=tax.behaviour, rate_code=tax.rate_code,
                rate_percent=tax.percent, base_amount=tax.base, tax_amount=tax.amount, rule_code=tax.rule_code,
                return_box=tax.return_box,
            ))
    await session.flush()


async def copy_tax_lines(
    session: AsyncSession, org_id: uuid.UUID, document_type: str, source_id: uuid.UUID, target_id: uuid.UUID
) -> list[DocumentTaxLine]:
    copies = [
        DocumentTaxLine(
            organization_id=org_id, document_type=document_type, document_id=target_id, line_no=line.line_no,
            component_code=line.component_code, label=line.label, behaviour=line.behaviour, rate_code=line.rate_code,
            rate_percent=line.rate_percent, base_amount=line.base_amount, tax_amount=line.tax_amount,
            rule_code=line.rule_code, return_box=line.return_box,
        )
        for line in await load_tax_lines(session, document_type, [source_id])
    ]
    session.add_all(copies)
    await session.flush()
    return copies


async def load_tax_lines(
    session: AsyncSession, document_type: str, document_ids: list[uuid.UUID]
) -> list[DocumentTaxLine]:
    if not document_ids:
        return []
    rows = await session.execute(
        select(DocumentTaxLine)
        .where(DocumentTaxLine.document_type == document_type, DocumentTaxLine.document_id.in_(document_ids))
        .order_by(DocumentTaxLine.line_no, DocumentTaxLine.component_code)
    )
    return list(rows.scalars().all())


def group_by_document(lines: list[DocumentTaxLine]) -> dict[uuid.UUID, list[DocumentTaxLine]]:
    grouped: dict[uuid.UUID, list[DocumentTaxLine]] = defaultdict(list)
    for line in lines:
        grouped[line.document_id].append(line)
    return grouped


@dataclass(frozen=True)
class StoredTaxTotal:
    component_code: str
    label: str
    behaviour: str
    percent: Decimal
    amount: Decimal
    return_box: Optional[str]


def totals_of(lines: list[DocumentTaxLine]) -> list[StoredTaxTotal]:
    grouped: dict[tuple[str, str, str, Decimal, Optional[str]], Decimal] = {}
    for line in lines:
        key = (line.component_code, line.label, line.behaviour, to_decimal(line.rate_percent), line.return_box)
        grouped[key] = grouped.get(key, ZERO) + to_decimal(line.tax_amount)
    return [
        StoredTaxTotal(component_code=code, label=label, behaviour=behaviour, percent=percent, amount=amount, return_box=box)
        for (code, label, behaviour, percent, box), amount in grouped.items()
    ]


def legacy_split(totals: Iterable[StoredTaxTotal]) -> dict[str, Decimal]:
    """The older cgst/sgst/igst fields, filled from each component's reporting bucket."""
    split = {"cgst": ZERO, "sgst": ZERO, "igst": ZERO}
    for total in totals:
        if total.behaviour in ("added", "collected") and total.return_box in split:
            split[total.return_box] += total.amount
    return split
