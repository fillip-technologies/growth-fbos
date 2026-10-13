"""offering fulfilment: what a won contract for it is delivered as (project, service, none)

Revision ID: d2a8f6c3e1b7
Revises: c7e1d4b9a2f6
Create Date: 2026-10-13 18:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd2a8f6c3e1b7'
down_revision: Union[str, None] = 'c7e1d4b9a2f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Every existing offering keeps today's behaviour: no next step is suggested.
    with op.batch_alter_table('offerings') as batch:
        batch.add_column(sa.Column('fulfilment', sa.String(length=20), server_default='none', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('offerings') as batch:
        batch.drop_column('fulfilment')
