"""proposals

Proposals with versions (`proposals`), their services (`proposal_items`) and history
(`proposal_events`). Quotations remember the proposal they were made from (`proposal_id`) and
the PDF the customer got (`pdf_document_id`, `pdf_version_no`). Nothing existing is changed.

Revision ID: a7d2e9c4b1f6
Revises: f3a9c1e7b5d2
Create Date: 2026-11-12 18:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import database.types


revision: str = 'a7d2e9c4b1f6'
down_revision: Union[str, None] = 'f3a9c1e7b5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = database.types.UUIDType(length=36)


def upgrade() -> None:
    op.create_table('proposals',
    sa.Column('id', UUID, nullable=False),
    sa.Column('organization_id', UUID, nullable=False),
    sa.Column('opportunity_id', UUID, nullable=False),
    sa.Column('client_id', UUID, nullable=False),
    sa.Column('proposal_no', sa.String(length=50), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('previous_version_id', UUID, nullable=True),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('requirements', sa.Text(), nullable=True),
    sa.Column('scope', sa.Text(), nullable=True),
    sa.Column('timeline', sa.Text(), nullable=True),
    sa.Column('terms', sa.Text(), nullable=True),
    sa.Column('currency', sa.String(length=10), nullable=False),
    sa.Column('total', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('revision_note', sa.Text(), nullable=True),
    sa.Column('customer_feedback', sa.Text(), nullable=True),
    sa.Column('sent_at', sa.DateTime(), nullable=True),
    sa.Column('decided_at', sa.DateTime(), nullable=True),
    sa.Column('pdf_document_id', UUID, nullable=True),
    sa.Column('pdf_version_no', sa.Integer(), nullable=True),
    sa.Column('created_by_user_id', UUID, nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['previous_version_id'], ['proposals.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'proposal_no', 'version_no', name='uq_proposals_number_version')
    )
    op.create_index(op.f('ix_proposals_organization_id'), 'proposals', ['organization_id'], unique=False)
    op.create_index(op.f('ix_proposals_opportunity_id'), 'proposals', ['opportunity_id'], unique=False)
    op.create_index(op.f('ix_proposals_client_id'), 'proposals', ['client_id'], unique=False)
    op.create_index(op.f('ix_proposals_proposal_no'), 'proposals', ['proposal_no'], unique=False)
    op.create_index(op.f('ix_proposals_status'), 'proposals', ['status'], unique=False)

    op.create_table('proposal_items',
    sa.Column('id', UUID, nullable=False),
    sa.Column('proposal_id', UUID, nullable=False),
    sa.Column('offering_id', UUID, nullable=False),
    sa.Column('line_no', sa.Integer(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=15, scale=4), nullable=False),
    sa.Column('unit', sa.String(length=50), nullable=True),
    sa.Column('unit_price', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.ForeignKeyConstraint(['offering_id'], ['offerings.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['proposal_id'], ['proposals.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_proposal_items_proposal_id'), 'proposal_items', ['proposal_id'], unique=False)

    op.create_table('proposal_events',
    sa.Column('id', UUID, nullable=False),
    sa.Column('organization_id', UUID, nullable=False),
    sa.Column('proposal_id', UUID, nullable=False),
    sa.Column('event', sa.String(length=30), nullable=False),
    sa.Column('actor_user_id', UUID, nullable=True),
    sa.Column('occurred_at', sa.DateTime(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('data', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['proposal_id'], ['proposals.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_proposal_events_organization_id'), 'proposal_events', ['organization_id'], unique=False)
    op.create_index(op.f('ix_proposal_events_proposal_id'), 'proposal_events', ['proposal_id'], unique=False)

    with op.batch_alter_table('quotations') as batch:
        batch.add_column(sa.Column('proposal_id', UUID, nullable=True))
        batch.add_column(sa.Column('pdf_document_id', UUID, nullable=True))
        batch.add_column(sa.Column('pdf_version_no', sa.Integer(), nullable=True))
        batch.create_index('ix_quotations_proposal_id', ['proposal_id'], unique=False)
        batch.create_foreign_key('fk_quotations_proposal_id', 'proposals', ['proposal_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('quotations') as batch:
        batch.drop_constraint('fk_quotations_proposal_id', type_='foreignkey')
        batch.drop_index('ix_quotations_proposal_id')
        batch.drop_column('pdf_version_no')
        batch.drop_column('pdf_document_id')
        batch.drop_column('proposal_id')

    op.drop_index(op.f('ix_proposal_events_proposal_id'), table_name='proposal_events')
    op.drop_index(op.f('ix_proposal_events_organization_id'), table_name='proposal_events')
    op.drop_table('proposal_events')
    op.drop_index(op.f('ix_proposal_items_proposal_id'), table_name='proposal_items')
    op.drop_table('proposal_items')
    op.drop_index(op.f('ix_proposals_status'), table_name='proposals')
    op.drop_index(op.f('ix_proposals_proposal_no'), table_name='proposals')
    op.drop_index(op.f('ix_proposals_client_id'), table_name='proposals')
    op.drop_index(op.f('ix_proposals_opportunity_id'), table_name='proposals')
    op.drop_index(op.f('ix_proposals_organization_id'), table_name='proposals')
    op.drop_table('proposals')
