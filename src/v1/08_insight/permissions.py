"""
Insight service permission codes, matching identity's catalog naming (`insight.<entity>.<action>`).

Insight keeps the audit trail, analytics (dashboards, metric series, reports) and the CEO Command
Center's daily snapshots. The snapshots are read with the Command Center's own codes: the
gateway's screen and these series show the same figures to the same people.
"""

AUDIT_READ = "insight.audit.read"
ANALYTICS_READ = "insight.analytics.read"
REPORT_RUN = "insight.report.run"

# The CEO Command Center (the gateway builds the screen); its snapshots here use the same codes.
CEO_DASHBOARD_READ = "insight.ceo_dashboard.read"
# Payroll, expenses, costs, purchases and other income.
CEO_DASHBOARD_FINANCIALS = "insight.ceo_dashboard.financials"

ALL = frozenset([AUDIT_READ, ANALYTICS_READ, REPORT_RUN, CEO_DASHBOARD_READ, CEO_DASHBOARD_FINANCIALS])
