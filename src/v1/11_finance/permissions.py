"""
Finance service permission codes, matching identity's catalog naming (`finance.<entity>.<action>`).

Finance holds the money that has no other home: operating expenses (rent, travel, marketing...)
and the company's investments and the income they bring. Hardware purchases stay in inventory
(Fixly), salaries in people, project costs in delivery and asset costs in assets.
"""

EXPENSE_READ = "finance.expense.read"
EXPENSE_WRITE = "finance.expense.write"
# Decide expenses waiting for approval (those above the organization's threshold).
EXPENSE_APPROVE = "finance.expense.approve"

INVESTMENT_READ = "finance.investment.read"
# Investments and the income entries recorded against them (interest, dividends, rent...).
INVESTMENT_WRITE = "finance.investment.write"

# Expense categories and the approval threshold.
SETUP_MANAGE = "finance.setup.manage"

# The business summary (CEO Command Center): expenses, other income and investments, totals only.
SUMMARY_READ = "finance.summary.read"

ALL = frozenset([
    EXPENSE_READ,
    EXPENSE_WRITE,
    EXPENSE_APPROVE,
    INVESTMENT_READ,
    INVESTMENT_WRITE,
    SETUP_MANAGE,
    SUMMARY_READ,
])
