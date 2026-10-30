"""employee ids bank accounts onboarding

Revision ID: c36b879d89c3
Revises: a1d3f5b7c9e2
Create Date: 2026-10-30 12:37:02.187065+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

import database.types

revision: str = 'c36b879d89c3'
down_revision: Union[str, None] = 'a1d3f5b7c9e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The old bank and PAN columns on workers are dropped without copying: encrypting them needs the
    # field key, nothing read them, and no environment holds data in them.
    op.create_table('onboarding_requirements',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('item_code', sa.String(length=50), nullable=False),
    sa.Column('is_required', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'item_code', name='uq_onboarding_requirement')
    )
    op.create_index(op.f('ix_onboarding_requirements_organization_id'), 'onboarding_requirements', ['organization_id'], unique=False)
    op.create_table('sensitive_access_log',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('worker_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('actor_user_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('action', sa.String(length=30), nullable=False),
    sa.Column('target', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sensitive_access_log_organization_id'), 'sensitive_access_log', ['organization_id'], unique=False)
    op.create_index(op.f('ix_sensitive_access_log_worker_id'), 'sensitive_access_log', ['worker_id'], unique=False)
    op.create_table('worker_bank_accounts',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('worker_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('account_holder_name', sa.String(length=255), nullable=False),
    sa.Column('bank_name', sa.String(length=150), nullable=False),
    sa.Column('branch', sa.String(length=150), nullable=True),
    sa.Column('account_number_encrypted', sa.Text(), nullable=False),
    sa.Column('account_last4', sa.String(length=8), nullable=False),
    sa.Column('ifsc', sa.String(length=11), nullable=False),
    sa.Column('account_type', sa.String(length=20), nullable=False),
    sa.Column('upi_id', sa.String(length=100), nullable=True),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('proof_document_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('verified_by', database.types.UUIDType(length=36), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_worker_bank_accounts_organization_id'), 'worker_bank_accounts', ['organization_id'], unique=False)
    op.create_index(op.f('ix_worker_bank_accounts_status'), 'worker_bank_accounts', ['status'], unique=False)
    op.create_index(op.f('ix_worker_bank_accounts_worker_id'), 'worker_bank_accounts', ['worker_id'], unique=False)
    op.add_column('worker_documents', sa.Column('number_encrypted', sa.Text(), nullable=True))
    op.add_column('worker_documents', sa.Column('number_last4', sa.String(length=8), nullable=True))
    op.add_column('worker_documents', sa.Column('name_on_document', sa.String(length=255), nullable=True))
    op.add_column('worker_documents', sa.Column('issued_on', sa.Date(), nullable=True))
    op.add_column('worker_documents', sa.Column('expires_on', sa.Date(), nullable=True))
    op.add_column('worker_documents', sa.Column('issuing_authority', sa.String(length=255), nullable=True))
    op.add_column('worker_documents', sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'))
    op.add_column('worker_documents', sa.Column('rejection_reason', sa.Text(), nullable=True))
    op.add_column('worker_documents', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.add_column('worker_documents', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.alter_column('worker_documents', 'document_id',
               existing_type=mysql.VARCHAR(length=36),
               nullable=True)
    op.alter_column('worker_documents', 'file_name',
               existing_type=mysql.VARCHAR(length=255),
               nullable=True)
    op.create_index(op.f('ix_worker_documents_status'), 'worker_documents', ['status'], unique=False)
    op.create_unique_constraint('uq_worker_documents_type', 'worker_documents', ['organization_id', 'worker_id', 'document_type'])
    op.drop_column('workers', 'tax_id')
    op.drop_column('workers', 'bank_name')
    op.drop_column('workers', 'ifsc_code')
    op.drop_column('workers', 'bank_account_no')
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('workers', sa.Column('bank_account_no', mysql.VARCHAR(length=50), nullable=True))
    op.add_column('workers', sa.Column('ifsc_code', mysql.VARCHAR(length=50), nullable=True))
    op.add_column('workers', sa.Column('bank_name', mysql.VARCHAR(length=100), nullable=True))
    op.add_column('workers', sa.Column('tax_id', mysql.VARCHAR(length=50), nullable=True))
    op.drop_constraint('uq_worker_documents_type', 'worker_documents', type_='unique')
    op.drop_index(op.f('ix_worker_documents_status'), table_name='worker_documents')
    op.alter_column('worker_documents', 'file_name',
               existing_type=mysql.VARCHAR(length=255),
               nullable=False)
    op.alter_column('worker_documents', 'document_id',
               existing_type=mysql.VARCHAR(length=36),
               nullable=False)
    op.drop_column('worker_documents', 'updated_at')
    op.drop_column('worker_documents', 'created_at')
    op.drop_column('worker_documents', 'rejection_reason')
    op.drop_column('worker_documents', 'status')
    op.drop_column('worker_documents', 'issuing_authority')
    op.drop_column('worker_documents', 'expires_on')
    op.drop_column('worker_documents', 'issued_on')
    op.drop_column('worker_documents', 'name_on_document')
    op.drop_column('worker_documents', 'number_last4')
    op.drop_column('worker_documents', 'number_encrypted')
    op.drop_table('worker_bank_accounts')
    op.drop_table('sensitive_access_log')
    op.drop_table('onboarding_requirements')
    # ### end Alembic commands ###
