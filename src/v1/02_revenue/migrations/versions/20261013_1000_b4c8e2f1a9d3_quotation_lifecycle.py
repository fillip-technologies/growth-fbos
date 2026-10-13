"""quotation lifecycle: valid_until, sent_at, status note and reason, quotation_events

`completed_at` held the valid-until date (midnight) until a quotation was sent, then the send
time, then the acceptance time. A midnight value is the valid-until date the quotation was
created with; any other value on a sent or rejected quotation is when it was sent. The
valid-until dates of quotations already sent were overwritten and stay unknown.

Revision ID: b4c8e2f1a9d3
Revises: a3f1c7d9e2b4
Create Date: 2026-10-13 10:00:00.000000+00:00

"""
from datetime import date, datetime, time
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import database.types


revision: str = 'b4c8e2f1a9d3'
down_revision: Union[str, None] = 'a3f1c7d9e2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

quotations = sa.table(
    'quotations',
    sa.column('id', database.types.UUIDType(length=36)),
    sa.column('status', sa.String(50)),
    sa.column('completed_at', sa.DateTime()),
    sa.column('valid_until', sa.Date()),
    sa.column('sent_at', sa.DateTime()),
)


def _as_datetime(value) -> datetime:
    # SQLite hands back text through a lightweight table() column.
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def upgrade() -> None:
    with op.batch_alter_table('quotations') as batch:
        batch.add_column(sa.Column('valid_until', sa.Date(), nullable=True))
        batch.add_column(sa.Column('sent_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('status_note', sa.Text(), nullable=True))
        batch.add_column(sa.Column('status_reason', sa.String(length=50), nullable=True))

    op.create_table('quotation_events',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('quotation_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('event', sa.String(length=30), nullable=False),
    sa.Column('actor_user_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('occurred_at', sa.DateTime(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('data', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['quotation_id'], ['quotations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_quotation_events_organization_id'), 'quotation_events', ['organization_id'], unique=False)
    op.create_index(op.f('ix_quotation_events_quotation_id'), 'quotation_events', ['quotation_id'], unique=False)

    bind = op.get_bind()
    rows = bind.execute(
        sa.select(quotations.c.id, quotations.c.status, quotations.c.completed_at).where(quotations.c.completed_at.is_not(None))
    ).all()
    for quote_id, status, completed_at in rows:
        moment = _as_datetime(completed_at)
        if moment.time() == time.min and status != 'accepted':
            values = {'valid_until': moment.date(), 'completed_at': None}
        elif status in ('sent', 'rejected'):
            values = {'sent_at': moment, 'completed_at': None}
        else:
            continue
        bind.execute(quotations.update().where(quotations.c.id == quote_id).values(**values))


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(quotations.c.id, quotations.c.valid_until, quotations.c.sent_at).where(quotations.c.completed_at.is_(None))
    ).all()
    for quote_id, valid_until, sent_at in rows:
        if sent_at is not None:
            restored = _as_datetime(sent_at)
        elif valid_until is not None:
            restored = datetime.combine(_as_date(valid_until), time.min)
        else:
            continue
        bind.execute(quotations.update().where(quotations.c.id == quote_id).values(completed_at=restored))

    # Its indexes go with it (MySQL won't drop the foreign key's index on its own).
    op.drop_table('quotation_events')
    with op.batch_alter_table('quotations') as batch:
        batch.drop_column('status_reason')
        batch.drop_column('status_note')
        batch.drop_column('sent_at')
        batch.drop_column('valid_until')
