"""
Proposal and quotation PDFs: an HTML page per document, drawn into a PDF by WeasyPrint.

The letterhead is text only (no logo is stored anywhere): the organization's default tax
registration gives its legal name, address and GSTIN. A preview is marked "Draft" and never
stored; the copy the customer gets is rendered once, when the document is first sent.
"""

from dataclasses import dataclass
from datetime import date
from html import escape
from typing import Optional, Sequence
import uuid

from anyio import to_thread
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.client import Client
from models.proposal import Proposal
from models.tax_registration import OrgTaxRegistration
from schemas.proposal import ProposalItemResponse
from schemas.quotation import QuotationResponse
from services.tax_service import parse_address


@dataclass(frozen=True)
class Party:
    """Who a document is from, or to: a name, address lines and a GSTIN."""

    name: str
    lines: tuple[str, ...] = ()
    gstin: Optional[str] = None


def _address_lines(raw: object) -> tuple[str, ...]:
    address = parse_address(raw)
    if not address:
        # Free text, as some customers' addresses are kept.
        text = raw.strip() if isinstance(raw, str) else ""
        return tuple(line.strip() for line in text.splitlines() if line.strip())
    place = " ".join(p for p in (address.get("city"), address.get("postal_code")) if p)
    region = ", ".join(p for p in (place, address.get("state")) if p)
    return tuple(p for p in (address.get("line1"), address.get("line2"), region) if p)


async def letterhead(session: AsyncSession, org_id: uuid.UUID, registration_id: Optional[uuid.UUID] = None) -> Optional[Party]:
    """The document's registration (a quotation's), else the default one active today; None if there is none."""
    chosen = await session.get(OrgTaxRegistration, registration_id) if registration_id else None
    if chosen is None or chosen.organization_id != org_id:
        rows = await session.execute(select(OrgTaxRegistration).where(OrgTaxRegistration.organization_id == org_id))
        active = [r for r in rows.scalars() if r.active_on(date.today())]
        chosen = next((r for r in active if r.is_default), active[0] if len(active) == 1 else None)
    if chosen is None:
        return None
    return Party(name=chosen.legal_name, lines=_address_lines(chosen.address), gstin=chosen.registration_no)


def customer(client: Client) -> Party:
    return Party(name=client.legal_name or client.name, lines=_address_lines(client.billing_address), gstin=client.gstin)


def _money(amount: float, currency: str) -> str:
    return f"{currency} {amount:,.2f}"


def _quantity(value: float) -> str:
    return f"{value:g}"


def _text(value: Optional[str]) -> str:
    """Paragraphs and line breaks kept, everything escaped."""
    blocks = [b.strip() for b in (value or "").split("\n\n") if b.strip()]
    return "".join(f"<p>{escape(b).replace(chr(10), '<br>')}</p>" for b in blocks)


def _party(label: str, party: Optional[Party]) -> str:
    if party is None:
        return ""
    lines = "".join(f"<div>{escape(line)}</div>" for line in party.lines)
    gstin = f'<div class="muted">GSTIN {escape(party.gstin)}</div>' if party.gstin else ""
    return f'<div class="party"><div class="label">{label}</div><strong>{escape(party.name)}</strong>{lines}{gstin}</div>'


STYLE = """
@page { size: A4; margin: 18mm 16mm 20mm; @bottom-right { content: "Page " counter(page) " of " counter(pages); font-size: 8pt; color: #64748b; } }
body { font-family: "DejaVu Sans", sans-serif; font-size: 9.5pt; color: #0f172a; line-height: 1.45; }
.head { display: flex; justify-content: space-between; border-bottom: 2px solid #0f172a; padding-bottom: 8px; margin-bottom: 14px; }
.head .org { font-size: 13pt; font-weight: bold; }
.head .doc { text-align: right; }
.head .doc .kind { font-size: 15pt; font-weight: bold; letter-spacing: 1px; }
.muted { color: #64748b; }
.parties { display: flex; gap: 24px; margin-bottom: 14px; }
.party { flex: 1; }
.label { font-size: 7.5pt; text-transform: uppercase; letter-spacing: .6px; color: #64748b; margin-bottom: 2px; }
h1 { font-size: 13pt; margin: 6px 0 10px; }
h2 { font-size: 10.5pt; margin: 16px 0 6px; border-bottom: 1px solid #cbd5e1; padding-bottom: 2px; }
p { margin: 0 0 6px; }
table { width: 100%; border-collapse: collapse; margin-top: 4px; }
th { text-align: left; font-size: 8pt; text-transform: uppercase; color: #475569; border-bottom: 1px solid #94a3b8; padding: 4px 6px; }
td { border-bottom: 1px solid #e2e8f0; padding: 5px 6px; vertical-align: top; }
td.num, th.num { text-align: right; white-space: nowrap; }
tr.total td { font-weight: bold; border-bottom: none; border-top: 1.5px solid #0f172a; }
.draft { position: fixed; top: 40%; left: 0; right: 0; text-align: center; font-size: 80pt; color: rgba(220, 38, 38, .12); transform: rotate(-30deg); font-weight: bold; }
.note { font-size: 8pt; color: #64748b; margin-top: 8px; }
"""


def _page(title: str, body: str, draft: bool) -> str:
    mark = '<div class="draft">DRAFT</div>' if draft else ""
    return (
        f'<!doctype html><html><head><meta charset="utf-8"><title>{escape(title)}</title>'
        f"<style>{STYLE}</style></head><body>{mark}{body}</body></html>"
    )


