"""
What each kind of tax configuration entry may hold.

Every entry is `(kind, code, effective_from, effective_to, data)`. `data` is validated here,
whether it comes from a pack file or from the API, so the engine can trust it. Adding a kind
means adding a model to `KIND_SCHEMAS`; adding entries of an existing kind is configuration.
"""

from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from finance.errors import TaxConfigError


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RegistrationSlice(_Strict):
    """Where a registration number spells the jurisdiction (a GSTIN's first two characters)."""

    start: int = Field(..., ge=0)
    length: int = Field(..., ge=1)


class DocumentNumberRules(_Strict):
    max_length: Optional[int] = Field(None, ge=1)
    pattern: Optional[str] = None


class RegimeData(_Strict):
    name: str
    country: str = Field(..., min_length=2, max_length=2)
    kind: Literal["indirect", "withholding"]
    rounding_mode: Literal["half_up", "half_even", "up", "down"] = "half_up"
    # line: each tax amount is rounded on its line; document: per-component totals are rounded once.
    rounding_level: Literal["line", "document"] = "line"
    # Grand total rounded to a multiple of this (e.g. 1 = nearest rupee); none = no round-off line.
    document_round_off: Optional[Decimal] = Field(None, gt=0)
    fiscal_year_start: str = Field("01-01", pattern=r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
    registration_validator: Optional[str] = None
    registration_jurisdiction: Optional[RegistrationSlice] = None
    document_number: DocumentNumberRules = DocumentNumberRules()
    party_registration_types: list[str] = []
    deductee_types: list[str] = []
    default_category: Optional[str] = None
    provider: str = "internal"


class ComponentData(_Strict):
    regime: str
    label: str
    # added: increases the total; withheld: payer keeps it back; collected: seller collects on top.
    behaviour: Literal["added", "withheld", "collected"] = "added"
    # taxable_plus_previous: compound tax, its base includes components with a lower sequence.
    base: Literal["taxable_value", "taxable_plus_previous"] = "taxable_value"
    sequence: int = 10
    ledger_account: Optional[str] = None
    return_box: Optional[str] = None


class RateData(_Strict):
    percent: Decimal = Field(..., ge=0, le=1000)
    notification: Optional[str] = None


class CategoryData(_Strict):
    regime: str
    name: str
    treatment: Literal["taxable", "exempt", "nil_rated", "non_taxable"]
    supply_kind: Literal["service", "goods"] = "service"
    rate: Optional[str] = None
    classification: Optional[str] = None
    # The recipient pays this supply's tax (reverse charge), whoever the customer is.
    reverse_charge: bool = False

    @model_validator(mode="after")
    def taxable_needs_a_rate(self) -> "CategoryData":
        if self.treatment == "taxable" and not self.rate:
            raise ValueError("a taxable category needs a rate")
        return self


SupplyType = Literal["intra_state", "inter_state", "export"]


class RuleConditions(_Strict):
    """
    The facts a rule can test. Every set condition must hold; unset ones are ignored. New
    entries never need code; a new kind of fact does (it has to be added here and to the engine).
    """

    supply_type: Optional[list[SupplyType]] = None
    category: Optional[list[str]] = None
    category_treatment: Optional[list[str]] = None
    customer_registration_type: Optional[list[str]] = None
    jurisdiction_kind: Optional[list[str]] = None
    place_of_supply: Optional[list[str]] = None
    customer_country: Optional[list[str]] = None
    document_type: Optional[list[str]] = None
    reverse_charge: Optional[bool] = None
    lut_valid: Optional[bool] = None


class RuleOutput(_Strict):
    component: str
    rate: Optional[str] = None
    percent: Optional[Decimal] = Field(None, ge=0, le=1000)
    rate_from_category: bool = False
    # Share of the rate this component carries: 0.5 splits one 18% rate into 9% + 9%.
    split: Decimal = Field(Decimal(1), gt=0, le=1)
    behaviour: Optional[Literal["added", "reverse_charge"]] = None

    @model_validator(mode="after")
    def exactly_one_rate_source(self) -> "RuleOutput":
        sources = [self.rate is not None, self.percent is not None, self.rate_from_category]
        if sum(sources) != 1:
            raise ValueError("give exactly one of rate, percent or rate_from_category")
        return self


class RuleData(_Strict):
    regime: str
    priority: int
    when: RuleConditions = RuleConditions()
    then: list[RuleOutput] = []
    note: Optional[str] = None


class JurisdictionData(_Strict):
    regime: str
    name: str
    kind: str = Field(..., min_length=1)


class Threshold(_Strict):
    amount: Decimal = Field(..., gt=0)
    basis: Literal["per_payment", "monthly", "annual"]


class WithholdingSectionData(_Strict):
    regime: str
    nature: str
    statute_ref: str
    aliases: list[str] = []
    # Percent by deductee type; "default" covers every type not listed.
    rates: dict[str, Decimal]
    payment_codes: dict[str, str] = {}
    no_pan_percent: Optional[Decimal] = Field(None, ge=0, le=100)
    thresholds: list[Threshold] = []
    base: Literal["taxable_value", "gross"] = "taxable_value"
    notification: Optional[str] = None

    @field_validator("rates")
    @classmethod
    def rates_cover_everyone(cls, rates: dict[str, Decimal]) -> dict[str, Decimal]:
        if "default" not in rates:
            raise ValueError("rates need a 'default' entry")
        if any(percent < 0 or percent > 100 for percent in rates.values()):
            raise ValueError("rates are percentages between 0 and 100")
        return rates


class DeadlineRule(_Strict):
    # after_fy_end: a calendar day after the end of the document's fiscal year (month 11 day 30 =
    # 30 November); days_after: a number of days after one of the document's dates.
    type: Literal["after_fy_end", "days_after"]
    month: Optional[int] = Field(None, ge=1, le=12)
    day: Optional[int] = Field(None, ge=1, le=31)
    field: Optional[Literal["issue_date", "tax_point_date"]] = None
    days: Optional[int] = Field(None, ge=0)

    @model_validator(mode="after")
    def complete_for_its_type(self) -> "DeadlineRule":
        if self.type == "after_fy_end" and (self.month is None or self.day is None):
            raise ValueError("after_fy_end needs month and day")
        if self.type == "days_after" and (self.field is None or self.days is None):
            raise ValueError("days_after needs field and days")
        return self


class DeadlineData(_Strict):
    regime: str
    description: str
    applies_to: list[str]
    rule: DeadlineRule
    severity: Literal["warn", "block"] = "warn"


class SeriesTemplateData(_Strict):
    prefix: str = Field(..., min_length=1, max_length=20)
    # Python format string with {prefix}, {fy}, {fy_short}, {year}, {jurisdiction} and {seq},
    # e.g. "{prefix}/{fy_short}/{seq:06d}".
    format: str = Field(..., min_length=1, max_length=100)
    reset: Literal["fiscal_year", "calendar_year", "never"] = "fiscal_year"

    @field_validator("format")
    @classmethod
    def format_renders(cls, template: str) -> str:
        if "{seq" not in template:
            raise ValueError("the format must contain {seq}")
        try:
            template.format(prefix="P", fy="2000-01", fy_short="00-01", year=2000, jurisdiction="00", seq=1)
        except (KeyError, IndexError, ValueError) as error:
            raise ValueError(f"the format does not render: {error}") from error
        return template


KIND_SCHEMAS: dict[str, type[_Strict]] = {
    "regime": RegimeData,
    "component": ComponentData,
    "rate": RateData,
    "category": CategoryData,
    "rule": RuleData,
    "jurisdiction": JurisdictionData,
    "withholding_section": WithholdingSectionData,
    "deadline": DeadlineData,
    "series_template": SeriesTemplateData,
}

CONFIG_KINDS = tuple(KIND_SCHEMAS)


def validate_entry_data(kind: str, data: dict) -> _Strict:
    schema = KIND_SCHEMAS.get(kind)
    if schema is None:
        raise TaxConfigError("TAX_CONFIG_KIND_UNKNOWN", f"Unknown tax configuration kind '{kind}'", meta={"kinds": list(CONFIG_KINDS)})
    try:
        return schema.model_validate(data)
    except ValidationError as error:
        raise TaxConfigError(
            "TAX_CONFIG_INVALID",
            f"The {kind.replace('_', ' ')} entry is not valid",
            meta={"kind": kind, "errors": error.errors(include_url=False, include_context=False, include_input=False)},
        ) from error
