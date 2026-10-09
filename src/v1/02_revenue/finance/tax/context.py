"""What the engine is asked: who supplies whom, where, when, and which lines."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from finance.money import ZERO


@dataclass(frozen=True)
class SupplierParty:
    regime_code: str
    country: str
    jurisdiction_code: Optional[str]
    registration_no: Optional[str] = None
    registration_type: str = "regular"
    lut_valid: bool = False


@dataclass(frozen=True)
class LowerDeductionCertificate:
    certificate_no: str
    percent: Decimal
    valid_from: date
    valid_to: date

    def covers(self, day: date) -> bool:
        return self.valid_from <= day <= self.valid_to


@dataclass(frozen=True)
class WithholdingProfile:
    section_code: str
    deductee_type: str = "default"
    has_pan: bool = True
    certificates: tuple[LowerDeductionCertificate, ...] = ()


@dataclass(frozen=True)
class CustomerParty:
    country: str
    registration_type: str
    place_of_supply: Optional[str] = None
    registration_no: Optional[str] = None
    withholding: Optional[WithholdingProfile] = None


@dataclass(frozen=True)
class LineInput:
    line_no: int
    category_code: str
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal = ZERO
    discount_percent: Decimal = ZERO
    price_includes_tax: bool = False
    classification_code: Optional[str] = None


@dataclass(frozen=True)
class TaxContext:
    tax_point_date: date
    document_type: str
    currency: str
    supplier: SupplierParty
    customer: CustomerParty
    lines: tuple[LineInput, ...] = field(default_factory=tuple)
    place_of_supply_override: Optional[str] = None
    reverse_charge: bool = False
