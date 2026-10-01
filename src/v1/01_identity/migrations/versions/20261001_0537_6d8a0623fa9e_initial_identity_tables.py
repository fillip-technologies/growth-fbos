"""initial_identity_tables

Revision ID: 6d8a0623fa9e
Revises: 
Create Date: 2026-10-01 05:37:15.041169+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import database.types


revision: str = '6d8a0623fa9e'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Databases created earlier by Base.metadata.create_all already have some or
    # all of these tables; create only the missing ones so they adopt cleanly.
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if 'clients' not in existing:
        op.create_table('clients',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('contact_email', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_clients_code'), 'clients', ['code'], unique=True)
    if 'object_types' not in existing:
        op.create_table('object_types',
        sa.Column('code', sa.String(length=200), nullable=False),
        sa.Column('owning_service', sa.String(length=100), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('access_endpoint', sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint('code')
        )
        op.create_index(op.f('ix_object_types_owning_service'), 'object_types', ['owning_service'], unique=False)
    if 'permissions' not in existing:
        op.create_table('permissions',
        sa.Column('code', sa.String(length=200), nullable=False),
        sa.Column('service', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('code')
        )
        op.create_index(op.f('ix_permissions_service'), 'permissions', ['service'], unique=False)
    if 'platform_admins' not in existing:
        op.create_table('platform_admins',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_platform_admins_email'), 'platform_admins', ['email'], unique=True)
    if 'security_audit_logs' not in existing:
        op.create_table('security_audit_logs',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('user_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('ip_address', sa.String(length=100), nullable=True),
        sa.Column('user_agent', sa.String(length=512), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_security_audit_logs_category'), 'security_audit_logs', ['category'], unique=False)
        op.create_index(op.f('ix_security_audit_logs_event_type'), 'security_audit_logs', ['event_type'], unique=False)
        op.create_index(op.f('ix_security_audit_logs_organization_id'), 'security_audit_logs', ['organization_id'], unique=False)
        op.create_index(op.f('ix_security_audit_logs_user_id'), 'security_audit_logs', ['user_id'], unique=False)
    if 'verticals' not in existing:
        op.create_table('verticals',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_verticals_code'), 'verticals', ['code'], unique=True)
    if 'organizations' not in existing:
        op.create_table('organizations',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('client_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=True),
        sa.Column('base_currency', sa.String(length=10), nullable=False),
        sa.Column('fiscal_year_start', sa.String(length=5), nullable=False),
        sa.Column('timezone', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_organizations_client_id'), 'organizations', ['client_id'], unique=False)
        op.create_index(op.f('ix_organizations_code'), 'organizations', ['code'], unique=True)
    if 'api_clients' not in existing:
        op.create_table('api_clients',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('client_id', sa.String(length=100), nullable=False),
        sa.Column('client_secret_hash', sa.String(length=255), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('allowed_owner_hash', sa.String(length=255), nullable=True),
        sa.Column('allowed_scopes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_api_clients_client_id'), 'api_clients', ['client_id'], unique=True)
        op.create_index(op.f('ix_api_clients_organization_id'), 'api_clients', ['organization_id'], unique=False)
    if 'calendars' not in existing:
        op.create_table('calendars',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('timezone', sa.String(length=100), nullable=False),
        sa.Column('weekly_hours', sa.JSON(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_calendars_organization_id'), 'calendars', ['organization_id'], unique=False)
    if 'field_definitions' not in existing:
        op.create_table('field_definitions',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('vertical_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('object_type', sa.String(length=200), nullable=False),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('json_schema', sa.JSON(), nullable=True),
        sa.Column('ui_schema', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(['object_type'], ['object_types.code'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['vertical_id'], ['verticals.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_field_definitions_organization_id'), 'field_definitions', ['organization_id'], unique=False)
        op.create_index(op.f('ix_field_definitions_vertical_id'), 'field_definitions', ['vertical_id'], unique=False)
    if 'roles' not in existing:
        op.create_table('roles',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('is_system', sa.Boolean(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'code', name='uq_role_org_code')
        )
        op.create_index(op.f('ix_roles_code'), 'roles', ['code'], unique=False)
        op.create_index(op.f('ix_roles_organization_id'), 'roles', ['organization_id'], unique=False)
    if 'vertical_packs' not in existing:
        op.create_table('vertical_packs',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('vertical_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('pack_code', sa.String(length=100), nullable=False),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('manifest', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('import_results', sa.JSON(), nullable=True),
        sa.Column('activated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['vertical_id'], ['verticals.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_vertical_packs_organization_id'), 'vertical_packs', ['organization_id'], unique=False)
        op.create_index(op.f('ix_vertical_packs_vertical_id'), 'vertical_packs', ['vertical_id'], unique=False)
    if 'calendar_holidays' not in existing:
        op.create_table('calendar_holidays',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('calendar_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('holiday_date', sa.Date(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('is_half_day', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['calendar_id'], ['calendars.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_calendar_holidays_calendar_id'), 'calendar_holidays', ['calendar_id'], unique=False)
    if 'org_units' not in existing:
        op.create_table('org_units',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('unit_type', sa.String(length=50), nullable=True),
        sa.Column('parent_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('path', sa.String(length=2048), nullable=False),
        sa.Column('head_user_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('calendar_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['calendar_id'], ['calendars.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_id'], ['org_units.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'code', name='uq_org_unit_org_code')
        )
        op.create_index(op.f('ix_org_units_code'), 'org_units', ['code'], unique=False)
        op.create_index(op.f('ix_org_units_organization_id'), 'org_units', ['organization_id'], unique=False)
        op.create_index(op.f('ix_org_units_parent_id'), 'org_units', ['parent_id'], unique=False)
        op.create_index('ix_org_units_path', 'org_units', ['path'], unique=False, mysql_length=255)
    if 'role_permissions' not in existing:
        op.create_table('role_permissions',
        sa.Column('role_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('permission_code', sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(['permission_code'], ['permissions.code'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('role_id', 'permission_code')
        )
    if 'legal_entities' not in existing:
        op.create_table('legal_entities',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('mg_unit_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('legal_name', sa.String(length=512), nullable=False),
        sa.Column('pan', sa.String(length=20), nullable=True),
        sa.ForeignKeyConstraint(['mg_unit_id'], ['org_units.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_legal_entities_organization_id'), 'legal_entities', ['organization_id'], unique=False)
        op.create_index(op.f('ix_legal_entities_pan'), 'legal_entities', ['pan'], unique=False)
    if 'org_unit_verticals' not in existing:
        op.create_table('org_unit_verticals',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('org_unit_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('vertical_id', database.types.UUIDType(length=36), nullable=False),
        sa.ForeignKeyConstraint(['org_unit_id'], ['org_units.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['vertical_id'], ['verticals.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_unit_id', 'vertical_id', name='uq_org_unit_vertical')
        )
        op.create_index(op.f('ix_org_unit_verticals_org_unit_id'), 'org_unit_verticals', ['org_unit_id'], unique=False)
        op.create_index(op.f('ix_org_unit_verticals_vertical_id'), 'org_unit_verticals', ['vertical_id'], unique=False)
    if 'users' not in existing:
        op.create_table('users',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('manager_user_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('home_unit_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('employee_code', sa.String(length=100), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('user_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['home_unit_id'], ['org_units.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['manager_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
        op.create_index(op.f('ix_users_employee_code'), 'users', ['employee_code'], unique=False)
        op.create_index(op.f('ix_users_home_unit_id'), 'users', ['home_unit_id'], unique=False)
        op.create_index(op.f('ix_users_organization_id'), 'users', ['organization_id'], unique=False)
        op.create_index(op.f('ix_users_status'), 'users', ['status'], unique=False)
    # org_units <-> users is circular, so this FK is added once both tables exist.
    if 'org_units' not in existing:
        op.create_foreign_key(
            'fk_org_units_head_user_id', 'org_units', 'users',
            ['head_user_id'], ['id'], ondelete='SET NULL',
        )
    if 'refresh_tokens' not in existing:
        op.create_table('refresh_tokens',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('user_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('family_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('issued_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('user_agent', sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_refresh_tokens_family_id'), 'refresh_tokens', ['family_id'], unique=False)
        op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)
    if 'role_assignments' not in existing:
        op.create_table('role_assignments',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('user_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('role_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('scope_unit_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('scope_vertical_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('scope_path', sa.String(length=2048), nullable=True),
        sa.Column('self_only', sa.Boolean(), nullable=False),
        sa.Column('valid_from', sa.DateTime(), nullable=False),
        sa.Column('valid_to', sa.DateTime(), nullable=True),
        sa.Column('granted_by_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('reason', sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(['granted_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['scope_unit_id'], ['org_units.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['scope_vertical_id'], ['verticals.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_role_assignments_organization_id'), 'role_assignments', ['organization_id'], unique=False)
        op.create_index(op.f('ix_role_assignments_role_id'), 'role_assignments', ['role_id'], unique=False)
        op.create_index('ix_role_assignments_scope_path', 'role_assignments', ['scope_path'], unique=False, mysql_length=255)
        op.create_index(op.f('ix_role_assignments_scope_unit_id'), 'role_assignments', ['scope_unit_id'], unique=False)
        op.create_index(op.f('ix_role_assignments_scope_vertical_id'), 'role_assignments', ['scope_vertical_id'], unique=False)
        op.create_index(op.f('ix_role_assignments_user_id'), 'role_assignments', ['user_id'], unique=False)
    if 'tax_registrations' not in existing:
        op.create_table('tax_registrations',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('legal_entity_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('branch_unit_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('pin', sa.String(length=50), nullable=False),
        sa.Column('regime_code', sa.String(length=50), nullable=False),
        sa.Column('registered_address', sa.Text(), nullable=True),
        sa.Column('valid_from', sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(['branch_unit_id'], ['org_units.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['legal_entity_id'], ['legal_entities.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_tax_registrations_legal_entity_id'), 'tax_registrations', ['legal_entity_id'], unique=False)
        op.create_index(op.f('ix_tax_registrations_pin'), 'tax_registrations', ['pin'], unique=False)
    if 'unit_memberships' not in existing:
        op.create_table('unit_memberships',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('user_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('unit_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('member_role', sa.String(length=100), nullable=True),
        sa.Column('valid_to', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['unit_id'], ['org_units.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_unit_memberships_unit_id'), 'unit_memberships', ['unit_id'], unique=False)
        op.create_index(op.f('ix_unit_memberships_user_id'), 'unit_memberships', ['user_id'], unique=False)
    if 'user_credentials' not in existing:
        op.create_table('user_credentials',
        sa.Column('user_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('otp_secret_enc', sa.Text(), nullable=True),
        sa.Column('otp_enabled', sa.Boolean(), nullable=False),
        sa.Column('recovery_codes', sa.Text(), nullable=True),
        sa.Column('failed_attempts', sa.Integer(), nullable=False),
        sa.Column('locked_until', sa.DateTime(), nullable=True),
        sa.Column('password_changed_at', sa.DateTime(), nullable=True),
        sa.Column('reset_token', sa.String(length=255), nullable=True),
        sa.Column('reset_token_expires_at', sa.DateTime(), nullable=True),
        sa.Column('invitation_token', sa.String(length=255), nullable=True),
        sa.Column('invitation_token_expires_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id')
        )
        op.create_index(op.f('ix_user_credentials_invitation_token'), 'user_credentials', ['invitation_token'], unique=False)
        op.create_index(op.f('ix_user_credentials_reset_token'), 'user_credentials', ['reset_token'], unique=False)


def downgrade() -> None:
    # Indexes go with their tables; dropping them first fails on MySQL when a
    # foreign key still depends on them.
    op.drop_constraint('fk_org_units_head_user_id', 'org_units', type_='foreignkey')
    op.drop_table('user_credentials')
    op.drop_table('unit_memberships')
    op.drop_table('tax_registrations')
    op.drop_table('role_assignments')
    op.drop_table('refresh_tokens')
    op.drop_table('users')
    op.drop_table('org_unit_verticals')
    op.drop_table('legal_entities')
    op.drop_table('role_permissions')
    op.drop_table('org_units')
    op.drop_table('calendar_holidays')
    op.drop_table('vertical_packs')
    op.drop_table('roles')
    op.drop_table('field_definitions')
    op.drop_table('calendars')
    op.drop_table('api_clients')
    op.drop_table('organizations')
    op.drop_table('verticals')
    op.drop_table('security_audit_logs')
    op.drop_table('platform_admins')
    op.drop_table('permissions')
    op.drop_table('object_types')
    op.drop_table('clients')
