"""worker posts

Revision ID: c3e5a7b9d1f3
Revises: b7c2d4e6f8a1, 6b1f7015d0f9
Create Date: 2026-11-02 12:00:00.000000+00:00

Adds the effective-dated posts table and gives every existing employee a primary post built from
their current designation, department, manager and seat.
"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types


revision: str = 'c3e5a7b9d1f3'
down_revision: Union[str, Sequence[str], None] = ('b7c2d4e6f8a1', '6b1f7015d0f9')
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
    if not _exists('worker_posts'):
        _create_worker_posts()
    _backfill_primary_posts()


def _create_worker_posts() -> None:
    op.create_table('worker_posts',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('worker_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('post_ref', database.types.UUIDType(length=36), nullable=False),
    sa.Column('post_type', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('unit_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('position_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('manager_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('time_share', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('monthly_allowance', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('role_change_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['manager_id'], ['workers.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    for column in ('organization_id', 'worker_id', 'post_ref', 'unit_id', 'position_id', 'start_date', 'status'):
        op.create_index(op.f(f'ix_worker_posts_{column}'), 'worker_posts', [column], unique=False)
    op.create_index('ix_worker_posts_worker_status', 'worker_posts', ['worker_id', 'status'], unique=False)


def _backfill_primary_posts() -> None:
    """One primary post for each employee who has none. Employees who already left get an ended one."""
    bind = op.get_bind()
    posts = sa.table(
        'worker_posts',
        sa.column('id'), sa.column('organization_id'), sa.column('worker_id'), sa.column('post_ref'), sa.column('post_type'),
        sa.column('title'), sa.column('unit_id'), sa.column('position_id'), sa.column('manager_id'),
        sa.column('start_date', sa.Date), sa.column('end_date', sa.Date), sa.column('status'),
    )
    has_post = sa.select(posts.c.worker_id)
    workers = sa.table(
        'workers',
        sa.column('id'), sa.column('organization_id'), sa.column('designation'), sa.column('unit_id'),
        sa.column('manager_id'), sa.column('status'), sa.column('date_of_joining', sa.Date), sa.column('last_working_date', sa.Date),
    )
    seats = sa.table(
        'position_assignments',
        sa.column('worker_id'), sa.column('position_id'), sa.column('is_primary'), sa.column('status'),
    )
    seat_by_worker = {
        str(row.worker_id): row.position_id
        for row in bind.execute(
            sa.select(seats.c.worker_id, seats.c.position_id).where(seats.c.is_primary.is_(True), seats.c.status == 'active')
        )
    }
    rows = []
    for worker in bind.execute(sa.select(workers).where(workers.c.id.not_in(has_post))):
        exited = worker.status == 'exited'
        rows.append({
            'id': str(uuid.uuid4()),
            'organization_id': str(worker.organization_id),
            'worker_id': str(worker.id),
            'post_ref': str(uuid.uuid4()),
            'post_type': 'primary',
            'title': worker.designation,
            'unit_id': str(worker.unit_id) if worker.unit_id else None,
            'position_id': str(seat_by_worker[str(worker.id)]) if str(worker.id) in seat_by_worker else None,
            'manager_id': str(worker.manager_id) if worker.manager_id else None,
            'start_date': worker.date_of_joining,
            'end_date': (worker.last_working_date or worker.date_of_joining) if exited else None,
            'status': 'ended' if exited else 'active',
        })
    if rows:
        op.bulk_insert(posts, rows)


def downgrade() -> None:
    op.drop_table('worker_posts')
