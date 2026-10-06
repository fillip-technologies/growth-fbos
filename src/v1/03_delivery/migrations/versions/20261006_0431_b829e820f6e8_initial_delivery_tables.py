"""initial delivery tables

Revision ID: b829e820f6e8
Revises: 
Create Date: 2026-10-06 04:31:11.592203+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types


revision: str = 'b829e820f6e8'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('code_sequences',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('scope', sa.String(length=100), nullable=False),
    sa.Column('next_value', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'scope', name='uq_code_sequences_org_scope')
    )
    op.create_table('handovers',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('parent_handover_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('subject_type', sa.String(length=100), nullable=False),
    sa.Column('subject_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('from_unit_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('to_unit_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('requested_by', database.types.UUIDType(length=36), nullable=False),
    sa.Column('reason', sa.String(length=255), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('responded_by', database.types.UUIDType(length=36), nullable=True),
    sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rejection_reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['parent_handover_id'], ['handovers.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_handovers_from_unit_id'), 'handovers', ['from_unit_id'], unique=False)
    op.create_index(op.f('ix_handovers_organization_id'), 'handovers', ['organization_id'], unique=False)
    op.create_index(op.f('ix_handovers_parent_handover_id'), 'handovers', ['parent_handover_id'], unique=False)
    op.create_index(op.f('ix_handovers_status'), 'handovers', ['status'], unique=False)
    op.create_index(op.f('ix_handovers_subject_id'), 'handovers', ['subject_id'], unique=False)
    op.create_index(op.f('ix_handovers_subject_type'), 'handovers', ['subject_type'], unique=False)
    op.create_index(op.f('ix_handovers_to_unit_id'), 'handovers', ['to_unit_id'], unique=False)
    op.create_table('task_types',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('category', sa.String(length=100), nullable=False),
    sa.Column('requires_review', sa.Boolean(), nullable=False),
    sa.Column('default_estimate_minutes', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'code', name='uq_task_types_org_code')
    )
    op.create_index(op.f('ix_task_types_code'), 'task_types', ['code'], unique=False)
    op.create_index(op.f('ix_task_types_organization_id'), 'task_types', ['organization_id'], unique=False)
    op.create_table('work_dependencies',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('predecessor_type', sa.String(length=50), nullable=False),
    sa.Column('predecessor_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('successor_type', sa.String(length=50), nullable=False),
    sa.Column('successor_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('dependency_type', sa.String(length=20), nullable=False),
    sa.Column('lag_days', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_work_dependencies_organization_id'), 'work_dependencies', ['organization_id'], unique=False)
    op.create_index(op.f('ix_work_dependencies_predecessor_id'), 'work_dependencies', ['predecessor_id'], unique=False)
    op.create_index(op.f('ix_work_dependencies_successor_id'), 'work_dependencies', ['successor_id'], unique=False)
    op.create_table('work_unit_types',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('category', sa.String(length=100), nullable=False),
    sa.Column('requires_client', sa.Boolean(), nullable=False),
    sa.Column('default_template_code', sa.String(length=100), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'code', name='uq_work_unit_types_org_code')
    )
    op.create_index(op.f('ix_work_unit_types_code'), 'work_unit_types', ['code'], unique=False)
    op.create_index(op.f('ix_work_unit_types_organization_id'), 'work_unit_types', ['organization_id'], unique=False)
    op.create_table('workflow_definitions',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('vertical_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('subject_type', sa.String(length=100), nullable=False),
    sa.Column('current_version_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'code', name='uq_workflow_definitions_org_code')
    )
    op.create_index(op.f('ix_workflow_definitions_code'), 'workflow_definitions', ['code'], unique=False)
    op.create_index(op.f('ix_workflow_definitions_current_version_id'), 'workflow_definitions', ['current_version_id'], unique=False)
    op.create_index(op.f('ix_workflow_definitions_organization_id'), 'workflow_definitions', ['organization_id'], unique=False)
    op.create_index(op.f('ix_workflow_definitions_status'), 'workflow_definitions', ['status'], unique=False)
    op.create_index(op.f('ix_workflow_definitions_subject_type'), 'workflow_definitions', ['subject_type'], unique=False)
    op.create_index(op.f('ix_workflow_definitions_vertical_id'), 'workflow_definitions', ['vertical_id'], unique=False)
    op.create_table('task_templates',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('task_type_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('title_template', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('checklist', sa.JSON(), nullable=True),
    sa.Column('estimate_minutes', sa.Integer(), nullable=True),
    sa.Column('default_priority', sa.String(length=50), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['task_type_id'], ['task_types.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'code', name='uq_task_templates_org_code')
    )
    op.create_index(op.f('ix_task_templates_code'), 'task_templates', ['code'], unique=False)
    op.create_index(op.f('ix_task_templates_organization_id'), 'task_templates', ['organization_id'], unique=False)
    op.create_index(op.f('ix_task_templates_task_type_id'), 'task_templates', ['task_type_id'], unique=False)
    op.create_table('work_templates',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('work_unit_type_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('vertical_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.ForeignKeyConstraint(['work_unit_type_id'], ['work_unit_types.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'code', name='uq_work_templates_org_code')
    )
    op.create_index(op.f('ix_work_templates_code'), 'work_templates', ['code'], unique=False)
    op.create_index(op.f('ix_work_templates_organization_id'), 'work_templates', ['organization_id'], unique=False)
    op.create_index(op.f('ix_work_templates_status'), 'work_templates', ['status'], unique=False)
    op.create_index(op.f('ix_work_templates_vertical_id'), 'work_templates', ['vertical_id'], unique=False)
    op.create_index(op.f('ix_work_templates_work_unit_type_id'), 'work_templates', ['work_unit_type_id'], unique=False)
    op.create_table('workflow_versions',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('definition_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('checksum', sa.String(length=64), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_by', database.types.UUIDType(length=36), nullable=True),
    sa.ForeignKeyConstraint(['definition_id'], ['workflow_definitions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workflow_versions_definition_id'), 'workflow_versions', ['definition_id'], unique=False)
    op.create_index(op.f('ix_workflow_versions_status'), 'workflow_versions', ['status'], unique=False)
    op.create_table('recurring_task_rules',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('template_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('subject_type', sa.String(length=100), nullable=True),
    sa.Column('subject_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('owning_unit_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('rrule', sa.String(length=255), nullable=False),
    sa.Column('timezone', sa.String(length=100), nullable=False),
    sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.ForeignKeyConstraint(['template_id'], ['task_templates.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_recurring_task_rules_next_run_at'), 'recurring_task_rules', ['next_run_at'], unique=False)
    op.create_index(op.f('ix_recurring_task_rules_organization_id'), 'recurring_task_rules', ['organization_id'], unique=False)
    op.create_index(op.f('ix_recurring_task_rules_owning_unit_id'), 'recurring_task_rules', ['owning_unit_id'], unique=False)
    op.create_index(op.f('ix_recurring_task_rules_status'), 'recurring_task_rules', ['status'], unique=False)
    op.create_index(op.f('ix_recurring_task_rules_subject_id'), 'recurring_task_rules', ['subject_id'], unique=False)
    op.create_index(op.f('ix_recurring_task_rules_subject_type'), 'recurring_task_rules', ['subject_type'], unique=False)
    op.create_index(op.f('ix_recurring_task_rules_template_id'), 'recurring_task_rules', ['template_id'], unique=False)
    op.create_table('stages',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('version_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('stage_type', sa.String(length=50), nullable=False),
    sa.Column('owner_unit_selector', sa.JSON(), nullable=True),
    sa.Column('sla_policy_code', sa.String(length=100), nullable=True),
    sa.Column('exit_criteria', sa.JSON(), nullable=True),
    sa.Column('allow_parallel', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['version_id'], ['workflow_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_stages_code'), 'stages', ['code'], unique=False)
    op.create_index(op.f('ix_stages_version_id'), 'stages', ['version_id'], unique=False)
    op.create_table('tasks',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('parent_task_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('subject_type', sa.String(length=100), nullable=True),
    sa.Column('subject_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('work_unit_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('workflow_instance_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('stage_run_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('source', sa.String(length=50), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('owning_unit_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('scope_path', sa.String(length=255), nullable=True),
    sa.Column('assignee_user_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('reviewer_user_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('task_type_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('priority', sa.String(length=50), nullable=False),
    sa.Column('template_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('review_round', sa.Integer(), nullable=False),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('estimate_minutes', sa.Integer(), nullable=True),
    sa.Column('logged_minutes', sa.Integer(), nullable=False),
    sa.Column('progress_pct', sa.Integer(), nullable=False),
    sa.Column('attributes', sa.JSON(), nullable=True),
    sa.Column('created_by', database.types.UUIDType(length=36), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['parent_task_id'], ['tasks.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['task_type_id'], ['task_types.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['template_id'], ['task_templates.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'code', name='uq_tasks_org_code')
    )
    op.create_index(op.f('ix_tasks_assignee_user_id'), 'tasks', ['assignee_user_id'], unique=False)
    op.create_index(op.f('ix_tasks_code'), 'tasks', ['code'], unique=False)
    op.create_index(op.f('ix_tasks_organization_id'), 'tasks', ['organization_id'], unique=False)
    op.create_index(op.f('ix_tasks_owning_unit_id'), 'tasks', ['owning_unit_id'], unique=False)
    op.create_index(op.f('ix_tasks_parent_task_id'), 'tasks', ['parent_task_id'], unique=False)
    op.create_index(op.f('ix_tasks_reviewer_user_id'), 'tasks', ['reviewer_user_id'], unique=False)
    op.create_index(op.f('ix_tasks_scope_path'), 'tasks', ['scope_path'], unique=False)
    op.create_index(op.f('ix_tasks_stage_run_id'), 'tasks', ['stage_run_id'], unique=False)
    op.create_index(op.f('ix_tasks_status'), 'tasks', ['status'], unique=False)
    op.create_index(op.f('ix_tasks_subject_id'), 'tasks', ['subject_id'], unique=False)
    op.create_index(op.f('ix_tasks_subject_type'), 'tasks', ['subject_type'], unique=False)
    op.create_index(op.f('ix_tasks_task_type_id'), 'tasks', ['task_type_id'], unique=False)
    op.create_index(op.f('ix_tasks_template_id'), 'tasks', ['template_id'], unique=False)
    op.create_index(op.f('ix_tasks_work_unit_id'), 'tasks', ['work_unit_id'], unique=False)
    op.create_index(op.f('ix_tasks_workflow_instance_id'), 'tasks', ['workflow_instance_id'], unique=False)
    op.create_table('work_template_versions',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('template_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('structure', sa.JSON(), nullable=True),
    sa.Column('workflow_definition_code', sa.String(length=100), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_by', database.types.UUIDType(length=36), nullable=True),
    sa.ForeignKeyConstraint(['template_id'], ['work_templates.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_work_template_versions_template_id'), 'work_template_versions', ['template_id'], unique=False)
    op.create_table('workflow_instances',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('version_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('subject_type', sa.String(length=100), nullable=False),
    sa.Column('subject_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('scope_path', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('context', sa.JSON(), nullable=True),
    sa.Column('started_by', database.types.UUIDType(length=36), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['version_id'], ['workflow_versions.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workflow_instances_organization_id'), 'workflow_instances', ['organization_id'], unique=False)
    op.create_index(op.f('ix_workflow_instances_scope_path'), 'workflow_instances', ['scope_path'], unique=False)
    op.create_index(op.f('ix_workflow_instances_status'), 'workflow_instances', ['status'], unique=False)
    op.create_index(op.f('ix_workflow_instances_subject_id'), 'workflow_instances', ['subject_id'], unique=False)
    op.create_index(op.f('ix_workflow_instances_subject_type'), 'workflow_instances', ['subject_type'], unique=False)
    op.create_index(op.f('ix_workflow_instances_version_id'), 'workflow_instances', ['version_id'], unique=False)
    op.create_table('automation_rules',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('version_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('stage_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('trigger', sa.String(length=100), nullable=False),
    sa.Column('condition', sa.JSON(), nullable=True),
    sa.Column('actions', sa.JSON(), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['stage_id'], ['stages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['version_id'], ['workflow_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_automation_rules_stage_id'), 'automation_rules', ['stage_id'], unique=False)
    op.create_index(op.f('ix_automation_rules_version_id'), 'automation_rules', ['version_id'], unique=False)
    op.create_table('checklist_items',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('task_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('text', sa.String(length=500), nullable=False),
    sa.Column('mandatory', sa.Boolean(), nullable=False),
    sa.Column('done_by', database.types.UUIDType(length=36), nullable=True),
    sa.Column('done_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_checklist_items_task_id'), 'checklist_items', ['task_id'], unique=False)
    op.create_table('stage_task_templates',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('stage_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('task_template_code', sa.String(length=100), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('required', sa.Boolean(), nullable=False),
    sa.Column('assignee_selector', sa.JSON(), nullable=True),
    sa.Column('due_offset_minutes', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['stage_id'], ['stages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_stage_task_templates_stage_id'), 'stage_task_templates', ['stage_id'], unique=False)
    op.create_index(op.f('ix_stage_task_templates_task_template_code'), 'stage_task_templates', ['task_template_code'], unique=False)
    op.create_table('task_assignments',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('task_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('unit_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('user_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('assignment_role', sa.String(length=100), nullable=False),
    sa.Column('assigned_by', database.types.UUIDType(length=36), nullable=True),
    sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('end_reason', sa.String(length=255), nullable=True),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_task_assignments_task_id'), 'task_assignments', ['task_id'], unique=False)
    op.create_index(op.f('ix_task_assignments_unit_id'), 'task_assignments', ['unit_id'], unique=False)
    op.create_index(op.f('ix_task_assignments_user_id'), 'task_assignments', ['user_id'], unique=False)
    op.create_table('task_comments',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('task_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('author_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('mentions', sa.JSON(), nullable=True),
    sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_task_comments_author_id'), 'task_comments', ['author_id'], unique=False)
    op.create_index(op.f('ix_task_comments_task_id'), 'task_comments', ['task_id'], unique=False)
    op.create_table('task_dependencies',
    sa.Column('task_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('depends_on_task_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('dependency_type', sa.String(length=20), nullable=False),
    sa.ForeignKeyConstraint(['depends_on_task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('task_id', 'depends_on_task_id')
    )
    op.create_table('task_reviews',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('task_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('round', sa.Integer(), nullable=False),
    sa.Column('reviewer_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('result', sa.String(length=50), nullable=False),
    sa.Column('rating', sa.Integer(), nullable=True),
    sa.Column('feedback', sa.Text(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_task_reviews_reviewer_id'), 'task_reviews', ['reviewer_id'], unique=False)
    op.create_index(op.f('ix_task_reviews_task_id'), 'task_reviews', ['task_id'], unique=False)
    op.create_table('task_status_history',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('task_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('from_status', sa.String(length=50), nullable=True),
    sa.Column('to_status', sa.String(length=50), nullable=False),
    sa.Column('changed_by', database.types.UUIDType(length=36), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_task_status_history_task_id'), 'task_status_history', ['task_id'], unique=False)
    op.create_table('task_watchers',
    sa.Column('task_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('user_id', database.types.UUIDType(length=36), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('task_id', 'user_id')
    )
    op.create_table('time_entries',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('task_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('user_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('work_date', sa.Date(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('minutes', sa.Integer(), nullable=False),
    sa.Column('billable', sa.Boolean(), nullable=False),
    sa.Column('source', sa.String(length=50), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('approved_by', database.types.UUIDType(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_time_entries_organization_id'), 'time_entries', ['organization_id'], unique=False)
    op.create_index(op.f('ix_time_entries_task_id'), 'time_entries', ['task_id'], unique=False)
    op.create_index(op.f('ix_time_entries_user_id'), 'time_entries', ['user_id'], unique=False)
    op.create_table('transitions',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('version_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('trigger_type', sa.String(length=50), nullable=False),
    sa.Column('from_stage_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('to_stage_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('condition', sa.JSON(), nullable=True),
    sa.Column('approval_policy_code', sa.String(length=100), nullable=True),
    sa.Column('allowed_permission', sa.String(length=100), nullable=True),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['from_stage_id'], ['stages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['to_stage_id'], ['stages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['version_id'], ['workflow_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_transitions_code'), 'transitions', ['code'], unique=False)
    op.create_index(op.f('ix_transitions_from_stage_id'), 'transitions', ['from_stage_id'], unique=False)
    op.create_index(op.f('ix_transitions_to_stage_id'), 'transitions', ['to_stage_id'], unique=False)
    op.create_index(op.f('ix_transitions_version_id'), 'transitions', ['version_id'], unique=False)
    op.create_table('work_units',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('parent_work_unit_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('objective', sa.Text(), nullable=True),
    sa.Column('work_unit_type_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('template_version_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('vertical_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('owning_unit_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('scope_path', sa.String(length=255), nullable=True),
    sa.Column('client_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('contract_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('deal_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('manager_user_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('planned_start', sa.Date(), nullable=True),
    sa.Column('planned_end', sa.Date(), nullable=True),
    sa.Column('actual_start', sa.Date(), nullable=True),
    sa.Column('actual_end', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('priority', sa.String(length=50), nullable=False),
    sa.Column('billable', sa.Boolean(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('progress_pct', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('health', sa.String(length=50), nullable=False),
    sa.Column('attributes', sa.JSON(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['parent_work_unit_id'], ['work_units.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['template_version_id'], ['work_template_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['work_unit_type_id'], ['work_unit_types.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'code', name='uq_work_units_org_code')
    )
    op.create_index(op.f('ix_work_units_client_id'), 'work_units', ['client_id'], unique=False)
    op.create_index(op.f('ix_work_units_code'), 'work_units', ['code'], unique=False)
    op.create_index(op.f('ix_work_units_contract_id'), 'work_units', ['contract_id'], unique=False)
    op.create_index(op.f('ix_work_units_deal_id'), 'work_units', ['deal_id'], unique=False)
    op.create_index(op.f('ix_work_units_manager_user_id'), 'work_units', ['manager_user_id'], unique=False)
    op.create_index(op.f('ix_work_units_organization_id'), 'work_units', ['organization_id'], unique=False)
    op.create_index(op.f('ix_work_units_owning_unit_id'), 'work_units', ['owning_unit_id'], unique=False)
    op.create_index(op.f('ix_work_units_parent_work_unit_id'), 'work_units', ['parent_work_unit_id'], unique=False)
    op.create_index(op.f('ix_work_units_scope_path'), 'work_units', ['scope_path'], unique=False)
    op.create_index(op.f('ix_work_units_status'), 'work_units', ['status'], unique=False)
    op.create_index(op.f('ix_work_units_template_version_id'), 'work_units', ['template_version_id'], unique=False)
    op.create_index(op.f('ix_work_units_vertical_id'), 'work_units', ['vertical_id'], unique=False)
    op.create_index(op.f('ix_work_units_work_unit_type_id'), 'work_units', ['work_unit_type_id'], unique=False)
    op.create_table('baselines',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('work_unit_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('baseline_no', sa.Integer(), nullable=False),
    sa.Column('snapshot', sa.JSON(), nullable=False),
    sa.Column('approved_by', database.types.UUIDType(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['work_unit_id'], ['work_units.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_baselines_work_unit_id'), 'baselines', ['work_unit_id'], unique=False)
    op.create_table('change_requests',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('work_unit_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('cr_no', sa.String(length=100), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('scope_impact', sa.Text(), nullable=True),
    sa.Column('schedule_impact_days', sa.Integer(), nullable=False),
    sa.Column('cost_impact', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('approval_request_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('amends_contract', sa.Boolean(), nullable=False),
    sa.Column('decided_by', database.types.UUIDType(length=36), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['work_unit_id'], ['work_units.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_change_requests_cr_no'), 'change_requests', ['cr_no'], unique=False)
    op.create_index(op.f('ix_change_requests_status'), 'change_requests', ['status'], unique=False)
    op.create_index(op.f('ix_change_requests_work_unit_id'), 'change_requests', ['work_unit_id'], unique=False)
    op.create_table('closures',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('work_unit_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('lessons_learned', sa.Text(), nullable=True),
    sa.Column('client_signoff_document_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('closed_by', database.types.UUIDType(length=36), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['work_unit_id'], ['work_units.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_closures_work_unit_id'), 'closures', ['work_unit_id'], unique=True)
    op.create_table('cost_entries',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('work_unit_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('category', sa.String(length=100), nullable=False),
    sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('occurred_on', sa.Date(), nullable=False),
    sa.Column('source_type', sa.String(length=50), nullable=False),
    sa.Column('source_ref', sa.String(length=255), nullable=True),
    sa.Column('source_event_id', database.types.UUIDType(length=36), nullable=True),
    sa.ForeignKeyConstraint(['work_unit_id'], ['work_units.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cost_entries_work_unit_id'), 'cost_entries', ['work_unit_id'], unique=False)
    op.create_table('issues',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('work_unit_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('severity', sa.String(length=50), nullable=False),
    sa.Column('owner_user_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('resolution', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['work_unit_id'], ['work_units.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_issues_status'), 'issues', ['status'], unique=False)
    op.create_index(op.f('ix_issues_work_unit_id'), 'issues', ['work_unit_id'], unique=False)
    op.create_table('pending_signals',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('instance_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('transition_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('awaited_event_type', sa.String(length=100), nullable=False),
    sa.Column('correlation_key', sa.String(length=255), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.ForeignKeyConstraint(['instance_id'], ['workflow_instances.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['transition_id'], ['transitions.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pending_signals_awaited_event_type'), 'pending_signals', ['awaited_event_type'], unique=False)
    op.create_index(op.f('ix_pending_signals_correlation_key'), 'pending_signals', ['correlation_key'], unique=False)
    op.create_index(op.f('ix_pending_signals_instance_id'), 'pending_signals', ['instance_id'], unique=False)
    op.create_index(op.f('ix_pending_signals_status'), 'pending_signals', ['status'], unique=False)
    op.create_index(op.f('ix_pending_signals_transition_id'), 'pending_signals', ['transition_id'], unique=False)
    op.create_table('phases',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('work_unit_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('planned_start', sa.Date(), nullable=True),
    sa.Column('planned_end', sa.Date(), nullable=True),
    sa.Column('actual_start', sa.Date(), nullable=True),
    sa.Column('actual_end', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.ForeignKeyConstraint(['work_unit_id'], ['work_units.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_phases_status'), 'phases', ['status'], unique=False)
    op.create_index(op.f('ix_phases_work_unit_id'), 'phases', ['work_unit_id'], unique=False)
    op.create_table('progress_snapshots',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('work_unit_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('as_of', sa.Date(), nullable=False),
    sa.Column('planned_pct', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('actual_pct', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('spi', sa.Numeric(precision=6, scale=3), nullable=True),
    sa.Column('cpi', sa.Numeric(precision=6, scale=3), nullable=True),
    sa.Column('health_overall', sa.String(length=50), nullable=False),
    sa.Column('health_schedule', sa.String(length=50), nullable=False),
    sa.Column('health_cost', sa.String(length=50), nullable=False),
    sa.Column('health_resource', sa.String(length=50), nullable=False),
    sa.Column('health_risk', sa.String(length=50), nullable=False),
    sa.ForeignKeyConstraint(['work_unit_id'], ['work_units.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_progress_snapshots_work_unit_id'), 'progress_snapshots', ['work_unit_id'], unique=False)
    op.create_table('risks',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('work_unit_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('probability', sa.Integer(), nullable=False),
    sa.Column('impact', sa.Integer(), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('mitigation', sa.Text(), nullable=True),
    sa.Column('owner_user_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.ForeignKeyConstraint(['work_unit_id'], ['work_units.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_risks_status'), 'risks', ['status'], unique=False)
    op.create_index(op.f('ix_risks_work_unit_id'), 'risks', ['work_unit_id'], unique=False)
    op.create_table('stage_runs',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('instance_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('stage_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('iteration', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('owner_unit_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('entered_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('exited_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('entered_via_transition_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('exited_via_transition_id', database.types.UUIDType(length=36), nullable=True),
    sa.ForeignKeyConstraint(['entered_via_transition_id'], ['transitions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['exited_via_transition_id'], ['transitions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['instance_id'], ['workflow_instances.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['stage_id'], ['stages.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_stage_runs_instance_id'), 'stage_runs', ['instance_id'], unique=False)
    op.create_index(op.f('ix_stage_runs_stage_id'), 'stage_runs', ['stage_id'], unique=False)
    op.create_index(op.f('ix_stage_runs_status'), 'stage_runs', ['status'], unique=False)
    op.create_table('status_history',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('work_unit_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('from_status', sa.String(length=50), nullable=True),
    sa.Column('to_status', sa.String(length=50), nullable=False),
    sa.Column('changed_by', database.types.UUIDType(length=36), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['work_unit_id'], ['work_units.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_status_history_work_unit_id'), 'status_history', ['work_unit_id'], unique=False)
    op.create_table('work_budgets',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('work_unit_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('planned_amount', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('approved_amount', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['work_unit_id'], ['work_units.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_work_budgets_work_unit_id'), 'work_budgets', ['work_unit_id'], unique=False)
    op.create_table('work_unit_members',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('work_unit_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('user_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('member_role', sa.String(length=100), nullable=False),
    sa.Column('allocation_pct', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('valid_from', sa.Date(), nullable=False),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.ForeignKeyConstraint(['work_unit_id'], ['work_units.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_work_unit_members_user_id'), 'work_unit_members', ['user_id'], unique=False)
    op.create_index(op.f('ix_work_unit_members_work_unit_id'), 'work_unit_members', ['work_unit_id'], unique=False)
    op.create_table('work_unit_services',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('work_unit_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('offering_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('contract_item_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['work_unit_id'], ['work_units.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_work_unit_services_offering_id'), 'work_unit_services', ['offering_id'], unique=False)
    op.create_index(op.f('ix_work_unit_services_work_unit_id'), 'work_unit_services', ['work_unit_id'], unique=False)
    op.create_table('action_executions',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('instance_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('rule_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('stage_run_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('action_type', sa.String(length=100), nullable=False),
    sa.Column('idempotency_key', sa.String(length=255), nullable=False),
    sa.Column('input', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['instance_id'], ['workflow_instances.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['rule_id'], ['automation_rules.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['stage_run_id'], ['stage_runs.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_action_executions_idempotency_key'), 'action_executions', ['idempotency_key'], unique=True)
    op.create_index(op.f('ix_action_executions_instance_id'), 'action_executions', ['instance_id'], unique=False)
    op.create_index(op.f('ix_action_executions_rule_id'), 'action_executions', ['rule_id'], unique=False)
    op.create_index(op.f('ix_action_executions_stage_run_id'), 'action_executions', ['stage_run_id'], unique=False)
    op.create_index(op.f('ix_action_executions_status'), 'action_executions', ['status'], unique=False)
    op.create_table('milestones',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('work_unit_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('phase_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('weight', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('planned_date', sa.Date(), nullable=False),
    sa.Column('forecast_date', sa.Date(), nullable=True),
    sa.Column('actual_date', sa.Date(), nullable=True),
    sa.Column('is_billing_milestone', sa.Boolean(), nullable=False),
    sa.Column('requires_client_acceptance', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.ForeignKeyConstraint(['phase_id'], ['phases.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['work_unit_id'], ['work_units.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_milestones_code'), 'milestones', ['code'], unique=False)
    op.create_index(op.f('ix_milestones_phase_id'), 'milestones', ['phase_id'], unique=False)
    op.create_index(op.f('ix_milestones_status'), 'milestones', ['status'], unique=False)
    op.create_index(op.f('ix_milestones_work_unit_id'), 'milestones', ['work_unit_id'], unique=False)
    op.create_table('transition_log',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('instance_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('transition_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('from_stage_run_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('to_stage_run_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('performed_by', database.types.UUIDType(length=36), nullable=True),
    sa.Column('performed_by_type', sa.String(length=50), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('approval_request_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('performed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['from_stage_run_id'], ['stage_runs.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['instance_id'], ['workflow_instances.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['to_stage_run_id'], ['stage_runs.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['transition_id'], ['transitions.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_transition_log_from_stage_run_id'), 'transition_log', ['from_stage_run_id'], unique=False)
    op.create_index(op.f('ix_transition_log_instance_id'), 'transition_log', ['instance_id'], unique=False)
    op.create_index(op.f('ix_transition_log_to_stage_run_id'), 'transition_log', ['to_stage_run_id'], unique=False)
    op.create_index(op.f('ix_transition_log_transition_id'), 'transition_log', ['transition_id'], unique=False)
    op.create_table('work_packages',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('work_unit_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('phase_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('owner_unit_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('estimated_hours', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.ForeignKeyConstraint(['phase_id'], ['phases.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['work_unit_id'], ['work_units.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_work_packages_phase_id'), 'work_packages', ['phase_id'], unique=False)
    op.create_index(op.f('ix_work_packages_status'), 'work_packages', ['status'], unique=False)
    op.create_index(op.f('ix_work_packages_work_unit_id'), 'work_packages', ['work_unit_id'], unique=False)
    op.create_table('deliverables',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('milestone_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('document_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('accepted_by', sa.String(length=255), nullable=True),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['milestone_id'], ['milestones.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_deliverables_milestone_id'), 'deliverables', ['milestone_id'], unique=False)
    op.create_index(op.f('ix_deliverables_status'), 'deliverables', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_deliverables_status'), table_name='deliverables')
    op.drop_index(op.f('ix_deliverables_milestone_id'), table_name='deliverables')
    op.drop_table('deliverables')
    op.drop_index(op.f('ix_work_packages_work_unit_id'), table_name='work_packages')
    op.drop_index(op.f('ix_work_packages_status'), table_name='work_packages')
    op.drop_index(op.f('ix_work_packages_phase_id'), table_name='work_packages')
    op.drop_table('work_packages')
    op.drop_index(op.f('ix_transition_log_transition_id'), table_name='transition_log')
    op.drop_index(op.f('ix_transition_log_to_stage_run_id'), table_name='transition_log')
    op.drop_index(op.f('ix_transition_log_instance_id'), table_name='transition_log')
    op.drop_index(op.f('ix_transition_log_from_stage_run_id'), table_name='transition_log')
    op.drop_table('transition_log')
    op.drop_index(op.f('ix_milestones_work_unit_id'), table_name='milestones')
    op.drop_index(op.f('ix_milestones_status'), table_name='milestones')
    op.drop_index(op.f('ix_milestones_phase_id'), table_name='milestones')
    op.drop_index(op.f('ix_milestones_code'), table_name='milestones')
    op.drop_table('milestones')
    op.drop_index(op.f('ix_action_executions_status'), table_name='action_executions')
    op.drop_index(op.f('ix_action_executions_stage_run_id'), table_name='action_executions')
    op.drop_index(op.f('ix_action_executions_rule_id'), table_name='action_executions')
    op.drop_index(op.f('ix_action_executions_instance_id'), table_name='action_executions')
    op.drop_index(op.f('ix_action_executions_idempotency_key'), table_name='action_executions')
    op.drop_table('action_executions')
    op.drop_index(op.f('ix_work_unit_services_work_unit_id'), table_name='work_unit_services')
    op.drop_index(op.f('ix_work_unit_services_offering_id'), table_name='work_unit_services')
    op.drop_table('work_unit_services')
    op.drop_index(op.f('ix_work_unit_members_work_unit_id'), table_name='work_unit_members')
    op.drop_index(op.f('ix_work_unit_members_user_id'), table_name='work_unit_members')
    op.drop_table('work_unit_members')
    op.drop_index(op.f('ix_work_budgets_work_unit_id'), table_name='work_budgets')
    op.drop_table('work_budgets')
    op.drop_index(op.f('ix_status_history_work_unit_id'), table_name='status_history')
    op.drop_table('status_history')
    op.drop_index(op.f('ix_stage_runs_status'), table_name='stage_runs')
    op.drop_index(op.f('ix_stage_runs_stage_id'), table_name='stage_runs')
    op.drop_index(op.f('ix_stage_runs_instance_id'), table_name='stage_runs')
    op.drop_table('stage_runs')
    op.drop_index(op.f('ix_risks_work_unit_id'), table_name='risks')
    op.drop_index(op.f('ix_risks_status'), table_name='risks')
    op.drop_table('risks')
    op.drop_index(op.f('ix_progress_snapshots_work_unit_id'), table_name='progress_snapshots')
    op.drop_table('progress_snapshots')
    op.drop_index(op.f('ix_phases_work_unit_id'), table_name='phases')
    op.drop_index(op.f('ix_phases_status'), table_name='phases')
    op.drop_table('phases')
    op.drop_index(op.f('ix_pending_signals_transition_id'), table_name='pending_signals')
    op.drop_index(op.f('ix_pending_signals_status'), table_name='pending_signals')
    op.drop_index(op.f('ix_pending_signals_instance_id'), table_name='pending_signals')
    op.drop_index(op.f('ix_pending_signals_correlation_key'), table_name='pending_signals')
    op.drop_index(op.f('ix_pending_signals_awaited_event_type'), table_name='pending_signals')
    op.drop_table('pending_signals')
    op.drop_index(op.f('ix_issues_work_unit_id'), table_name='issues')
    op.drop_index(op.f('ix_issues_status'), table_name='issues')
    op.drop_table('issues')
    op.drop_index(op.f('ix_cost_entries_work_unit_id'), table_name='cost_entries')
    op.drop_table('cost_entries')
    op.drop_index(op.f('ix_closures_work_unit_id'), table_name='closures')
    op.drop_table('closures')
    op.drop_index(op.f('ix_change_requests_work_unit_id'), table_name='change_requests')
    op.drop_index(op.f('ix_change_requests_status'), table_name='change_requests')
    op.drop_index(op.f('ix_change_requests_cr_no'), table_name='change_requests')
    op.drop_table('change_requests')
    op.drop_index(op.f('ix_baselines_work_unit_id'), table_name='baselines')
    op.drop_table('baselines')
    op.drop_index(op.f('ix_work_units_work_unit_type_id'), table_name='work_units')
    op.drop_index(op.f('ix_work_units_vertical_id'), table_name='work_units')
    op.drop_index(op.f('ix_work_units_template_version_id'), table_name='work_units')
    op.drop_index(op.f('ix_work_units_status'), table_name='work_units')
    op.drop_index(op.f('ix_work_units_scope_path'), table_name='work_units')
    op.drop_index(op.f('ix_work_units_parent_work_unit_id'), table_name='work_units')
    op.drop_index(op.f('ix_work_units_owning_unit_id'), table_name='work_units')
    op.drop_index(op.f('ix_work_units_organization_id'), table_name='work_units')
    op.drop_index(op.f('ix_work_units_manager_user_id'), table_name='work_units')
    op.drop_index(op.f('ix_work_units_deal_id'), table_name='work_units')
    op.drop_index(op.f('ix_work_units_contract_id'), table_name='work_units')
    op.drop_index(op.f('ix_work_units_code'), table_name='work_units')
    op.drop_index(op.f('ix_work_units_client_id'), table_name='work_units')
    op.drop_table('work_units')
    op.drop_index(op.f('ix_transitions_version_id'), table_name='transitions')
    op.drop_index(op.f('ix_transitions_to_stage_id'), table_name='transitions')
    op.drop_index(op.f('ix_transitions_from_stage_id'), table_name='transitions')
    op.drop_index(op.f('ix_transitions_code'), table_name='transitions')
    op.drop_table('transitions')
    op.drop_index(op.f('ix_time_entries_user_id'), table_name='time_entries')
    op.drop_index(op.f('ix_time_entries_task_id'), table_name='time_entries')
    op.drop_index(op.f('ix_time_entries_organization_id'), table_name='time_entries')
    op.drop_table('time_entries')
    op.drop_table('task_watchers')
    op.drop_index(op.f('ix_task_status_history_task_id'), table_name='task_status_history')
    op.drop_table('task_status_history')
    op.drop_index(op.f('ix_task_reviews_task_id'), table_name='task_reviews')
    op.drop_index(op.f('ix_task_reviews_reviewer_id'), table_name='task_reviews')
    op.drop_table('task_reviews')
    op.drop_table('task_dependencies')
    op.drop_index(op.f('ix_task_comments_task_id'), table_name='task_comments')
    op.drop_index(op.f('ix_task_comments_author_id'), table_name='task_comments')
    op.drop_table('task_comments')
    op.drop_index(op.f('ix_task_assignments_user_id'), table_name='task_assignments')
    op.drop_index(op.f('ix_task_assignments_unit_id'), table_name='task_assignments')
    op.drop_index(op.f('ix_task_assignments_task_id'), table_name='task_assignments')
    op.drop_table('task_assignments')
    op.drop_index(op.f('ix_stage_task_templates_task_template_code'), table_name='stage_task_templates')
    op.drop_index(op.f('ix_stage_task_templates_stage_id'), table_name='stage_task_templates')
    op.drop_table('stage_task_templates')
    op.drop_index(op.f('ix_checklist_items_task_id'), table_name='checklist_items')
    op.drop_table('checklist_items')
    op.drop_index(op.f('ix_automation_rules_version_id'), table_name='automation_rules')
    op.drop_index(op.f('ix_automation_rules_stage_id'), table_name='automation_rules')
    op.drop_table('automation_rules')
    op.drop_index(op.f('ix_workflow_instances_version_id'), table_name='workflow_instances')
    op.drop_index(op.f('ix_workflow_instances_subject_type'), table_name='workflow_instances')
    op.drop_index(op.f('ix_workflow_instances_subject_id'), table_name='workflow_instances')
    op.drop_index(op.f('ix_workflow_instances_status'), table_name='workflow_instances')
    op.drop_index(op.f('ix_workflow_instances_scope_path'), table_name='workflow_instances')
    op.drop_index(op.f('ix_workflow_instances_organization_id'), table_name='workflow_instances')
    op.drop_table('workflow_instances')
    op.drop_index(op.f('ix_work_template_versions_template_id'), table_name='work_template_versions')
    op.drop_table('work_template_versions')
    op.drop_index(op.f('ix_tasks_workflow_instance_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_work_unit_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_template_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_task_type_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_subject_type'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_subject_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_status'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_stage_run_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_scope_path'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_reviewer_user_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_parent_task_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_owning_unit_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_organization_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_code'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_assignee_user_id'), table_name='tasks')
    op.drop_table('tasks')
    op.drop_index(op.f('ix_stages_version_id'), table_name='stages')
    op.drop_index(op.f('ix_stages_code'), table_name='stages')
    op.drop_table('stages')
    op.drop_index(op.f('ix_recurring_task_rules_template_id'), table_name='recurring_task_rules')
    op.drop_index(op.f('ix_recurring_task_rules_subject_type'), table_name='recurring_task_rules')
    op.drop_index(op.f('ix_recurring_task_rules_subject_id'), table_name='recurring_task_rules')
    op.drop_index(op.f('ix_recurring_task_rules_status'), table_name='recurring_task_rules')
    op.drop_index(op.f('ix_recurring_task_rules_owning_unit_id'), table_name='recurring_task_rules')
    op.drop_index(op.f('ix_recurring_task_rules_organization_id'), table_name='recurring_task_rules')
    op.drop_index(op.f('ix_recurring_task_rules_next_run_at'), table_name='recurring_task_rules')
    op.drop_table('recurring_task_rules')
    op.drop_index(op.f('ix_workflow_versions_status'), table_name='workflow_versions')
    op.drop_index(op.f('ix_workflow_versions_definition_id'), table_name='workflow_versions')
    op.drop_table('workflow_versions')
    op.drop_index(op.f('ix_work_templates_work_unit_type_id'), table_name='work_templates')
    op.drop_index(op.f('ix_work_templates_vertical_id'), table_name='work_templates')
    op.drop_index(op.f('ix_work_templates_status'), table_name='work_templates')
    op.drop_index(op.f('ix_work_templates_organization_id'), table_name='work_templates')
    op.drop_index(op.f('ix_work_templates_code'), table_name='work_templates')
    op.drop_table('work_templates')
    op.drop_index(op.f('ix_task_templates_task_type_id'), table_name='task_templates')
    op.drop_index(op.f('ix_task_templates_organization_id'), table_name='task_templates')
    op.drop_index(op.f('ix_task_templates_code'), table_name='task_templates')
    op.drop_table('task_templates')
    op.drop_index(op.f('ix_workflow_definitions_vertical_id'), table_name='workflow_definitions')
    op.drop_index(op.f('ix_workflow_definitions_subject_type'), table_name='workflow_definitions')
    op.drop_index(op.f('ix_workflow_definitions_status'), table_name='workflow_definitions')
    op.drop_index(op.f('ix_workflow_definitions_organization_id'), table_name='workflow_definitions')
    op.drop_index(op.f('ix_workflow_definitions_current_version_id'), table_name='workflow_definitions')
    op.drop_index(op.f('ix_workflow_definitions_code'), table_name='workflow_definitions')
    op.drop_table('workflow_definitions')
    op.drop_index(op.f('ix_work_unit_types_organization_id'), table_name='work_unit_types')
    op.drop_index(op.f('ix_work_unit_types_code'), table_name='work_unit_types')
    op.drop_table('work_unit_types')
    op.drop_index(op.f('ix_work_dependencies_successor_id'), table_name='work_dependencies')
    op.drop_index(op.f('ix_work_dependencies_predecessor_id'), table_name='work_dependencies')
    op.drop_index(op.f('ix_work_dependencies_organization_id'), table_name='work_dependencies')
    op.drop_table('work_dependencies')
    op.drop_index(op.f('ix_task_types_organization_id'), table_name='task_types')
    op.drop_index(op.f('ix_task_types_code'), table_name='task_types')
    op.drop_table('task_types')
    op.drop_index(op.f('ix_handovers_to_unit_id'), table_name='handovers')
    op.drop_index(op.f('ix_handovers_subject_type'), table_name='handovers')
    op.drop_index(op.f('ix_handovers_subject_id'), table_name='handovers')
    op.drop_index(op.f('ix_handovers_status'), table_name='handovers')
    op.drop_index(op.f('ix_handovers_parent_handover_id'), table_name='handovers')
    op.drop_index(op.f('ix_handovers_organization_id'), table_name='handovers')
    op.drop_index(op.f('ix_handovers_from_unit_id'), table_name='handovers')
    op.drop_table('handovers')
    op.drop_table('code_sequences')
