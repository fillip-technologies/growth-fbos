"""role assignable by people

Whether People may grant a role through an approved role change. Off for system roles; an admin can turn it on.

Revision ID: d0f2b4c6e8a1
Revises: f2c8d4e6a7b9
Create Date: 2026-11-03 09:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd0f2b4c6e8a1'
down_revision: Union[str, None] = 'f2c8d4e6a7b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('roles')}
    if 'assignable_by_people' in columns:
        return
    op.add_column('roles', sa.Column('assignable_by_people', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.execute(sa.text("UPDATE roles SET assignable_by_people = :off WHERE is_system = :on").bindparams(off=False, on=True))


def downgrade() -> None:
    op.drop_column('roles', 'assignable_by_people')
