"""organization relationship

How the client relates to each of its companies: its own, an associate it gives work to, or one
it has invested in. Existing organizations are the client's own.

Revision ID: c7e9a1b3d5f6
Revises: b6d8f0a2c4e5
Create Date: 2026-11-07 09:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7e9a1b3d5f6'
down_revision: Union[str, None] = 'b6d8f0a2c4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('organizations')}
    if 'relationship' not in columns:
        op.add_column(
            'organizations',
            sa.Column('relationship', sa.String(length=20), nullable=False, server_default='own'),
        )


def downgrade() -> None:
    op.drop_column('organizations', 'relationship')
