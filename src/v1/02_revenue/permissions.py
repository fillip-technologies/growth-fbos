"""
Permission codes for revenue's tax and billing-setup routes (older revenue routes name their
codes inline). Every code here is also in identity's catalog
(`src/v1/01_identity/services/permission_catalog.py`).
"""

# Tax setup: registrations, rates, rules, packs, numbering, finance settings and tax reports.
TAX_READ = "revenue.tax.read"
TAX_MANAGE = "revenue.tax.manage"

# Contract billing schedules: what is due, milestones reached, billing a line.
BILLING_SCHEDULE_READ = "revenue.billing_schedule.read"
BILLING_SCHEDULE_WRITE = "revenue.billing_schedule.write"

# Writing off what a customer will not pay (no tax effect, unlike a credit note).
INVOICE_WRITE_OFF = "revenue.invoice.write_off"

# TDS customers withheld: tracking it until it shows in Form 26AS and is claimed.
TDS_RECEIVABLE_READ = "revenue.tds_receivable.read"
TDS_RECEIVABLE_WRITE = "revenue.tds_receivable.write"

# Existing codes the new routes reuse.
CLIENT_READ = "revenue.client.read"
CLIENT_WRITE = "revenue.client.write"

# The business summary (CEO Command Center): revenue, receivables, pipeline, AMC, totals only.
SUMMARY_READ = "revenue.summary.read"

# Leads: everyone with read sees every lead; write lets someone claim a lead and work the ones
# they handle (calls, qualify, disqualify, pass it on); assign is for sales managers: hand any
# lead to anyone and work any lead.
LEAD_READ = "revenue.lead.read"
LEAD_WRITE = "revenue.lead.write"
LEAD_ASSIGN = "revenue.lead.assign"
