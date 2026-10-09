"""
What an invoice still owes, and its status, from what settled it.

balance_due = grand_total - amount_settled - credited_amount - written_off_amount
- amount_settled: payments, plus the TDS / GST-TDS the customer withheld from them.
- credited_amount: credit notes against it (they correct the invoice; they are not payments).
- written_off_amount: what the organization stopped expecting (no tax effect).

A credit note alone never makes an invoice "paid": fully credited is "cancelled".
"""

from decimal import Decimal

from finance.money import ZERO, to_decimal
from models.invoice import Invoice

OPEN_STATUSES = ("issued", "partially_paid", "overdue")


def owed(invoice: Invoice) -> Decimal:
    return (
        to_decimal(invoice.grand_total)
        - to_decimal(invoice.amount_settled)
        - to_decimal(invoice.credited_amount)
        - to_decimal(invoice.written_off_amount)
    )


def settlement_status(invoice: Invoice) -> str:
    if invoice.status in ("draft", "pending_approval"):
        return invoice.status
    grand_total = to_decimal(invoice.grand_total)
    if to_decimal(invoice.credited_amount) >= grand_total:
        return "cancelled"
    if owed(invoice) <= ZERO:
        if to_decimal(invoice.amount_settled) > ZERO:
            return "paid"
        if to_decimal(invoice.written_off_amount) > ZERO:
            return "written_off"
        return "cancelled"
    if to_decimal(invoice.amount_settled) > ZERO:
        return "partially_paid"
    if invoice.status == "overdue":
        return "overdue"
    return "issued"


def recompute(invoice: Invoice) -> Decimal:
    """Refresh balance_due and status; returns any excess (credit beyond what was owed)."""
    remaining = owed(invoice)
    invoice.balance_due = max(remaining, ZERO)
    invoice.status = settlement_status(invoice)
    invoice.version += 1
    return max(-remaining, ZERO)


def apply_credit(invoice: Invoice, amount: Decimal) -> Decimal:
    """Credit an invoice; returns the part of the credit beyond its balance (owed back to the customer)."""
    invoice.credited_amount = to_decimal(invoice.credited_amount) + amount
    return recompute(invoice)


def apply_settlement(invoice: Invoice, amount: Decimal) -> None:
    invoice.amount_settled = to_decimal(invoice.amount_settled) + amount
    recompute(invoice)


def apply_write_off(invoice: Invoice, amount: Decimal) -> None:
    invoice.written_off_amount = to_decimal(invoice.written_off_amount) + amount
    recompute(invoice)
