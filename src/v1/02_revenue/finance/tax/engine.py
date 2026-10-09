"""
The tax engine: `calculate(context, snapshot) -> TaxResult`.

Pure: no database, no clock, no settings. Everything it knows comes from the context (who,
where, when, what) and the configuration snapshot in effect on the tax point date. It never
guesses: a line no rule covers is an error (`TAX_RULE_NOT_FOUND`), never a silent rate.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from finance.errors import TaxConfigError, rule_not_found
from finance.money import HUNDRED, ZERO, round_money, round_to_increment
from finance.tax.config_schema import CategoryData, ComponentData, RegimeData, RuleData, RuleOutput
from finance.tax.context import LineInput, TaxContext
from finance.tax.result import CHARGED_BEHAVIOURS, ComponentTotal, LineResult, TaxLine, TaxResult, Withholding
from finance.tax.snapshot import ConfigSnapshot


@dataclass(frozen=True)
class _ResolvedOutput:
    component_code: str
    component: ComponentData
    rate_code: Optional[str]
    percent: Decimal
    behaviour: str


@dataclass(frozen=True)
class _ComputedLine:
    result: LineResult
    raw_amounts: tuple[Decimal, ...]  # unrounded, for document-level rounding
    note: Optional[str]


@dataclass(frozen=True)
class _Situation:
    """Facts shared by every line of the document."""

    regime_code: str
    regime: RegimeData
    supply_type: str
    place_of_supply: Optional[str]
    jurisdiction_kind: Optional[str]


def calculate(context: TaxContext, snapshot: ConfigSnapshot) -> TaxResult:
    situation = _situation(context, snapshot)
    computed = [_calculate_line(line, context, situation, snapshot) for line in context.lines]
    line_results = tuple(line.result for line in computed)

    taxes = _component_totals(computed, situation.regime, context.currency)
    taxable_total = sum((line.taxable_value for line in line_results), ZERO)
    tax_total = sum((tax.amount for tax in taxes if tax.behaviour in CHARGED_BEHAVIOURS), ZERO)
    unrounded_grand_total = taxable_total + tax_total
    grand_total = unrounded_grand_total
    if situation.regime.document_round_off is not None:
        grand_total = round_money(
            round_to_increment(unrounded_grand_total, situation.regime.document_round_off, situation.regime.rounding_mode),
            context.currency,
        )

    withholding = _withholding(context, snapshot, taxable_total, grand_total)
    withheld = sum((item.amount for item in withholding), ZERO)
    return TaxResult(
        regime_code=situation.regime_code,
        config_revision=snapshot.revision,
        supply_type=situation.supply_type,
        place_of_supply=situation.place_of_supply,
        reverse_charge=context.reverse_charge or any(
            tax.behaviour == "reverse_charge" for line in line_results for tax in line.taxes
        ),
        lines=line_results,
        subtotal=sum((line.gross for line in line_results), ZERO),
        discount_total=sum((line.discount for line in line_results), ZERO),
        taxable_total=taxable_total,
        taxes=taxes,
        tax_total=tax_total,
        round_off=grand_total - unrounded_grand_total,
        grand_total=grand_total,
        withholding=withholding,
        net_receivable=grand_total - withheld,
        notes=tuple(dict.fromkeys(line.note for line in computed if line.note)),
    )


def resolve_supply_type(context: TaxContext, place_of_supply: Optional[str]) -> str:
    supplier, customer = context.supplier, context.customer
    if customer.country.upper() != supplier.country.upper():
        return "export"
    if place_of_supply is None and supplier.jurisdiction_code is None:
        # A regime without sub-national jurisdictions: every domestic supply is local.
        return "intra_state"
    if place_of_supply is None:
        raise TaxConfigError(
            "PLACE_OF_SUPPLY_UNKNOWN",
            "The place of supply could not be worked out. Set it on the document or on the customer's tax profile.",
        )
    if supplier.jurisdiction_code is None:
        raise TaxConfigError(
            "SUPPLIER_JURISDICTION_UNKNOWN", "The supplier's tax registration has no jurisdiction (state) set."
        )
    return "intra_state" if place_of_supply == supplier.jurisdiction_code else "inter_state"


def _situation(context: TaxContext, snapshot: ConfigSnapshot) -> _Situation:
    regime_code = context.supplier.regime_code
    regime = snapshot.regime(regime_code)
    if regime.provider != "internal":
        raise TaxConfigError(
            "TAX_PROVIDER_UNAVAILABLE",
            f"Regime '{regime_code}' is set to use the '{regime.provider}' provider, which is not connected.",
        )
    place = context.place_of_supply_override or context.customer.place_of_supply
    supply_type = resolve_supply_type(context, place)
    jurisdiction_kind = None
    if supply_type != "export" and place is not None:
        jurisdiction = snapshot.jurisdiction(regime_code, place)
        if jurisdiction is None:
            raise TaxConfigError(
                "JURISDICTION_UNKNOWN",
                f"Place of supply '{place}' is not a jurisdiction of {regime.name}.",
                meta={"place_of_supply": place, "regime": regime_code},
            )
        jurisdiction_kind = jurisdiction.kind
    return _Situation(regime_code, regime, supply_type, place, jurisdiction_kind)


def _line_facts(line: LineInput, category: CategoryData, context: TaxContext, situation: _Situation) -> dict[str, Any]:
    return {
        "supply_type": situation.supply_type,
        "category": line.category_code,
        "category_treatment": category.treatment,
        "customer_registration_type": context.customer.registration_type,
        "jurisdiction_kind": situation.jurisdiction_kind,
        "place_of_supply": situation.place_of_supply,
        "customer_country": context.customer.country.upper(),
        "document_type": context.document_type,
        "reverse_charge": context.reverse_charge or category.reverse_charge,
        "lut_valid": context.supplier.lut_valid,
    }


def conditions_hold(rule: RuleData, facts: dict[str, Any]) -> bool:
    for fact, expected in rule.when.model_dump(exclude_none=True).items():
        actual = facts.get(fact)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def select_rule(rules: list[tuple[str, RuleData]], facts: dict[str, Any], line_no: int) -> tuple[str, RuleData]:
    matching = [(code, rule) for code, rule in rules if conditions_hold(rule, facts)]
    if not matching:
        raise rule_not_found(line_no, facts)
    top_priority = max(rule.priority for _, rule in matching)
    best = [(code, rule) for code, rule in matching if rule.priority == top_priority]
    if len(best) > 1:
        raise TaxConfigError(
            "TAX_RULE_AMBIGUOUS",
            f"Rules {', '.join(code for code, _ in best)} all apply to line {line_no} with the same priority.",
            meta={"line_no": line_no, "rules": [code for code, _ in best]},
        )
    return best[0]


def _resolve_output(output: RuleOutput, category: CategoryData, snapshot: ConfigSnapshot) -> _ResolvedOutput:
    component = snapshot.component(output.component)
    rate_code: Optional[str] = None
    if output.percent is not None:
        percent = output.percent
    else:
        rate_code = category.rate if output.rate_from_category else output.rate
        if rate_code is None:
            raise TaxConfigError(
                "TAX_CATEGORY_RATE_MISSING", f"Category '{category.name}' has no rate for component '{output.component}'."
            )
        percent = snapshot.rate(rate_code).percent
    return _ResolvedOutput(
        component_code=output.component,
        component=component,
        rate_code=rate_code,
        percent=percent * output.split,
        behaviour=output.behaviour or component.behaviour,
    )


def _calculate_line(line: LineInput, context: TaxContext, situation: _Situation, snapshot: ConfigSnapshot) -> _ComputedLine:
    category = snapshot.category(line.category_code)
    if category.regime != situation.regime_code:
        raise TaxConfigError(
            "TAX_CATEGORY_WRONG_REGIME",
            f"Category '{line.category_code}' belongs to {category.regime}, not {situation.regime_code}.",
        )
    facts = _line_facts(line, category, context, situation)
    rule_code, rule = select_rule(snapshot.rules(situation.regime_code), facts, line.line_no)
    outputs = sorted(
        (_resolve_output(output, category, snapshot) for output in rule.then), key=lambda resolved: resolved.component.sequence
    )

    currency, mode = context.currency, situation.regime.rounding_mode
    gross = line.quantity * line.unit_price
    discount = round_money(line.discount_amount + gross * line.discount_percent / HUNDRED, currency, mode)
    net = round_money(gross, currency, mode) - discount

    taxable_raw = net
    if line.price_includes_tax:
        if any(out.component.base == "taxable_plus_previous" for out in outputs):
            raise TaxConfigError(
                "TAX_INCLUSIVE_COMPOUND_UNSUPPORTED", "Tax-inclusive prices can't be used with compound taxes."
            )
        charged_percent = sum((out.percent for out in outputs if out.behaviour in CHARGED_BEHAVIOURS), ZERO)
        taxable_raw = net / (1 + charged_percent / HUNDRED)

    tax_lines: list[TaxLine] = []
    raw_amounts: list[Decimal] = []
    for resolved in outputs:
        earlier_charged = sum(
            (
                raw
                for raw, previous in zip(raw_amounts, outputs)
                if previous.component.sequence < resolved.component.sequence and previous.behaviour in CHARGED_BEHAVIOURS
            ),
            ZERO,
        )
        base = taxable_raw + (earlier_charged if resolved.component.base == "taxable_plus_previous" else ZERO)
        raw_amount = base * resolved.percent / HUNDRED
        raw_amounts.append(raw_amount)
        tax_lines.append(
            TaxLine(
                component_code=resolved.component_code,
                label=resolved.component.label,
                behaviour=resolved.behaviour,
                rate_code=resolved.rate_code,
                percent=resolved.percent,
                base=round_money(base, currency, mode),
                amount=round_money(raw_amount, currency, mode),
                rule_code=rule_code,
                return_box=resolved.component.return_box,
            )
        )

    taxable_value = round_money(taxable_raw, currency, mode)
    if line.price_includes_tax:
        # The customer pays exactly the inclusive price: any rounding paisa stays in the taxable value.
        taxable_value = net - sum((tax.amount for tax in tax_lines if tax.behaviour in CHARGED_BEHAVIOURS), ZERO)

    line_result = LineResult(
        line_no=line.line_no,
        category_code=line.category_code,
        classification_code=line.classification_code or category.classification,
        gross=round_money(gross, currency, mode),
        discount=discount,
        taxable_value=taxable_value,
        taxes=tuple(tax_lines),
    )
    return _ComputedLine(line_result, tuple(raw_amounts), rule.note)


def _component_totals(computed: list[_ComputedLine], regime: RegimeData, currency: str) -> tuple[ComponentTotal, ...]:
    grouped: dict[tuple[str, str, str, Decimal, Optional[str]], list[Decimal]] = {}
    for line in computed:
        for tax, raw_amount in zip(line.result.taxes, line.raw_amounts):
            key = (tax.component_code, tax.label, tax.behaviour, tax.percent, tax.return_box)
            grouped.setdefault(key, []).append(raw_amount if regime.rounding_level == "document" else tax.amount)
    return tuple(
        ComponentTotal(
            component_code=code,
            label=label,
            behaviour=behaviour,
            percent=percent,
            amount=round_money(sum(amounts, ZERO), currency, regime.rounding_mode),
            return_box=return_box,
        )
        for (code, label, behaviour, percent, return_box), amounts in grouped.items()
    )


def _withholding(
    context: TaxContext, snapshot: ConfigSnapshot, taxable_total: Decimal, grand_total: Decimal
) -> tuple[Withholding, ...]:
    profile = context.customer.withholding
    if profile is None:
        return ()
    found = snapshot.withholding_section(profile.section_code)
    if found is None:
        raise TaxConfigError(
            "WITHHOLDING_SECTION_NOT_EFFECTIVE",
            f"No withholding section '{profile.section_code}' is in effect on {snapshot.as_of.isoformat()}.",
            meta={"section_code": profile.section_code},
        )
    section_code, section = found
    percent = section.rates.get(profile.deductee_type, section.rates["default"])
    certificate = next((cert for cert in profile.certificates if cert.covers(context.tax_point_date)), None)
    if certificate is not None and profile.has_pan:
        percent = certificate.percent
    if not profile.has_pan and section.no_pan_percent is not None:
        percent = max(percent, section.no_pan_percent)

    base = taxable_total if section.base == "taxable_value" else grand_total
    return (
        Withholding(
            section_code=section_code,
            statute_ref=section.statute_ref,
            payment_code=section.payment_codes.get(profile.deductee_type, section.payment_codes.get("default")),
            percent=percent,
            base=base,
            amount=round_money(base * percent / HUNDRED, context.currency, "half_up"),
            certificate_no=certificate.certificate_no if certificate is not None and profile.has_pan else None,
        ),
    )

