"""work unit partner organization

The associate company (another organization of the client) doing a project's work. Existing
projects have none.

Revision ID: a8c4e2d6f0b3
Revises: f1b6d4a8c2e7
Create Date: 2026-11-07 11:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types


revision: str = 'a8c4e2d6f0b3'
down_revision: Union[str, None] = 'f1b6d4a8c2e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('work_units')}
    if 'partner_organization_id' not in columns:
        op.add_column('work_units', sa.Column('partner_organization_id', database.types.UUIDType(length=36), nullable=True))
        op.create_index('ix_work_units_partner_organization_id', 'work_units', ['partner_organization_id'])


def downgrade() -> None:
    op.drop_index('ix_work_units_partner_organization_id', table_name='work_units')
    op.drop_column('work_units', 'partner_organization_id')
