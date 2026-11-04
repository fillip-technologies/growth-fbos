"""
The gateway's permission codes, as identity's catalog names them. The CEO Command Center is an
Insight screen assembled here; every service it reads still checks its own summary permission.
"""

# Open the Command Center and see its non-financial cards.
CEO_DASHBOARD_READ = "insight.ceo_dashboard.read"
# Also see payroll, expenses, profit, margins, budgets and investments. Without it the gateway
# leaves those figures out of the response.
CEO_DASHBOARD_FINANCIALS = "insight.ceo_dashboard.financials"
