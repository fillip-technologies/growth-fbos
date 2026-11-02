"""interviews

Revision ID: b7c2d4e6f8a1
Revises: a1d3f5b7c9e2
Create Date: 2026-11-02 10:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types


revision: str = 'b7c2d4e6f8a1'
down_revision: Union[str, None] = 'a1d3f5b7c9e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _exists(table: str, column: str = None) -> bool:
    """
    Whether the table (or the column) is already there. People creates missing tables when it starts
    (`create_all`), so a table this migration would create may exist already; a column cannot be.
    """
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    return column is None or column in {c['name'] for c in inspector.get_columns(table)}



def upgrade() -> None:
    if _exists('interviews'):
        return
    op.create_table('interviews',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('application_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('round_name', sa.String(length=64), nullable=False),
    sa.Column('interviewer_worker_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('interviewer_user_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('interviewer_name', sa.String(length=128), nullable=False),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('duration_minutes', sa.Integer(), nullable=False),
    sa.Column('location', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('scorecard_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('created_by', database.types.UUIDType(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['job_applications.id']),
    sa.PrimaryKeyConstraint('id')
    )
    for column in ('organization_id', 'application_id', 'interviewer_worker_id', 'interviewer_user_id', 'scheduled_at', 'status'):
        op.create_index(op.f(f'ix_interviews_{column}'), 'interviews', [column], unique=False)


def downgrade() -> None:
    op.drop_table('interviews')
