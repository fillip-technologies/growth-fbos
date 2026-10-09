"""What the engine answers. Documents store these values as their frozen tax snapshot."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

# Behaviours that count toward what the customer is charged.
CHARGED_BEHAVIOURS = ("added", "collected")


@dataclass(frozen=True)
class TaxLine:
    component_code: str
    label: str
    behaviour: str  # added | collected | reverse_charge
    rate_code: Optional[str]
    percent: Decimal
    base: Decimal
    amount: Decimal
    rule_code: str
    # Reporting bucket from the component (e.g. "cgst"): returns, and the legacy cgst/sgst/igst fields.
    return_box: Optional[str] = None


@dataclass(frozen=True)
class LineResult:
    line_no: int
    category_code: str
    classification_code: Optional[str]
    gross: Decimal
    discount: Decimal
    taxable_value: Decimal
    taxes: tuple[TaxLine, ...]

    @property
    def charged_tax(self) -> Decimal:
        return sum((tax.amount for tax in self.taxes if tax.behaviour in CHARGED_BEHAVIOURS), Decimal(0))

    @property
    def effective_percent(self) -> Decimal:
        return sum((tax.percent for tax in self.taxes if tax.behaviour in CHARGED_BEHAVIOURS), Decimal(0))

    @property
    def line_total(self) -> Decimal:
        return self.taxable_value + self.charged_tax


@dataclass(frozen=True)
class ComponentTotal:
    component_code: str
    label: str
    behaviour: str
    percent: Decimal
    amount: Decimal
    return_box: Optional[str] = None


@dataclass(frozen=True)
class Withholding:
    section_code: str
    statute_ref: str
    payment_code: Optional[str]
    percent: Decimal
    base: Decimal
    amount: Decimal
    certificate_no: Optional[str] = None


@dataclass(frozen=True)
class TaxResult:
    regime_code: str
    config_revision: int
    supply_type: str
    place_of_supply: Optional[str]
    reverse_charge: bool
    lines: tuple[LineResult, ...]
    subtotal: Decimal
    discount_total: Decimal
    taxable_total: Decimal
    taxes: tuple[ComponentTotal, ...]
    tax_total: Decimal
    round_off: Decimal
    grand_total: Decimal
    withholding: tuple[Withholding, ...]
    net_receivable: Decimal
    notes: tuple[str, ...]

    @property
    def withheld_total(self) -> Decimal:
        return sum((item.amount for item in self.withholding), Decimal(0))