def _head(org: Optional[Party], kind: str, number: str, dated: Optional[date]) -> str:
    org_name = escape(org.name) if org else ""
    when = f"<div>Date: {dated:%d %b %Y}</div>" if dated else ""
    return (
        f'<div class="head"><div class="org">{org_name}</div>'
        f'<div class="doc"><div class="kind">{kind}</div><div>{escape(number)}</div>{when}</div></div>'
    )


def proposal_html(
    org: Optional[Party], to: Party, proposal: Proposal, items: Sequence[ProposalItemResponse], draft: bool
) -> str:
    number = f"{proposal.proposal_no} v{proposal.version_no}"
    dated = (proposal.sent_at or proposal.created_at).date() if (proposal.sent_at or proposal.created_at) else None
    sections = "".join(
        f"<h2>{heading}</h2>{_text(text)}"
        for heading, text in (
            ("Requirements", proposal.requirements),
            ("Scope of work", proposal.scope),
            ("Timeline", proposal.timeline),
        )
        if (text or "").strip()
    )
    services = ""
    if items:
        rows = "".join(
            f"<tr><td>{escape(i.offering_name)}"
            + (f'<div class="muted">{escape(i.description)}</div>' if i.description and i.description != i.offering_name else "")
            + f'</td><td class="num">{_quantity(i.quantity)} {escape(i.unit or "")}</td>'
            f'<td class="num">{_money(i.unit_price.amount, proposal.currency)}</td>'
            f'<td class="num">{_money(i.amount.amount, proposal.currency)}</td></tr>'
            for i in items
        )
        services = (
            '<h2>Services and estimate</h2><table><thead><tr><th>Service</th><th class="num">Quantity</th>'
            '<th class="num">Rate</th><th class="num">Amount</th></tr></thead>'
            f'<tbody>{rows}<tr class="total"><td colspan="3">Estimated total</td>'
            f'<td class="num">{_money(float(proposal.total or 0), proposal.currency)}</td></tr></tbody></table>'
            '<div class="note">Amounts are before tax. The quotation that follows this proposal gives the final prices with taxes.</div>'
        )
    terms = f"<h2>Terms</h2>{_text(proposal.terms)}" if (proposal.terms or "").strip() else ""
    body = (
        _head(org, "PROPOSAL", number, dated)
        + f'<div class="parties">{_party("From", org)}{_party("Prepared for", to)}</div>'
        + f"<h1>{escape(proposal.title)}</h1>{sections}{services}{terms}"
    )
    return _page(f"Proposal {number}", body, draft)


def quotation_html(org: Optional[Party], to: Party, quote: QuotationResponse, dated: Optional[date], draft: bool) -> str:
    number = f"{quote.quote_no} rev {quote.revision_no}"
    currency = quote.currency
    rows = "".join(
        f"<tr><td>{escape(i.description or '')}</td>"
        f'<td class="num">{_quantity(i.quantity)} {escape(i.unit or "")}</td>'
        f'<td class="num">{_money(i.unit_price.amount, currency)}</td>'
        f'<td class="num">{i.discount_pct:g}%</td>'
        f'<td class="num">{_money(i.taxable_value.amount, currency)}</td>'
        f'<td class="num">{i.gst_rate:g}%</td>'
        f'<td class="num">{_money(i.line_total.amount, currency)}</td></tr>'
        for i in quote.items
    )
    totals = quote.totals
    tax_rows = "".join(
        f'<tr><td colspan="6">{escape(t.label)} ({t.rate:g}%)</td><td class="num">{_money(t.amount.amount, currency)}</td></tr>'
        for t in totals.taxes
    )
    round_off = (
        f'<tr><td colspan="6">Round off</td><td class="num">{_money(totals.round_off.amount, currency)}</td></tr>'
        if totals.round_off.amount
        else ""
    )
    valid = f"<p>Valid until {quote.valid_until:%d %b %Y}.</p>" if quote.valid_until else ""
    supply = f'<div class="muted">Place of supply: {escape(quote.place_of_supply)}</div>' if quote.place_of_supply else ""
    body = (
        _head(org, "QUOTATION", number, dated)
        + f'<div class="parties">{_party("From", org)}{_party("Quoted to", to)}</div>'
        + (f"<h1>{escape(quote.name)}</h1>" if quote.name else "")
        + supply
        + '<table><thead><tr><th>Item</th><th class="num">Qty</th><th class="num">Rate</th><th class="num">Disc.</th>'
        '<th class="num">Taxable</th><th class="num">Tax</th><th class="num">Amount</th></tr></thead>'
        f"<tbody>{rows}"
        f'<tr><td colspan="6">Taxable value</td><td class="num">{_money(totals.taxable_total.amount, currency)}</td></tr>'
        f"{tax_rows}{round_off}"
        f'<tr class="total"><td colspan="6">Total</td><td class="num">{_money(totals.grand_total.amount, currency)}</td></tr>'
        "</tbody></table>"
        + valid
        + (f"<h2>Terms</h2>{_text(quote.terms)}" if (quote.terms or "").strip() else "")
    )
    return _page(f"Quotation {number}", body, draft)


def _write_pdf(html: str) -> bytes:
    # Imported here: WeasyPrint loads Pango when imported, which only the PDF routes need.
    from weasyprint import HTML

    return HTML(string=html).write_pdf()


async def to_pdf(html: str) -> bytes:
    """Drawing a PDF takes a moment of CPU: off the event loop."""
    return await to_thread.run_sync(_write_pdf, html)
