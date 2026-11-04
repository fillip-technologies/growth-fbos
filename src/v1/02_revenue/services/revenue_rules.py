"""What counts as revenue earned: one rule for Management's actuals and the business summary.

Issued tax invoices and debit notes count positive, credit notes negative, each at its taxable
value (GST collected is owed to the government, not earned), dated by its issue date.
"""

REVENUE_DOC_TYPES = ("tax_invoice", "debit_note", "credit_note")
UNISSUED_STATUSES = ("draft", "pending_approval")
NEGATIVE_DOC_TYPES = ("credit_note",)
