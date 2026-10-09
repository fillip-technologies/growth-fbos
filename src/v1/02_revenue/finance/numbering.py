"""
Document numbers from series templates (`series_template` entries).

A series is one running sequence per registration (or the organization), document type and
period. The next number is taken under a row lock, so two documents issued at once never get
the same number and none is skipped. A series that starts while numbers in its format already
exist (documents issued before the series table was used) continues after the highest one.
"""

from dataclasses import dataclass
from datetime import date
import re
import string
from typing import Awaitable, Callable, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.errors import TaxConfigError
from finance.fiscal import fiscal_year_of
from finance.tax.config_schema import DocumentNumberRules, SeriesTemplateData
from finance.tax.snapshot import ConfigSnapshot
from models.invoice_series import ORGANIZATION_SCOPE, InvoiceSeries

# Numbers already used for a document type in the organization, for continuing a series.
ExistingNumbers = Callable[[], Awaitable[list[str]]]


@dataclass(frozen=True)
class PeriodTokens:
    label: str  # the series' period key
    fy: str
    fy_short: str
    year: int
    jurisdiction: str = ""  # the registration's jurisdiction (GST state code), for orgs with several


def period_tokens(day: date, reset: str, fiscal_year_start: str, jurisdiction: Optional[str] = None) -> PeriodTokens:
    fiscal_year = fiscal_year_of(day, fiscal_year_start)
    label = {"fiscal_year": fiscal_year.label, "calendar_year": str(day.year), "never": "all"}[reset]
    return PeriodTokens(
        label=label, fy=fiscal_year.label, fy_short=fiscal_year.short_label, year=day.year, jurisdiction=jurisdiction or ""
    )


def render_number(template_format: str, prefix: str, tokens: PeriodTokens, sequence: int) -> str:
    return template_format.format(
        prefix=prefix, fy=tokens.fy, fy_short=tokens.fy_short, year=tokens.year, jurisdiction=tokens.jurisdiction, seq=sequence
    )


def number_pattern(template_format: str, prefix: str, tokens: PeriodTokens) -> re.Pattern[str]:
    """A regex matching numbers rendered from the format in this period, capturing the sequence."""
    values = {
        "prefix": prefix, "fy": tokens.fy, "fy_short": tokens.fy_short, "year": str(tokens.year), "jurisdiction": tokens.jurisdiction,
    }
    parts: list[str] = []
    for literal, field, _spec, _conversion in string.Formatter().parse(template_format):
        parts.append(re.escape(literal))
        if field == "seq":
            parts.append(r"(\d+)")
        elif field is not None:
            parts.append(re.escape(values[field]))
    return re.compile("^" + "".join(parts) + "$")


def check_number_rules(number: str, rules: DocumentNumberRules) -> None:
    if rules.max_length is not None and len(number) > rules.max_length:
        raise TaxConfigError(
            "DOCUMENT_NUMBER_TOO_LONG",
            f"'{number}' is {len(number)} characters; the regime allows {rules.max_length}. Shorten the series format.",
        )
    if rules.pattern is not None and not re.match(rules.pattern, number):
        raise TaxConfigError(
            "DOCUMENT_NUMBER_INVALID", f"'{number}' uses characters the regime does not allow in document numbers."
        )


async def next_document_number(
    session: AsyncSession,
    org_id: uuid.UUID,
    doc_type: str,
    on: date,
    snapshot: ConfigSnapshot,
    fiscal_year_start: str,
    existing_numbers: ExistingNumbers,
    registration_id: Optional[uuid.UUID] = None,
    number_rules: Optional[DocumentNumberRules] = None,
    jurisdiction: Optional[str] = None,
) -> tuple[InvoiceSeries, str]:
    template: Optional[SeriesTemplateData] = snapshot.series_template(doc_type)
    if template is None:
        raise TaxConfigError(
            "SERIES_TEMPLATE_MISSING", f"No number format is set for {doc_type.replace('_', ' ')}s.", meta={"doc_type": doc_type}
        )
    tokens = period_tokens(on, template.reset, fiscal_year_start, jurisdiction)
    scope_key = str(registration_id) if registration_id else ORGANIZATION_SCOPE

    series = (
        await session.execute(
            select(InvoiceSeries)
            .where(
                InvoiceSeries.organization_id == org_id,
                InvoiceSeries.scope_key == scope_key,
                InvoiceSeries.doc_type == doc_type,
                InvoiceSeries.fiscal_year == tokens.label,
            )
            .with_for_update()
        )
    ).scalars().first()
    if series is None:
        pattern = number_pattern(template.format, template.prefix, tokens)
        used = [int(match.group(1)) for number in await existing_numbers() if (match := pattern.match(number))]
        series = InvoiceSeries(
            organization_id=org_id, fin_registration_id=registration_id, scope_key=scope_key, doc_type=doc_type,
            prefix=template.prefix, fiscal_year=tokens.label, format=template.format, next_number=max(used, default=0) + 1,
        )
        session.add(series)
        await session.flush()

    number = render_number(series.format or template.format, series.prefix, tokens, series.next_number)
    if number_rules is not None:
        check_number_rules(number, number_rules)
    series.next_number += 1
    await session.flush()
    return series, number
