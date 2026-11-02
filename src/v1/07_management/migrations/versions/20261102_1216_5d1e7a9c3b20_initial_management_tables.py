"""initial management tables

The 30 tables management started with (planning, performance, resources). The shared database already
holds them, created by create_all; on such a database this revision only records itself.

Revision ID: 5d1e7a9c3b20
Revises: 
Create Date: 2026-11-02 12:16:50.536048+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types  # the UUIDType columns


revision: str = '5d1e7a9c3b20'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Databases created earlier by Base.metadata.create_all already have some or all of these tables;
    # create only the missing ones so they adopt cleanly (start.sh runs `alembic upgrade head`).
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if 'fiscal_years' not in existing:
        op.create_table('fiscal_years',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'code', name='uq_fiscal_years_org_code')
        )
        op.create_index(op.f('ix_fiscal_years_code'), 'fiscal_years', ['code'], unique=False)
        op.create_index(op.f('ix_fiscal_years_organization_id'), 'fiscal_years', ['organization_id'], unique=False)
        op.create_index(op.f('ix_fiscal_years_status'), 'fiscal_years', ['status'], unique=False)
    if 'kpi_definitions' not in existing:
        op.create_table('kpi_definitions',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('unit', sa.String(length=50), nullable=False),
        sa.Column('direction', sa.String(length=50), nullable=False),
        sa.Column('aggregation', sa.String(length=50), nullable=False),
        sa.Column('formula', sa.JSON(), nullable=True),
        sa.Column('frequency', sa.String(length=50), nullable=False),
        sa.Column('owner_user_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'code', name='uq_kpi_definitions_org_code')
        )
        op.create_index(op.f('ix_kpi_definitions_code'), 'kpi_definitions', ['code'], unique=False)
        op.create_index(op.f('ix_kpi_definitions_organization_id'), 'kpi_definitions', ['organization_id'], unique=False)
        op.create_index(op.f('ix_kpi_definitions_owner_user_id'), 'kpi_definitions', ['owner_user_id'], unique=False)
        op.create_index(op.f('ix_kpi_definitions_status'), 'kpi_definitions', ['status'], unique=False)
    if 'resources' not in existing:
        op.create_table('resources',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('resource_type', sa.String(length=50), nullable=False),
        sa.Column('user_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('unit_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('calendar_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('employment_type', sa.String(length=50), nullable=False),
        sa.Column('fte', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('daily_capacity_minutes', sa.Integer(), nullable=False),
        sa.Column('internal_cost_rate', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_resources_calendar_id'), 'resources', ['calendar_id'], unique=False)
        op.create_index(op.f('ix_resources_organization_id'), 'resources', ['organization_id'], unique=False)
        op.create_index(op.f('ix_resources_status'), 'resources', ['status'], unique=False)
        op.create_index(op.f('ix_resources_unit_id'), 'resources', ['unit_id'], unique=False)
        op.create_index(op.f('ix_resources_user_id'), 'resources', ['user_id'], unique=False)
    if 'skills' not in existing:
        op.create_table('skills',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'code', name='uq_skills_org_code')
        )
        op.create_index(op.f('ix_skills_category'), 'skills', ['category'], unique=False)
        op.create_index(op.f('ix_skills_code'), 'skills', ['code'], unique=False)
        op.create_index(op.f('ix_skills_organization_id'), 'skills', ['organization_id'], unique=False)
    if 'availability_exceptions' not in existing:
        op.create_table('availability_exceptions',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('resource_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('exception_type', sa.String(length=50), nullable=False),
        sa.Column('minutes', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=100), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['resource_id'], ['resources.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_availability_exceptions_resource_id'), 'availability_exceptions', ['resource_id'], unique=False)
        op.create_index(op.f('ix_availability_exceptions_starts_at'), 'availability_exceptions', ['starts_at'], unique=False)
    if 'budgets' not in existing:
        op.create_table('budgets',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('fiscal_year_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('scope_unit_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('scope_vertical_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('revision_no', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('approval_request_id', database.types.UUIDType(length=36), nullable=True),
        sa.ForeignKeyConstraint(['fiscal_year_id'], ['fiscal_years.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'code', name='uq_budgets_org_code')
        )
        op.create_index(op.f('ix_budgets_approval_request_id'), 'budgets', ['approval_request_id'], unique=False)
        op.create_index(op.f('ix_budgets_code'), 'budgets', ['code'], unique=False)
        op.create_index(op.f('ix_budgets_fiscal_year_id'), 'budgets', ['fiscal_year_id'], unique=False)
        op.create_index(op.f('ix_budgets_organization_id'), 'budgets', ['organization_id'], unique=False)
        op.create_index(op.f('ix_budgets_scope_unit_id'), 'budgets', ['scope_unit_id'], unique=False)
        op.create_index(op.f('ix_budgets_scope_vertical_id'), 'budgets', ['scope_vertical_id'], unique=False)
        op.create_index(op.f('ix_budgets_status'), 'budgets', ['status'], unique=False)
    if 'capacity_gaps' not in existing:
        op.create_table('capacity_gaps',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('skill_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('unit_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('required_minutes', sa.Integer(), nullable=False),
        sa.Column('available_minutes', sa.Integer(), nullable=False),
        sa.Column('gap_minutes', sa.Integer(), nullable=False),
        sa.Column('severity', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_capacity_gaps_organization_id'), 'capacity_gaps', ['organization_id'], unique=False)
        op.create_index(op.f('ix_capacity_gaps_skill_id'), 'capacity_gaps', ['skill_id'], unique=False)
        op.create_index(op.f('ix_capacity_gaps_status'), 'capacity_gaps', ['status'], unique=False)
        op.create_index(op.f('ix_capacity_gaps_unit_id'), 'capacity_gaps', ['unit_id'], unique=False)
    if 'capacity_ledger' not in existing:
        op.create_table('capacity_ledger',
        sa.Column('resource_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('capacity_minutes', sa.Integer(), nullable=False),
        sa.Column('allocated_minutes', sa.Integer(), nullable=False),
        sa.Column('actual_minutes', sa.Integer(), nullable=False),
        sa.Column('overload', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['resource_id'], ['resources.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('resource_id', 'day')
        )
        op.create_index(op.f('ix_capacity_ledger_day'), 'capacity_ledger', ['day'], unique=False)
    if 'kpi_measurements' not in existing:
        op.create_table('kpi_measurements',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('kpi_definition_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('reverses_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('measured_on', sa.Date(), nullable=False),
        sa.Column('value', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('unit_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('vertical_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('user_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('client_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('offering_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('source_type', sa.String(length=50), nullable=False),
        sa.Column('source_event_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('entered_by', database.types.UUIDType(length=36), nullable=True),
        sa.ForeignKeyConstraint(['kpi_definition_id'], ['kpi_definitions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reverses_id'], ['kpi_measurements.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_kpi_measurements_client_id'), 'kpi_measurements', ['client_id'], unique=False)
        op.create_index(op.f('ix_kpi_measurements_kpi_definition_id'), 'kpi_measurements', ['kpi_definition_id'], unique=False)
        op.create_index(op.f('ix_kpi_measurements_measured_on'), 'kpi_measurements', ['measured_on'], unique=False)
        op.create_index(op.f('ix_kpi_measurements_offering_id'), 'kpi_measurements', ['offering_id'], unique=False)
        op.create_index(op.f('ix_kpi_measurements_organization_id'), 'kpi_measurements', ['organization_id'], unique=False)
        op.create_index(op.f('ix_kpi_measurements_reverses_id'), 'kpi_measurements', ['reverses_id'], unique=False)
        op.create_index(op.f('ix_kpi_measurements_source_event_id'), 'kpi_measurements', ['source_event_id'], unique=False)
        op.create_index(op.f('ix_kpi_measurements_unit_id'), 'kpi_measurements', ['unit_id'], unique=False)
        op.create_index(op.f('ix_kpi_measurements_user_id'), 'kpi_measurements', ['user_id'], unique=False)
        op.create_index(op.f('ix_kpi_measurements_vertical_id'), 'kpi_measurements', ['vertical_id'], unique=False)
    if 'kpi_sources' not in existing:
        op.create_table('kpi_sources',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('kpi_definition_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('source_type', sa.String(length=50), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=True),
        sa.Column('value_path', sa.String(length=255), nullable=True),
        sa.Column('filter', sa.JSON(), nullable=True),
        sa.Column('dimension_map', sa.JSON(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['kpi_definition_id'], ['kpi_definitions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_kpi_sources_kpi_definition_id'), 'kpi_sources', ['kpi_definition_id'], unique=False)
    if 'kpi_thresholds' not in existing:
        op.create_table('kpi_thresholds',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('kpi_definition_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('scope_unit_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('green_from_pct', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('amber_from_pct', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.ForeignKeyConstraint(['kpi_definition_id'], ['kpi_definitions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_kpi_thresholds_kpi_definition_id'), 'kpi_thresholds', ['kpi_definition_id'], unique=False)
        op.create_index(op.f('ix_kpi_thresholds_scope_unit_id'), 'kpi_thresholds', ['scope_unit_id'], unique=False)
    if 'planning_periods' not in existing:
        op.create_table('planning_periods',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('fiscal_year_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('parent_period_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('period_type', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(['fiscal_year_id'], ['fiscal_years.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_period_id'], ['planning_periods.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_planning_periods_fiscal_year_id'), 'planning_periods', ['fiscal_year_id'], unique=False)
        op.create_index(op.f('ix_planning_periods_organization_id'), 'planning_periods', ['organization_id'], unique=False)
        op.create_index(op.f('ix_planning_periods_parent_period_id'), 'planning_periods', ['parent_period_id'], unique=False)
        op.create_index(op.f('ix_planning_periods_status'), 'planning_periods', ['status'], unique=False)
    if 'resource_requirements' not in existing:
        op.create_table('resource_requirements',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('subject_type', sa.String(length=100), nullable=False),
        sa.Column('subject_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('skill_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('min_level', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('required_minutes', sa.Integer(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('priority', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_resource_requirements_organization_id'), 'resource_requirements', ['organization_id'], unique=False)
        op.create_index(op.f('ix_resource_requirements_skill_id'), 'resource_requirements', ['skill_id'], unique=False)
        op.create_index(op.f('ix_resource_requirements_status'), 'resource_requirements', ['status'], unique=False)
        op.create_index(op.f('ix_resource_requirements_subject_id'), 'resource_requirements', ['subject_id'], unique=False)
        op.create_index(op.f('ix_resource_requirements_subject_type'), 'resource_requirements', ['subject_type'], unique=False)
    if 'resource_skills' not in existing:
        op.create_table('resource_skills',
        sa.Column('resource_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('skill_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('level', sa.Integer(), nullable=False),
        sa.Column('years_experience', sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column('verified_by', database.types.UUIDType(length=36), nullable=True),
        sa.Column('valid_until', sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(['resource_id'], ['resources.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('resource_id', 'skill_id')
        )
    if 'allocations' not in existing:
        op.create_table('allocations',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('resource_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('requirement_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('subject_type', sa.String(length=100), nullable=False),
        sa.Column('subject_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('minutes_per_day', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('override_reason', sa.Text(), nullable=True),
        sa.Column('approved_by', database.types.UUIDType(length=36), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['requirement_id'], ['resource_requirements.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['resource_id'], ['resources.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_allocations_end_date'), 'allocations', ['end_date'], unique=False)
        op.create_index(op.f('ix_allocations_organization_id'), 'allocations', ['organization_id'], unique=False)
        op.create_index(op.f('ix_allocations_requirement_id'), 'allocations', ['requirement_id'], unique=False)
        op.create_index(op.f('ix_allocations_resource_id'), 'allocations', ['resource_id'], unique=False)
        op.create_index(op.f('ix_allocations_start_date'), 'allocations', ['start_date'], unique=False)
        op.create_index(op.f('ix_allocations_status'), 'allocations', ['status'], unique=False)
        op.create_index(op.f('ix_allocations_subject_id'), 'allocations', ['subject_id'], unique=False)
        op.create_index(op.f('ix_allocations_subject_type'), 'allocations', ['subject_type'], unique=False)
    if 'budget_lines' not in existing:
        op.create_table('budget_lines',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('budget_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('planned_amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('approved_amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.ForeignKeyConstraint(['budget_id'], ['budgets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_budget_lines_budget_id'), 'budget_lines', ['budget_id'], unique=False)
        op.create_index(op.f('ix_budget_lines_category'), 'budget_lines', ['category'], unique=False)
    if 'scenarios' not in existing:
        op.create_table('scenarios',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('base_period_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('assumption_type', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(['base_period_id'], ['planning_periods.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_scenarios_base_period_id'), 'scenarios', ['base_period_id'], unique=False)
        op.create_index(op.f('ix_scenarios_organization_id'), 'scenarios', ['organization_id'], unique=False)
        op.create_index(op.f('ix_scenarios_status'), 'scenarios', ['status'], unique=False)
    if 'strategic_goals' not in existing:
        op.create_table('strategic_goals',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('period_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('parent_goal_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('scope_unit_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('scope_vertical_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('owner_user_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('priority', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['parent_goal_id'], ['strategic_goals.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['period_id'], ['planning_periods.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'code', name='uq_strategic_goals_org_code')
        )
        op.create_index(op.f('ix_strategic_goals_code'), 'strategic_goals', ['code'], unique=False)
        op.create_index(op.f('ix_strategic_goals_organization_id'), 'strategic_goals', ['organization_id'], unique=False)
        op.create_index(op.f('ix_strategic_goals_owner_user_id'), 'strategic_goals', ['owner_user_id'], unique=False)
        op.create_index(op.f('ix_strategic_goals_parent_goal_id'), 'strategic_goals', ['parent_goal_id'], unique=False)
        op.create_index(op.f('ix_strategic_goals_period_id'), 'strategic_goals', ['period_id'], unique=False)
        op.create_index(op.f('ix_strategic_goals_scope_unit_id'), 'strategic_goals', ['scope_unit_id'], unique=False)
        op.create_index(op.f('ix_strategic_goals_scope_vertical_id'), 'strategic_goals', ['scope_vertical_id'], unique=False)
        op.create_index(op.f('ix_strategic_goals_status'), 'strategic_goals', ['status'], unique=False)
    if 'allocation_history' not in existing:
        op.create_table('allocation_history',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('allocation_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('change_type', sa.String(length=50), nullable=False),
        sa.Column('before', sa.JSON(), nullable=True),
        sa.Column('after', sa.JSON(), nullable=True),
        sa.Column('changed_by', database.types.UUIDType(length=36), nullable=True),
        sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['allocation_id'], ['allocations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_allocation_history_allocation_id'), 'allocation_history', ['allocation_id'], unique=False)
    if 'budget_actuals' not in existing:
        op.create_table('budget_actuals',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('budget_line_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('occurred_on', sa.Date(), nullable=False),
        sa.Column('source_type', sa.String(length=50), nullable=False),
        sa.Column('source_event_id', database.types.UUIDType(length=36), nullable=True),
        sa.ForeignKeyConstraint(['budget_line_id'], ['budget_lines.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_budget_actuals_budget_line_id'), 'budget_actuals', ['budget_line_id'], unique=False)
        op.create_index(op.f('ix_budget_actuals_occurred_on'), 'budget_actuals', ['occurred_on'], unique=False)
        op.create_index(op.f('ix_budget_actuals_source_event_id'), 'budget_actuals', ['source_event_id'], unique=False)
    if 'budget_allocations' not in existing:
        op.create_table('budget_allocations',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('budget_line_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('target_type', sa.String(length=100), nullable=False),
        sa.Column('target_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.ForeignKeyConstraint(['budget_line_id'], ['budget_lines.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_budget_allocations_budget_line_id'), 'budget_allocations', ['budget_line_id'], unique=False)
        op.create_index(op.f('ix_budget_allocations_target_id'), 'budget_allocations', ['target_id'], unique=False)
        op.create_index(op.f('ix_budget_allocations_target_type'), 'budget_allocations', ['target_type'], unique=False)
    if 'goal_kpis' not in existing:
        op.create_table('goal_kpis',
        sa.Column('goal_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('kpi_definition_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('weight', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.ForeignKeyConstraint(['goal_id'], ['strategic_goals.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['kpi_definition_id'], ['kpi_definitions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('goal_id', 'kpi_definition_id')
        )
    if 'initiatives' not in existing:
        op.create_table('initiatives',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('goal_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('owner_user_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('linked_work_unit_id', database.types.UUIDType(length=36), nullable=True),
        sa.ForeignKeyConstraint(['goal_id'], ['strategic_goals.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'code', name='uq_initiatives_org_code')
        )
        op.create_index(op.f('ix_initiatives_code'), 'initiatives', ['code'], unique=False)
        op.create_index(op.f('ix_initiatives_goal_id'), 'initiatives', ['goal_id'], unique=False)
        op.create_index(op.f('ix_initiatives_linked_work_unit_id'), 'initiatives', ['linked_work_unit_id'], unique=False)
        op.create_index(op.f('ix_initiatives_organization_id'), 'initiatives', ['organization_id'], unique=False)
        op.create_index(op.f('ix_initiatives_owner_user_id'), 'initiatives', ['owner_user_id'], unique=False)
        op.create_index(op.f('ix_initiatives_status'), 'initiatives', ['status'], unique=False)
    if 'kpi_targets' not in existing:
        op.create_table('kpi_targets',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('goal_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('kpi_definition_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('period_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('supersedes_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('scope_unit_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('scope_vertical_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('scope_user_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('target_value', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('stretch_value', sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column('revision_no', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('approval_request_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['goal_id'], ['strategic_goals.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['kpi_definition_id'], ['kpi_definitions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['period_id'], ['planning_periods.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['supersedes_id'], ['kpi_targets.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_kpi_targets_approval_request_id'), 'kpi_targets', ['approval_request_id'], unique=False)
        op.create_index(op.f('ix_kpi_targets_goal_id'), 'kpi_targets', ['goal_id'], unique=False)
        op.create_index(op.f('ix_kpi_targets_kpi_definition_id'), 'kpi_targets', ['kpi_definition_id'], unique=False)
        op.create_index(op.f('ix_kpi_targets_organization_id'), 'kpi_targets', ['organization_id'], unique=False)
        op.create_index(op.f('ix_kpi_targets_period_id'), 'kpi_targets', ['period_id'], unique=False)
        op.create_index(op.f('ix_kpi_targets_scope_unit_id'), 'kpi_targets', ['scope_unit_id'], unique=False)
        op.create_index(op.f('ix_kpi_targets_scope_user_id'), 'kpi_targets', ['scope_user_id'], unique=False)
        op.create_index(op.f('ix_kpi_targets_scope_vertical_id'), 'kpi_targets', ['scope_vertical_id'], unique=False)
        op.create_index(op.f('ix_kpi_targets_status'), 'kpi_targets', ['status'], unique=False)
        op.create_index(op.f('ix_kpi_targets_supersedes_id'), 'kpi_targets', ['supersedes_id'], unique=False)
    if 'scenario_values' not in existing:
        op.create_table('scenario_values',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('scenario_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('kpi_definition_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('period_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('baseline_value', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('scenario_value', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.ForeignKeyConstraint(['kpi_definition_id'], ['kpi_definitions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['period_id'], ['planning_periods.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['scenario_id'], ['scenarios.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_scenario_values_kpi_definition_id'), 'scenario_values', ['kpi_definition_id'], unique=False)
        op.create_index(op.f('ix_scenario_values_period_id'), 'scenario_values', ['period_id'], unique=False)
        op.create_index(op.f('ix_scenario_values_scenario_id'), 'scenario_values', ['scenario_id'], unique=False)
    if 'initiative_milestones' not in existing:
        op.create_table('initiative_milestones',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('initiative_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('progress_pct', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.ForeignKeyConstraint(['initiative_id'], ['initiatives.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_initiative_milestones_initiative_id'), 'initiative_milestones', ['initiative_id'], unique=False)
        op.create_index(op.f('ix_initiative_milestones_status'), 'initiative_milestones', ['status'], unique=False)
    if 'kpi_results' not in existing:
        op.create_table('kpi_results',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('target_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('kpi_definition_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('period_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('scope_key', sa.String(length=100), nullable=False),
        sa.Column('actual_value', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('target_value', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('achievement_pct', sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column('variance_abs', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('variance_pct', sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('trend', sa.String(length=50), nullable=False),
        sa.Column('calc_version', sa.Integer(), nullable=False),
        sa.Column('inputs_hash', sa.String(length=64), nullable=False),
        sa.Column('calculated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['kpi_definition_id'], ['kpi_definitions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['period_id'], ['planning_periods.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_id'], ['kpi_targets.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_kpi_results_kpi_definition_id'), 'kpi_results', ['kpi_definition_id'], unique=False)
        op.create_index(op.f('ix_kpi_results_organization_id'), 'kpi_results', ['organization_id'], unique=False)
        op.create_index(op.f('ix_kpi_results_period_id'), 'kpi_results', ['period_id'], unique=False)
        op.create_index(op.f('ix_kpi_results_scope_key'), 'kpi_results', ['scope_key'], unique=False)
        op.create_index(op.f('ix_kpi_results_status'), 'kpi_results', ['status'], unique=False)
        op.create_index(op.f('ix_kpi_results_target_id'), 'kpi_results', ['target_id'], unique=False)
    if 'roadmap_items' not in existing:
        op.create_table('roadmap_items',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('initiative_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('roadmap_code', sa.String(length=100), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(['initiative_id'], ['initiatives.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_roadmap_items_initiative_id'), 'roadmap_items', ['initiative_id'], unique=False)
        op.create_index(op.f('ix_roadmap_items_organization_id'), 'roadmap_items', ['organization_id'], unique=False)
        op.create_index(op.f('ix_roadmap_items_roadmap_code'), 'roadmap_items', ['roadmap_code'], unique=False)
        op.create_index(op.f('ix_roadmap_items_status'), 'roadmap_items', ['status'], unique=False)
    if 'corrective_actions' not in existing:
        op.create_table('corrective_actions',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('kpi_result_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('owner_user_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('task_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('closure_note', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['kpi_result_id'], ['kpi_results.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_corrective_actions_kpi_result_id'), 'corrective_actions', ['kpi_result_id'], unique=False)
        op.create_index(op.f('ix_corrective_actions_organization_id'), 'corrective_actions', ['organization_id'], unique=False)
        op.create_index(op.f('ix_corrective_actions_owner_user_id'), 'corrective_actions', ['owner_user_id'], unique=False)
        op.create_index(op.f('ix_corrective_actions_status'), 'corrective_actions', ['status'], unique=False)
        op.create_index(op.f('ix_corrective_actions_task_id'), 'corrective_actions', ['task_id'], unique=False)
    if 'kpi_period_snapshots' not in existing:
        op.create_table('kpi_period_snapshots',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('kpi_result_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('frozen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['kpi_result_id'], ['kpi_results.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_kpi_period_snapshots_kpi_result_id'), 'kpi_period_snapshots', ['kpi_result_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_kpi_period_snapshots_kpi_result_id'), table_name='kpi_period_snapshots')
    op.drop_table('kpi_period_snapshots')
    op.drop_index(op.f('ix_corrective_actions_task_id'), table_name='corrective_actions')
    op.drop_index(op.f('ix_corrective_actions_status'), table_name='corrective_actions')
    op.drop_index(op.f('ix_corrective_actions_owner_user_id'), table_name='corrective_actions')
    op.drop_index(op.f('ix_corrective_actions_organization_id'), table_name='corrective_actions')
    op.drop_index(op.f('ix_corrective_actions_kpi_result_id'), table_name='corrective_actions')
    op.drop_table('corrective_actions')
    op.drop_index(op.f('ix_roadmap_items_status'), table_name='roadmap_items')
    op.drop_index(op.f('ix_roadmap_items_roadmap_code'), table_name='roadmap_items')
    op.drop_index(op.f('ix_roadmap_items_organization_id'), table_name='roadmap_items')
    op.drop_index(op.f('ix_roadmap_items_initiative_id'), table_name='roadmap_items')
    op.drop_table('roadmap_items')
    op.drop_index(op.f('ix_kpi_results_target_id'), table_name='kpi_results')
    op.drop_index(op.f('ix_kpi_results_status'), table_name='kpi_results')
    op.drop_index(op.f('ix_kpi_results_scope_key'), table_name='kpi_results')
    op.drop_index(op.f('ix_kpi_results_period_id'), table_name='kpi_results')
    op.drop_index(op.f('ix_kpi_results_organization_id'), table_name='kpi_results')
    op.drop_index(op.f('ix_kpi_results_kpi_definition_id'), table_name='kpi_results')
    op.drop_table('kpi_results')
    op.drop_index(op.f('ix_initiative_milestones_status'), table_name='initiative_milestones')
    op.drop_index(op.f('ix_initiative_milestones_initiative_id'), table_name='initiative_milestones')
    op.drop_table('initiative_milestones')
    op.drop_index(op.f('ix_scenario_values_scenario_id'), table_name='scenario_values')
    op.drop_index(op.f('ix_scenario_values_period_id'), table_name='scenario_values')
    op.drop_index(op.f('ix_scenario_values_kpi_definition_id'), table_name='scenario_values')
    op.drop_table('scenario_values')
    op.drop_index(op.f('ix_kpi_targets_supersedes_id'), table_name='kpi_targets')
    op.drop_index(op.f('ix_kpi_targets_status'), table_name='kpi_targets')
    op.drop_index(op.f('ix_kpi_targets_scope_vertical_id'), table_name='kpi_targets')
    op.drop_index(op.f('ix_kpi_targets_scope_user_id'), table_name='kpi_targets')
    op.drop_index(op.f('ix_kpi_targets_scope_unit_id'), table_name='kpi_targets')
    op.drop_index(op.f('ix_kpi_targets_period_id'), table_name='kpi_targets')
    op.drop_index(op.f('ix_kpi_targets_organization_id'), table_name='kpi_targets')
    op.drop_index(op.f('ix_kpi_targets_kpi_definition_id'), table_name='kpi_targets')
    op.drop_index(op.f('ix_kpi_targets_goal_id'), table_name='kpi_targets')
    op.drop_index(op.f('ix_kpi_targets_approval_request_id'), table_name='kpi_targets')
    op.drop_table('kpi_targets')
    op.drop_index(op.f('ix_initiatives_status'), table_name='initiatives')
    op.drop_index(op.f('ix_initiatives_owner_user_id'), table_name='initiatives')
    op.drop_index(op.f('ix_initiatives_organization_id'), table_name='initiatives')
    op.drop_index(op.f('ix_initiatives_linked_work_unit_id'), table_name='initiatives')
    op.drop_index(op.f('ix_initiatives_goal_id'), table_name='initiatives')
    op.drop_index(op.f('ix_initiatives_code'), table_name='initiatives')
    op.drop_table('initiatives')
    op.drop_table('goal_kpis')
    op.drop_index(op.f('ix_budget_allocations_target_type'), table_name='budget_allocations')
    op.drop_index(op.f('ix_budget_allocations_target_id'), table_name='budget_allocations')
    op.drop_index(op.f('ix_budget_allocations_budget_line_id'), table_name='budget_allocations')
    op.drop_table('budget_allocations')
    op.drop_index(op.f('ix_budget_actuals_source_event_id'), table_name='budget_actuals')
    op.drop_index(op.f('ix_budget_actuals_occurred_on'), table_name='budget_actuals')
    op.drop_index(op.f('ix_budget_actuals_budget_line_id'), table_name='budget_actuals')
    op.drop_table('budget_actuals')
    op.drop_index(op.f('ix_allocation_history_allocation_id'), table_name='allocation_history')
    op.drop_table('allocation_history')
    op.drop_index(op.f('ix_strategic_goals_status'), table_name='strategic_goals')
    op.drop_index(op.f('ix_strategic_goals_scope_vertical_id'), table_name='strategic_goals')
    op.drop_index(op.f('ix_strategic_goals_scope_unit_id'), table_name='strategic_goals')
    op.drop_index(op.f('ix_strategic_goals_period_id'), table_name='strategic_goals')
    op.drop_index(op.f('ix_strategic_goals_parent_goal_id'), table_name='strategic_goals')
    op.drop_index(op.f('ix_strategic_goals_owner_user_id'), table_name='strategic_goals')
    op.drop_index(op.f('ix_strategic_goals_organization_id'), table_name='strategic_goals')
    op.drop_index(op.f('ix_strategic_goals_code'), table_name='strategic_goals')
    op.drop_table('strategic_goals')
    op.drop_index(op.f('ix_scenarios_status'), table_name='scenarios')
    op.drop_index(op.f('ix_scenarios_organization_id'), table_name='scenarios')
    op.drop_index(op.f('ix_scenarios_base_period_id'), table_name='scenarios')
    op.drop_table('scenarios')
    op.drop_index(op.f('ix_budget_lines_category'), table_name='budget_lines')
    op.drop_index(op.f('ix_budget_lines_budget_id'), table_name='budget_lines')
    op.drop_table('budget_lines')
    op.drop_index(op.f('ix_allocations_subject_type'), table_name='allocations')
    op.drop_index(op.f('ix_allocations_subject_id'), table_name='allocations')
    op.drop_index(op.f('ix_allocations_status'), table_name='allocations')
    op.drop_index(op.f('ix_allocations_start_date'), table_name='allocations')
    op.drop_index(op.f('ix_allocations_resource_id'), table_name='allocations')
    op.drop_index(op.f('ix_allocations_requirement_id'), table_name='allocations')
    op.drop_index(op.f('ix_allocations_organization_id'), table_name='allocations')
    op.drop_index(op.f('ix_allocations_end_date'), table_name='allocations')
    op.drop_table('allocations')
    op.drop_table('resource_skills')
    op.drop_index(op.f('ix_resource_requirements_subject_type'), table_name='resource_requirements')
    op.drop_index(op.f('ix_resource_requirements_subject_id'), table_name='resource_requirements')
    op.drop_index(op.f('ix_resource_requirements_status'), table_name='resource_requirements')
    op.drop_index(op.f('ix_resource_requirements_skill_id'), table_name='resource_requirements')
    op.drop_index(op.f('ix_resource_requirements_organization_id'), table_name='resource_requirements')
    op.drop_table('resource_requirements')
    op.drop_index(op.f('ix_planning_periods_status'), table_name='planning_periods')
    op.drop_index(op.f('ix_planning_periods_parent_period_id'), table_name='planning_periods')
    op.drop_index(op.f('ix_planning_periods_organization_id'), table_name='planning_periods')
    op.drop_index(op.f('ix_planning_periods_fiscal_year_id'), table_name='planning_periods')
    op.drop_table('planning_periods')
    op.drop_index(op.f('ix_kpi_thresholds_scope_unit_id'), table_name='kpi_thresholds')
    op.drop_index(op.f('ix_kpi_thresholds_kpi_definition_id'), table_name='kpi_thresholds')
    op.drop_table('kpi_thresholds')
    op.drop_index(op.f('ix_kpi_sources_kpi_definition_id'), table_name='kpi_sources')
    op.drop_table('kpi_sources')
    op.drop_index(op.f('ix_kpi_measurements_vertical_id'), table_name='kpi_measurements')
    op.drop_index(op.f('ix_kpi_measurements_user_id'), table_name='kpi_measurements')
    op.drop_index(op.f('ix_kpi_measurements_unit_id'), table_name='kpi_measurements')
    op.drop_index(op.f('ix_kpi_measurements_source_event_id'), table_name='kpi_measurements')
    op.drop_index(op.f('ix_kpi_measurements_reverses_id'), table_name='kpi_measurements')
    op.drop_index(op.f('ix_kpi_measurements_organization_id'), table_name='kpi_measurements')
    op.drop_index(op.f('ix_kpi_measurements_offering_id'), table_name='kpi_measurements')
    op.drop_index(op.f('ix_kpi_measurements_measured_on'), table_name='kpi_measurements')
    op.drop_index(op.f('ix_kpi_measurements_kpi_definition_id'), table_name='kpi_measurements')
    op.drop_index(op.f('ix_kpi_measurements_client_id'), table_name='kpi_measurements')
    op.drop_table('kpi_measurements')
    op.drop_index(op.f('ix_capacity_ledger_day'), table_name='capacity_ledger')
    op.drop_table('capacity_ledger')
    op.drop_index(op.f('ix_capacity_gaps_unit_id'), table_name='capacity_gaps')
    op.drop_index(op.f('ix_capacity_gaps_status'), table_name='capacity_gaps')
    op.drop_index(op.f('ix_capacity_gaps_skill_id'), table_name='capacity_gaps')
    op.drop_index(op.f('ix_capacity_gaps_organization_id'), table_name='capacity_gaps')
    op.drop_table('capacity_gaps')
    op.drop_index(op.f('ix_budgets_status'), table_name='budgets')
    op.drop_index(op.f('ix_budgets_scope_vertical_id'), table_name='budgets')
    op.drop_index(op.f('ix_budgets_scope_unit_id'), table_name='budgets')
    op.drop_index(op.f('ix_budgets_organization_id'), table_name='budgets')
    op.drop_index(op.f('ix_budgets_fiscal_year_id'), table_name='budgets')
    op.drop_index(op.f('ix_budgets_code'), table_name='budgets')
    op.drop_index(op.f('ix_budgets_approval_request_id'), table_name='budgets')
    op.drop_table('budgets')
    op.drop_index(op.f('ix_availability_exceptions_starts_at'), table_name='availability_exceptions')
    op.drop_index(op.f('ix_availability_exceptions_resource_id'), table_name='availability_exceptions')
    op.drop_table('availability_exceptions')
    op.drop_index(op.f('ix_skills_organization_id'), table_name='skills')
    op.drop_index(op.f('ix_skills_code'), table_name='skills')
    op.drop_index(op.f('ix_skills_category'), table_name='skills')
    op.drop_table('skills')
    op.drop_index(op.f('ix_resources_user_id'), table_name='resources')
    op.drop_index(op.f('ix_resources_unit_id'), table_name='resources')
    op.drop_index(op.f('ix_resources_status'), table_name='resources')
    op.drop_index(op.f('ix_resources_organization_id'), table_name='resources')
    op.drop_index(op.f('ix_resources_calendar_id'), table_name='resources')
    op.drop_table('resources')
    op.drop_index(op.f('ix_kpi_definitions_status'), table_name='kpi_definitions')
    op.drop_index(op.f('ix_kpi_definitions_owner_user_id'), table_name='kpi_definitions')
    op.drop_index(op.f('ix_kpi_definitions_organization_id'), table_name='kpi_definitions')
    op.drop_index(op.f('ix_kpi_definitions_code'), table_name='kpi_definitions')
    op.drop_table('kpi_definitions')
    op.drop_index(op.f('ix_fiscal_years_status'), table_name='fiscal_years')
    op.drop_index(op.f('ix_fiscal_years_organization_id'), table_name='fiscal_years')
    op.drop_index(op.f('ix_fiscal_years_code'), table_name='fiscal_years')
    op.drop_table('fiscal_years')
