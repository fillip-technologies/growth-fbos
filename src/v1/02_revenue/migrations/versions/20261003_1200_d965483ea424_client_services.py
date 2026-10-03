"""client_services

Revision ID: d965483ea424
Revises: 5b2e9c41d7a3
Create Date: 2026-10-03 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import database.types


revision: str = 'd965483ea424'
down_revision: Union[str, None] = '5b2e9c41d7a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('service_categories',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'name', name='uq_service_categories_org_name')
    )
    op.create_index(op.f('ix_service_categories_organization_id'), 'service_categories', ['organization_id'], unique=False)

    op.create_table('service_providers',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('category_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('contact_name', sa.String(length=255), nullable=True),
    sa.Column('phone', sa.String(length=50), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('website', sa.String(length=512), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['service_categories.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'name', name='uq_service_providers_org_name')
    )
    op.create_index(op.f('ix_service_providers_organization_id'), 'service_providers', ['organization_id'], unique=False)
    op.create_index(op.f('ix_service_providers_category_id'), 'service_providers', ['category_id'], unique=False)

    op.create_table('client_services',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('client_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('provider_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('category_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('reference_no', sa.String(length=255), nullable=True),
    sa.Column('managed_by', sa.String(length=20), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('renewal_date', sa.Date(), nullable=True),
    sa.Column('auto_renew', sa.Boolean(), nullable=False),
    sa.Column('cost', sa.Numeric(precision=15, scale=2), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('billing_cycle', sa.String(length=20), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('attributes', sa.JSON(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['provider_id'], ['service_providers.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['category_id'], ['service_categories.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_client_services_organization_id'), 'client_services', ['organization_id'], unique=False)
    op.create_index(op.f('ix_client_services_client_id'), 'client_services', ['client_id'], unique=False)
    op.create_index(op.f('ix_client_services_provider_id'), 'client_services', ['provider_id'], unique=False)
    op.create_index(op.f('ix_client_services_category_id'), 'client_services', ['category_id'], unique=False)
    op.create_index(op.f('ix_client_services_renewal_date'), 'client_services', ['renewal_date'], unique=False)
    op.create_index(op.f('ix_client_services_status'), 'client_services', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_client_services_status'), table_name='client_services')
    op.drop_index(op.f('ix_client_services_renewal_date'), table_name='client_services')
    op.drop_index(op.f('ix_client_services_category_id'), table_name='client_services')
    op.drop_index(op.f('ix_client_services_provider_id'), table_name='client_services')
    op.drop_index(op.f('ix_client_services_client_id'), table_name='client_services')
    op.drop_index(op.f('ix_client_services_organization_id'), table_name='client_services')
    op.drop_table('client_services')
    op.drop_index(op.f('ix_service_providers_category_id'), table_name='service_providers')
    op.drop_index(op.f('ix_service_providers_organization_id'), table_name='service_providers')
    op.drop_table('service_providers')
    op.drop_index(op.f('ix_service_categories_organization_id'), table_name='service_categories')
    op.drop_table('service_categories')
