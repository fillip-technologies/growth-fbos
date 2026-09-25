"""per_org_unique_codes

Revision ID: 5b2e9c41d7a3
Revises: 0946d05b0fba
Create Date: 2026-09-25 11:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import database.types


revision: str = '5b2e9c41d7a3'
down_revision: Union[str, None] = '0946d05b0fba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Codes are unique per organization (API reference, "Conventions"), not globally.
PER_ORG_UNIQUE = [
    ('contracts', 'contract_no'),
    ('invoices', 'invoice_no'),
    ('payments', 'receipt_no'),
]


def upgrade() -> None:
    op.add_column('invoice_series', sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False))
    op.create_index(op.f('ix_invoice_series_organization_id'), 'invoice_series', ['organization_id'], unique=False)
    for table, column in PER_ORG_UNIQUE:
        op.drop_index(op.f(f'ix_{table}_{column}'), table_name=table)
        op.create_index(op.f(f'ix_{table}_{column}'), table, [column], unique=False)
        op.create_unique_constraint(f'uq_{table}_org_{column}', table, ['organization_id', column])


def downgrade() -> None:
    for table, column in PER_ORG_UNIQUE:
        op.drop_constraint(f'uq_{table}_org_{column}', table, type_='unique')
        op.drop_index(op.f(f'ix_{table}_{column}'), table_name=table)
        op.create_index(op.f(f'ix_{table}_{column}'), table, [column], unique=True)
    op.drop_index(op.f('ix_invoice_series_organization_id'), table_name='invoice_series')
    op.drop_column('invoice_series', 'organization_id')
