"""per_org_unique_codes

Revision ID: 8d41f07a2c96
Revises: e10f9247a265
Create Date: 2026-09-25 11:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op


revision: str = '8d41f07a2c96'
down_revision: Union[str, None] = 'e10f9247a265'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Codes are unique per organization (API reference, "Conventions"), not globally.
PER_ORG_UNIQUE = [
    ('retention_policies', 'code'),
    ('document_categories', 'code'),
    ('documents', 'code'),
]


def upgrade() -> None:
    for table, column in PER_ORG_UNIQUE:
        op.drop_index(op.f(f'ix_{table}_{column}'), table_name=table)
        op.create_index(op.f(f'ix_{table}_{column}'), table, [column], unique=False)
        op.create_unique_constraint(f'uq_{table}_org_{column}', table, ['organization_id', column])


def downgrade() -> None:
    for table, column in PER_ORG_UNIQUE:
        op.drop_constraint(f'uq_{table}_org_{column}', table, type_='unique')
        op.drop_index(op.f(f'ix_{table}_{column}'), table_name=table)
        op.create_index(op.f(f'ix_{table}_{column}'), table, [column], unique=True)
