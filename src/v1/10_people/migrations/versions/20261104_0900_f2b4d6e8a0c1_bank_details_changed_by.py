"""bank details changed by

Who last entered a bank account's payment details, so that someone else verifies them (maker-checker).

Revision ID: f2b4d6e8a0c1
Revises: e1a3c5b7d9f2
Create Date: 2026-11-04 09:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types


revision: str = 'f2b4d6e8a0c1'
down_revision: Union[str, None] = 'e1a3c5b7d9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Startup's create_all may already have made the table with the column.
    inspector = sa.inspect(op.get_bind())
    if 'details_changed_by' not in {c['name'] for c in inspector.get_columns('worker_bank_accounts')}:
        op.add_column(
            'worker_bank_accounts',
            sa.Column('details_changed_by', database.types.UUIDType(length=36), nullable=True),
        )


def downgrade() -> None:
    op.drop_column('worker_bank_accounts', 'details_changed_by')
