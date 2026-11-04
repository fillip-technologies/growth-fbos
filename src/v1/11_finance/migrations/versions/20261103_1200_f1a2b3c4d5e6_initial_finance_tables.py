"""initial finance tables: expense categories, expenses, settings, investments, income entries

Revision ID: f1a2b3c4d5e6
Revises:
Create Date: 2026-11-03 12:00:00
"""
from alembic import op
import sqlalchemy as sa

from database.types import UUIDType

revision = "f1a2b3c4d5e6"
down_revision = None
branch_labels = None
depends_on = None

MONEY = sa.Numeric(14, 2)


def upgrade() -> None:
    op.create_table(
        "finance_settings",
        sa.Column("organization_id", UUIDType(), primary_key=True),
        sa.Column("expense_approval_threshold", MONEY, nullable=True),
        sa.Column("default_currency", sa.String(3), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", UUIDType(), nullable=True),
    )

    op.create_table(
        "expense_categories",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column("organization_id", UUIDType(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("is_builtin", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "code", name="uq_expense_categories_org_code"),
    )
    op.create_index("ix_expense_categories_organization_id", "expense_categories", ["organization_id"])

    op.create_table(
        "expenses",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column("organization_id", UUIDType(), nullable=False),
        sa.Column("category_id", UUIDType(), sa.ForeignKey("expense_categories.id"), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("vendor_name", sa.String(200), nullable=True),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("tax_amount", MONEY, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("payment_status", sa.String(20), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("payment_reference", sa.String(120), nullable=True),
        sa.Column("work_unit_id", UUIDType(), nullable=True),
        sa.Column("org_unit_id", UUIDType(), nullable=True),
        sa.Column("document_id", UUIDType(), nullable=True),
        sa.Column("approval_status", sa.String(20), nullable=False),
        sa.Column("decided_by", UUIDType(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", UUIDType(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_expenses_organization_id", "expenses", ["organization_id"])
    op.create_index("ix_expenses_category_id", "expenses", ["category_id"])
    op.create_index("ix_expenses_work_unit_id", "expenses", ["work_unit_id"])
    op.create_index("ix_expenses_org_unit_id", "expenses", ["org_unit_id"])
    op.create_index("ix_expenses_org_date", "expenses", ["organization_id", "expense_date"])
    op.create_index("ix_expenses_org_status", "expenses", ["organization_id", "approval_status"])

    op.create_table(
        "investments",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column("organization_id", UUIDType(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("investment_type", sa.String(30), nullable=False),
        sa.Column("institution", sa.String(200), nullable=True),
        sa.Column("reference", sa.String(120), nullable=True),
        sa.Column("investee_organization_id", UUIDType(), nullable=True),
        sa.Column("principal", MONEY, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("maturity_date", sa.Date(), nullable=True),
        sa.Column("expected_rate_pct", sa.Numeric(7, 3), nullable=True),
        sa.Column("current_value", MONEY, nullable=True),
        sa.Column("current_value_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", UUIDType(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_investments_organization_id", "investments", ["organization_id"])
    op.create_index("ix_investments_investee_organization_id", "investments", ["investee_organization_id"])
    op.create_index("ix_investments_status", "investments", ["status"])

    op.create_table(
        "income_entries",
        sa.Column("id", UUIDType(), primary_key=True),
        sa.Column("organization_id", UUIDType(), nullable=False),
        sa.Column("investment_id", UUIDType(), sa.ForeignKey("investments.id"), nullable=True),
        sa.Column("income_type", sa.String(30), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("tax_deducted", MONEY, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_by", UUIDType(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_income_entries_organization_id", "income_entries", ["organization_id"])
    op.create_index("ix_income_entries_investment_id", "income_entries", ["investment_id"])
    op.create_index("ix_income_entries_org_date", "income_entries", ["organization_id", "received_on"])


def downgrade() -> None:
    op.drop_table("income_entries")
    op.drop_table("investments")
    op.drop_table("expenses")
    op.drop_table("expense_categories")
    op.drop_table("finance_settings")
