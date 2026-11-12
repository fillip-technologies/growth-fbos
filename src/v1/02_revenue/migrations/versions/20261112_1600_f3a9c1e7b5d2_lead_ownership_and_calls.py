"""lead ownership and calls

Leads may wait unclaimed (`owner_user_id` NULL), keep the follow-up date of their latest call
(`next_follow_up_on`) and, once their customer accepts a quotation, when that happened and who
handled them (`converted_at`, `converted_by_user_id`). `lead_events` is each lead's history:
created, claimed, transferred, contacted, qualified and so on. Activities get a call's details:
requirements, expectations, next action and follow-up date. Nothing existing is changed.

Revision ID: f3a9c1e7b5d2
Revises: e4b8c2f6a9d1
Create Date: 2026-11-12 16:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import database.types


revision: str = 'f3a9c1e7b5d2'
down_revision: Union[str, None] = 'e4b8c2f6a9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('leads') as batch:
        batch.alter_column('owner_user_id', existing_type=database.types.UUIDType(length=36), nullable=True)
        batch.add_column(sa.Column('next_follow_up_on', sa.Date(), nullable=True))
        batch.add_column(sa.Column('converted_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('converted_by_user_id', database.types.UUIDType(length=36), nullable=True))
        batch.create_index('ix_leads_next_follow_up_on', ['next_follow_up_on'], unique=False)

    with op.batch_alter_table('activities') as batch:
        batch.add_column(sa.Column('requirements', sa.Text(), nullable=True))
        batch.add_column(sa.Column('expectations', sa.Text(), nullable=True))
        batch.add_column(sa.Column('next_action', sa.Text(), nullable=True))
        batch.add_column(sa.Column('follow_up_on', sa.Date(), nullable=True))

    op.create_table('lead_events',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('lead_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('event', sa.String(length=30), nullable=False),
    sa.Column('actor_user_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('occurred_at', sa.DateTime(), nullable=False),
    sa.Column('from_user_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('to_user_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('from_status', sa.String(length=50), nullable=True),
    sa.Column('to_status', sa.String(length=50), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_lead_events_organization_id'), 'lead_events', ['organization_id'], unique=False)
    op.create_index(op.f('ix_lead_events_lead_id'), 'lead_events', ['lead_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_lead_events_lead_id'), table_name='lead_events')
    op.drop_index(op.f('ix_lead_events_organization_id'), table_name='lead_events')
    op.drop_table('lead_events')

    with op.batch_alter_table('activities') as batch:
        batch.drop_column('follow_up_on')
        batch.drop_column('next_action')
        batch.drop_column('expectations')
        batch.drop_column('requirements')

    # Unclaimed leads can't go back to a required owner: put this back only after every
    # lead has one again.
    with op.batch_alter_table('leads') as batch:
        batch.drop_index('ix_leads_next_follow_up_on')
        batch.drop_column('converted_by_user_id')
        batch.drop_column('converted_at')
        batch.drop_column('next_follow_up_on')
        batch.alter_column('owner_user_id', existing_type=database.types.UUIDType(length=36), nullable=False)
